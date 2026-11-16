"""Capacity-Constrained Voronoi Diagram (CCVD) — Vector GIS & Raster Grid Solvers.

Implements the iterative Capacity-Constrained Voronoi Diagram (CCVD) algorithm
for partitioning Hanoi's geographic plane into school catchment zones whose
enclosed student populations match target school capacities within tolerance ε.

Supports:
1. Vector GIS mode (Shapely polygons + STRtree spatial indexing + GEOS-hardened
   topological operations).
2. 2D Raster Grid mode (Euclidean distance transform on uniform spatial grids).
3. Deterministic school processing orders:
   - "csv": preserve input dictionary/list order.
   - "center_voronoi": sort remaining schools by distance from their initial
     Voronoi cell centroid to the study-area center (Hanoi centroid), with
     deterministic tie-breaking (distance, school_x, school_y, school_id).
   - "center_school": sort schools by distance from school coordinates to the
     study-area center (Hanoi centroid), with deterministic tie-breaking.
   - "reverse": reverse of input order.
4. Optional leftover second-pass assignment to route unassigned children in
   remaining map fragments to nearest schools with spare capacity.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Literal, Tuple

import numpy as np
import shapely
from scipy.ndimage import distance_transform_edt
from shapely.geometry import MultiPolygon, Point, Polygon
from shapely.ops import unary_union, voronoi_diagram
from shapely.strtree import STRtree

OrderMode = Literal["csv", "center_voronoi", "center_school", "reverse"]


# ---------------------------------------------------------------------------
# Vector GIS CCVD (Shapely polygons + STRtree acceleration)
# ---------------------------------------------------------------------------


def _as_area(g: shapely.Geometry) -> shapely.Geometry:
    """Keep only polygonal area components (drop line/point slivers)."""
    if g is None or g.is_empty or g.geom_type in ("Polygon", "MultiPolygon"):
        return g if g is not None else Polygon()
    polys = [
        p
        for p in getattr(g, "geoms", [])
        if p.geom_type in ("Polygon", "MultiPolygon") and not p.is_empty
    ]
    return unary_union(polys) if polys else Polygon()


def _fill_holes(g: shapely.Geometry) -> shapely.Geometry:
    """Remove internal topological sliver holes from a Polygon or MultiPolygon."""
    g_area = _as_area(g)
    if g_area.is_empty:
        return Polygon()
    parts = list(g_area.geoms) if hasattr(g_area, "geoms") else [g_area]
    shells = [Polygon(p.exterior) for p in parts if p.geom_type == "Polygon" and not p.is_empty]
    return _as_area(unary_union(shells)) if shells else Polygon()


def _robust(op, a: shapely.Geometry, b: shapely.Geometry) -> shapely.Geometry:
    """Execute overlay op(a, b) with 1m grid snap and make_valid fallback on GEOS errors."""
    try:
        return op(a, b)
    except shapely.errors.GEOSException:
        try:
            return op(shapely.set_precision(a, 1.0), shapely.set_precision(b, 1.0))
        except shapely.errors.GEOSException:
            return op(shapely.make_valid(a), shapely.make_valid(b))


class SpatialCommunityIndex:
    """R-Tree accelerated areal interpolation over community polygons."""

    def __init__(self, community_polygons: List[Polygon], densities: List[float]) -> None:
        self.polygons = list(community_polygons)
        self.densities = np.asarray(densities, dtype=float)
        self.tree = STRtree(self.polygons) if self.polygons else None

    def calculate_students(self, zone_poly: shapely.Geometry) -> float:
        if zone_poly is None or zone_poly.is_empty or self.tree is None:
            return 0.0
        idxs = self.tree.query(zone_poly, predicate="intersects")
        if len(idxs) == 0:
            return 0.0
        total = 0.0
        for idx in idxs:
            cs_poly = self.polygons[int(idx)]
            density = float(self.densities[int(idx)])
            if density <= 0.0:
                continue
            inter_area = _robust(shapely.intersection, zone_poly, cs_poly).area
            total += inter_area * density
        return total


def calculate_students(
    zone_poly: shapely.Geometry,
    community_polygons: List[Polygon],
    densities: List[float],
) -> float:
    """Compute student count x_j in zone_poly via areal interpolation."""
    if zone_poly is None or zone_poly.is_empty:
        return 0.0
    total = 0.0
    for cs_poly, density in zip(community_polygons, densities):
        if density > 0.0 and zone_poly.intersects(cs_poly):
            inter_area = _robust(shapely.intersection, zone_poly, cs_poly).area
            total += inter_area * density
    return total


def bounded_voronoi_cells(
    schools: Dict[str, dict],
    remaining_map: shapely.Geometry,
    return_raw: bool = False,
):
    """Construct Voronoi cells V_j for active schools, clipped to remaining_map."""
    if not schools or remaining_map.is_empty:
        empty = {s_id: Polygon() for s_id in schools}
        return (empty, dict(empty)) if return_raw else empty
    if len(schools) == 1:
        only_id = next(iter(schools))
        clipped = {only_id: remaining_map}
        return (clipped, dict(clipped)) if return_raw else clipped

    pts = unary_union([v["point"] for v in schools.values()])
    envelope = remaining_map.envelope.buffer(100000.0)
    raw_regions = voronoi_diagram(pts, envelope=envelope)

    cells: Dict[str, shapely.Geometry] = {}
    raw_cells: Dict[str, shapely.Geometry] = {}
    reg_list = list(raw_regions.geoms)
    reg_tree = STRtree(reg_list)
    for s_id, info in schools.items():
        pt = info["point"]
        cand_idxs = reg_tree.query(pt)
        matched = None
        matched_raw = None
        for idx in cand_idxs:
            reg = reg_list[int(idx)]
            if reg.contains(pt) or reg.touches(pt):
                matched_raw = reg
                matched = _as_area(_robust(shapely.intersection, reg, remaining_map))
                break
        if matched is None:
            for reg in reg_list:
                if reg.contains(pt) or reg.touches(pt):
                    matched_raw = reg
                    matched = _as_area(_robust(shapely.intersection, reg, remaining_map))
                    break
        cells[s_id] = matched if matched is not None else Polygon()
        raw_cells[s_id] = matched_raw if matched_raw is not None else Polygon()
    return (cells, raw_cells) if return_raw else cells


def sort_schools_deterministic(
    schools: Dict[str, dict],
    study_area: shapely.Geometry,
    order_by: OrderMode = "csv",
) -> Dict[str, dict]:
    """Return a deterministically ordered dictionary of schools.

    Args:
        schools: Mapping of school_id -> {"point": Point, "capacity": float}.
        study_area: Unified study area polygon (e.g. Hanoi boundary in UTM meters).
        order_by:
            - "csv": preserve input order.
            - "reverse": reverse input order.
            - "center_school": sort by Euclidean distance from school point to
              Hanoi centroid (closest first), tie-broken by (x, y, str(school_id)).
            - "center_voronoi": sort by Euclidean distance from initial Voronoi
              cell centroid to Hanoi centroid (closest first), tie-broken by
              (school_distance, x, y, str(school_id)).
    """
    if order_by == "csv" or len(schools) <= 1:
        return dict(schools)
    if order_by == "reverse":
        return dict( list(schools.items())[::-1] )

    hanoi_center = study_area.centroid

    if order_by == "center_school":
        def key_school(item: Tuple[str, dict]):
            s_id, info = item
            pt: Point = info["point"]
            dist = round(float(pt.distance(hanoi_center)), 6)
            return (dist, round(pt.x, 3), round(pt.y, 3), str(s_id))

        return dict(sorted(schools.items(), key=key_school))

    if order_by == "center_voronoi":
        initial_cells = bounded_voronoi_cells(schools, study_area)

        def key_voronoi(item: Tuple[str, dict]):
            s_id, info = item
            pt: Point = info["point"]
            cell = initial_cells.get(s_id, Polygon())
            cell_center = cell.centroid if (cell is not None and not cell.is_empty) else pt
            dist_cell = round(float(cell_center.distance(hanoi_center)), 6)
            dist_pt = round(float(pt.distance(hanoi_center)), 6)
            return (dist_cell, dist_pt, round(pt.x, 3), round(pt.y, 3), str(s_id))

        return dict(sorted(schools.items(), key=key_voronoi))

    raise ValueError(f"Unknown order_by mode: {order_by!r}")


def run_ccvd_vector_gis(
    schools: Dict[str, dict],
    community_polygons: List[Polygon],
    densities: List[float],
    eps: float = 0.05,
    delta_r: float = 50.0,
    max_iter: int = 100,
    order_by: OrderMode = "csv",
    dynamic_voronoi_center_selection: bool = False,
) -> Tuple[Dict[str, shapely.Geometry], Dict[str, dict], shapely.Geometry, float]:
    """Run the Vector GIS CCVD algorithm on Shapely polygons.

    Args:
        schools: Dict of school_id -> {"point": Point, "capacity": float}.
        community_polygons: List of commune polygons (in metric CRS, e.g. EPSG:32648).
        densities: List of student densities (students / m²) per commune polygon.
        eps: Relative capacity tolerance (default 0.05 = ±5%).
        delta_r: Initial buffer step size in meters (default 50.0).
        max_iter: Maximum buffer adjustment iterations per school (default 100).
        order_by: Deterministic school ordering ("csv", "center_voronoi",
            "center_school", "reverse").
        dynamic_voronoi_center_selection: If True and order_by == "center_voronoi",
            re-evaluates the active Voronoi cell centroids at every step and picks
            the school whose current Voronoi cell centroid is closest to the initial
            Hanoi centroid. If False (default), sorts once using Step 1 Voronoi cells.

    Returns:
        (final_zones, stats, remaining_map, unassigned_students)
    """
    study_area = _fill_holes(unary_union(community_polygons))
    hanoi_center = study_area.centroid
    remaining_map = study_area

    if dynamic_voronoi_center_selection and order_by == "center_voronoi":
        active_schools = dict(schools)
    else:
        active_schools = sort_schools_deterministic(schools, study_area, order_by=order_by)

    spatial_idx = SpatialCommunityIndex(community_polygons, densities)
    final_zones: Dict[str, shapely.Geometry] = {}
    stats: Dict[str, dict] = {}

    while active_schools and not remaining_map.is_empty:
        voronoi_cells = bounded_voronoi_cells(active_schools, remaining_map)

        if dynamic_voronoi_center_selection and order_by == "center_voronoi":
            def _dyn_key(s_id: str):
                pt: Point = active_schools[s_id]["point"]
                cell = voronoi_cells.get(s_id, Polygon())
                c_pt = cell.centroid if (cell is not None and not cell.is_empty) else pt
                return (
                    round(float(c_pt.distance(hanoi_center)), 6),
                    round(float(pt.distance(hanoi_center)), 6),
                    round(pt.x, 3),
                    round(pt.y, 3),
                    str(s_id),
                )
            s_id = min(active_schools.keys(), key=_dyn_key)
        else:
            s_id = next(iter(active_schools))

        y_j = float(active_schools[s_id]["capacity"])
        v_j_base = voronoi_cells[s_id]
        v_j_src = _fill_holes(v_j_base)
        other_active = (
            _as_area(_robust(shapely.difference, remaining_map, v_j_base))
            if len(active_schools) > 1
            else Polygon()
        )

        r = 0.0
        step = float(delta_r)
        prev_dir = 0
        v_curr = v_j_base
        x_j = spatial_idx.calculate_students(v_curr)

        it = 0
        if not v_j_base.is_empty and y_j > 0:
            while abs(x_j - y_j) > eps * y_j and it < max_iter:
                it += 1
                direction = 1 if x_j < y_j else -1

                if prev_dir != 0 and direction != prev_dir:
                    step *= 0.5

                r += direction * step
                prev_dir = direction

                if r >= 0.0 or other_active.is_empty:
                    v_next = _as_area(_robust(shapely.intersection, v_j_src.buffer(r), remaining_map))
                else:
                    v_next = _as_area(_robust(shapely.difference, v_j_base, other_active.buffer(abs(r))))
                x_next = spatial_idx.calculate_students(v_next)

                if v_next.is_empty or v_next.equals(remaining_map):
                    v_curr, x_j = v_next, x_next
                    break

                v_curr, x_j = v_next, x_next

        final_zones[s_id] = v_curr
        stats[s_id] = {
            "allocated_students": round(x_j, 2),
            "capacity": y_j,
            "error_pct": round(abs(x_j - y_j) / y_j * 100.0, 2) if y_j > 0 else 0.0,
            "iterations": it,
            "final_r_offset": round(r, 2),
        }

        if not v_curr.is_empty:
            remaining_map = _as_area(_robust(shapely.difference, remaining_map, v_curr))
        del active_schools[s_id]

    # Mark any remaining schools (if remaining_map became empty early)
    for s_id, info in active_schools.items():
        y_j = float(info["capacity"])
        final_zones[s_id] = Polygon()
        stats[s_id] = {
            "allocated_students": 0.0,
            "capacity": y_j,
            "error_pct": 100.0 if y_j > 0 else 0.0,
            "iterations": 0,
            "final_r_offset": 0.0,
        }

    unassigned_students = spatial_idx.calculate_students(remaining_map)
    return final_zones, stats, remaining_map, unassigned_students


# ---------------------------------------------------------------------------
# 2D Raster Grid CCVD (Fast numpy / distance_transform_edt implementation)
# ---------------------------------------------------------------------------


@dataclass
class School:
    school_id: str
    x: float
    y: float
    capacity: float  # y_j


@dataclass
class ZoneResult:
    school_id: str
    allocated_students: float  # x_j
    target_capacity: float     # y_j
    relative_error: float      # |x_j - y_j| / y_j
    within_tolerance: bool
    iterations: int
    final_offset_r: float      # cumulative r offset


def compute_voronoi_mask_for_school(
    grid_x: np.ndarray,
    grid_y: np.ndarray,
    active_schools: List[School],
    target_idx: int,
    remaining_map_mask: np.ndarray,
) -> np.ndarray:
    """Construct Voronoi cell V_j on the remaining map without allocating O(M*H*W) memory."""
    if not np.any(remaining_map_mask) or not active_schools:
        return np.zeros_like(remaining_map_mask, dtype=bool)

    target = active_schools[target_idx]
    target_d2 = (grid_x - target.x) ** 2 + (grid_y - target.y) ** 2
    v_j = remaining_map_mask.copy()
    for idx, s in enumerate(active_schools):
        if idx == target_idx:
            continue
        d2 = (grid_x - s.x) ** 2 + (grid_y - s.y) ** 2
        if idx < target_idx:
            v_j &= target_d2 < d2
        else:
            v_j &= target_d2 <= d2
        if not np.any(v_j):
            break
    return v_j


def adjust_region_by_r(
    base_voronoi_mask: np.ndarray,
    r_offset: float,
    cell_size: float,
    remaining_map_mask: np.ndarray,
) -> np.ndarray:
    """Expand (r_offset > 0) or Shrink (r_offset < 0) candidate Voronoi region V_j."""
    if abs(r_offset) < 1e-9 or not np.any(base_voronoi_mask):
        return base_voronoi_mask & remaining_map_mask

    if r_offset > 0:
        dist_outside = distance_transform_edt(~base_voronoi_mask) * cell_size
        expanded = base_voronoi_mask | (dist_outside <= r_offset)
        return expanded & remaining_map_mask
    else:
        dist_inside = distance_transform_edt(base_voronoi_mask) * cell_size
        shrunk = base_voronoi_mask & (dist_inside > abs(r_offset))
        return shrunk & remaining_map_mask


def run_ccvd(
    grid_x: np.ndarray,
    grid_y: np.ndarray,
    student_density_grid: np.ndarray,
    valid_map_mask: np.ndarray,
    schools: List[School],
    tolerance_eps: float = 0.05,
    delta_r: float = 50.0,
    max_iter: int = 200,
    use_adaptive_step: bool = True,
    order_by: OrderMode = "csv",
) -> Tuple[np.ndarray, Dict[str, ZoneResult], float]:
    """Execute the 2D Grid Capacity-Constrained Voronoi Diagram (CCVD) algorithm."""
    dy = float(abs(grid_y[1, 0] - grid_y[0, 0])) if grid_y.shape[0] > 1 else 1.0
    dx = float(abs(grid_x[0, 1] - grid_x[0, 0])) if grid_x.shape[1] > 1 else 1.0
    cell_area = dx * dy
    cell_size = 0.5 * (dx + dy)

    students_per_cell = student_density_grid * cell_area
    remaining_map_mask = valid_map_mask.copy()
    zone_labels = np.full(valid_map_mask.shape, -1, dtype=int)
    results: Dict[str, ZoneResult] = {}

    # Compute Hanoi / valid map centroid for center-based ordering
    if np.any(valid_map_mask):
        center_x = float(np.mean(grid_x[valid_map_mask]))
        center_y = float(np.mean(grid_y[valid_map_mask]))
    else:
        center_x = float(np.mean(grid_x))
        center_y = float(np.mean(grid_y))

    active_entries: List[Tuple[int, School]] = list(enumerate(schools))
    if order_by == "reverse":
        active_entries = active_entries[::-1]
    elif order_by == "center_school":
        active_entries.sort(
            key=lambda item: (
                round(float(np.hypot(item[1].x - center_x, item[1].y - center_y)), 6),
                round(item[1].x, 3),
                round(item[1].y, 3),
                str(item[1].school_id),
            )
        )
    elif order_by == "center_voronoi":
        all_schools = [s for _, s in active_entries]
        vor_keys = []
        for idx, (orig_idx, s) in enumerate(active_entries):
            mask = compute_voronoi_mask_for_school(grid_x, grid_y, all_schools, idx, valid_map_mask)
            if np.any(mask):
                vx, vy = float(np.mean(grid_x[mask])), float(np.mean(grid_y[mask]))
            else:
                vx, vy = s.x, s.y
            d_vor = round(float(np.hypot(vx - center_x, vy - center_y)), 6)
            d_sch = round(float(np.hypot(s.x - center_x, s.y - center_y)), 6)
            vor_keys.append(((d_vor, d_sch, round(s.x, 3), round(s.y, 3), str(s.school_id)), (orig_idx, s)))
        vor_keys.sort(key=lambda x: x[0])
        active_entries = [item for _, item in vor_keys]

    while active_entries:
        active_schools = [s for _, s in active_entries]
        selected_pos = 0
        orig_idx, school_j = active_entries[selected_pos]

        v_j_initial = compute_voronoi_mask_for_school(
            grid_x, grid_y, active_schools, selected_pos, remaining_map_mask
        )

        r_current = 0.0
        step = delta_r
        prev_sign = 0
        v_j_curr = v_j_initial
        x_j = float(np.sum(students_per_cell[v_j_curr]))
        y_j = school_j.capacity

        iters = 0
        if np.any(v_j_initial) and y_j > 0:
            while abs(x_j - y_j) > tolerance_eps * y_j and iters < max_iter:
                iters += 1
                curr_sign = 1 if x_j < y_j else -1

                if use_adaptive_step and prev_sign != 0 and curr_sign != prev_sign:
                    step *= 0.5

                r_current += curr_sign * step
                prev_sign = curr_sign

                v_j_next = adjust_region_by_r(
                    v_j_initial, r_current, cell_size, remaining_map_mask
                )
                x_j_next = float(np.sum(students_per_cell[v_j_next]))

                if x_j_next == x_j and abs(r_current) > max(grid_x.ptp(), grid_y.ptp()):
                    break

                v_j_curr = v_j_next
                x_j = x_j_next

        z_j = v_j_curr
        zone_labels[z_j] = orig_idx
        remaining_map_mask[z_j] = False

        rel_err = abs(x_j - y_j) / y_j if y_j > 0 else 0.0
        results[school_j.school_id] = ZoneResult(
            school_id=school_j.school_id,
            allocated_students=x_j,
            target_capacity=y_j,
            relative_error=rel_err,
            within_tolerance=(rel_err <= tolerance_eps),
            iterations=iters,
            final_offset_r=r_current,
        )

        active_entries.pop(selected_pos)

    unassigned_students = float(np.sum(students_per_cell[remaining_map_mask]))
    return zone_labels, results, unassigned_students
