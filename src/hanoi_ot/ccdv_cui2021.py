"""Revised Discrete-Unit CCDV Algorithm (Cui et al., 2021 & Dung's Left-to-Right Cell Spec).

Implements the 6-step sequential allocation procedure from `CCDV_Methodology_Revised.pdf`
and Phạm Hiếu Dũng's design specification:
  - Step 1: Construct Voronoi cells V_j for active schools within study area Omega (EPSG:32648).
  - Step 2: Order active Voronoi cells by centroid G_j = (X_j, Y_j) ascending (Left-to-Right,
            then Bottom-to-Top relative to bottom-left origin (0, 0) of Omega).
  - Step 3: Collect unassigned community units C_i in the chosen V_j, sort their centroids
            g_i = (x_i, y_i) ascending (Left-to-Right, then Bottom-to-Top), and accumulate
            student loads p_i until |M_j - q_j| <= eps * q_j (leaving surplus right-side cells
            for subsequent eastern schools).
  - Step 4: If total students inside V_j is < (1 - eps) * q_j, expand outward from V_j starting
            at 100 m and increasing by +10 m per iteration, accumulating newly reached units
            sorted by (x_i, y_i) until |M_j - q_j| <= eps * q_j.
  - Step 5: Finalize school s_j, remove s_j and its assigned units A_j from the active pool,
            and reconstruct Voronoi diagram for remaining schools.
  - Step 6: When only 2 schools remain, split Omega by the analytic perpendicular bisector
            between the 2 schools, run Step 3/4 on the left-most school, then allocate remaining
            units to the last school within tolerance and report any unassigned units.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Dict, List, Literal, Tuple

import geopandas as gpd
import numpy as np
import shapely
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import split, unary_union, voronoi_diagram
from shapely.strtree import STRtree

from hanoi_ot.ccvd import _as_area, _fill_holes, _robust


@dataclass
class CommunityUnit:
    """Discrete spatial community unit C_i with centroid g_i and student population p_i."""

    unit_id: str
    geometry: shapely.Geometry
    centroid_x: float
    centroid_y: float
    population: float


def build_commune_units(
    communes_gdf: gpd.GeoDataFrame,
    pop_col: str = "children_5_14",
    id_col: str = "commune_id",
) -> List[CommunityUnit]:
    """Build 584 commune-level CommunityUnit objects in metric CRS (EPSG:32648)."""
    units: List[CommunityUnit] = []
    for row in communes_gdf.itertuples():
        geom = _as_area(row.geometry)
        c = geom.centroid
        pop = float(getattr(row, pop_col))
        uid = str(getattr(row, id_col))
        units.append(
            CommunityUnit(
                unit_id=uid,
                geometry=geom,
                centroid_x=float(c.x),
                centroid_y=float(c.y),
                population=pop,
            )
        )
    return units


def build_grid_units(
    communes_gdf: gpd.GeoDataFrame,
    pop_col: str = "children_5_14",
    id_col: str = "commune_id",
    cell_size_m: float = 500.0,
    max_cell_pop: float | None = None,
) -> List[CommunityUnit]:
    """Discretize commune polygons into metric grid cells C_i (default 500m x 500m).

    Each grid fragment inside commune k receives population proportional to its area share
    of commune k, guaranteeing exact conservation of each commune's student count.
    If max_cell_pop is provided, any cell whose population exceeds max_cell_pop is subdivided
    into a k x k sub-grid so that discrete atomic accumulation does not jump over [0.95*q_j, 1.05*q_j].
    """
    minx, miny, maxx, maxy = communes_gdf.total_bounds
    xs = np.arange(math.floor(minx), math.ceil(maxx) + cell_size_m, cell_size_m)
    ys = np.arange(math.floor(miny), math.ceil(maxy) + cell_size_m, cell_size_m)

    grid_boxes = []
    grid_coords = []
    for ix in range(len(xs) - 1):
        x0, x1 = float(xs[ix]), float(xs[ix + 1])
        for iy in range(len(ys) - 1):
            y0, y1 = float(ys[iy]), float(ys[iy + 1])
            grid_boxes.append(box(x0, y0, x1, y1))
            grid_coords.append((ix, iy))

    tree = STRtree(grid_boxes)
    units: List[CommunityUnit] = []

    for row in communes_gdf.itertuples():
        c_geom = _as_area(row.geometry)
        c_area = float(c_geom.area)
        c_pop = float(getattr(row, pop_col))
        c_id = str(getattr(row, id_col))
        if c_area <= 0.0 or c_pop <= 0.0:
            continue

        cand_idxs = tree.query(c_geom, predicate="intersects")
        pieces = []
        areas = []
        for idx in cand_idxs:
            idx_int = int(idx)
            inter = _as_area(_robust(shapely.intersection, c_geom, grid_boxes[idx_int]))
            if not inter.is_empty and inter.area > 1e-3:
                pieces.append((grid_coords[idx_int], inter))
                areas.append(float(inter.area))

        total_piece_area = sum(areas)
        if total_piece_area <= 0.0:
            pt = c_geom.centroid
            units.append(CommunityUnit(c_id, c_geom, float(pt.x), float(pt.y), c_pop))
            continue

        for (ix, iy), inter in pieces:
            share = float(inter.area) / total_piece_area
            piece_pop = c_pop * share
            if max_cell_pop is not None and piece_pop > max_cell_pop and inter.area > 1.0:
                k_sub = max(2, int(math.ceil(math.sqrt(piece_pop / (0.8 * max_cell_pop)))))
                b0x, b0y, b1x, b1y = inter.bounds
                sx = np.linspace(b0x, b1x, k_sub + 1)
                sy = np.linspace(b0y, b1y, k_sub + 1)
                sub_pieces = []
                sub_areas = []
                for six in range(k_sub):
                    for siy in range(k_sub):
                        sbox = box(float(sx[six]), float(sy[siy]), float(sx[six + 1]), float(sy[siy + 1]))
                        s_inter = _as_area(_robust(shapely.intersection, inter, sbox))
                        if not s_inter.is_empty and s_inter.area > 1e-3:
                            sub_pieces.append(((six, siy), s_inter))
                            sub_areas.append(float(s_inter.area))
                sub_tot = sum(sub_areas)
                if sub_tot > 0.0:
                    for (six, siy), s_inter in sub_pieces:
                        s_share = float(s_inter.area) / sub_tot
                        spt = s_inter.centroid
                        units.append(
                            CommunityUnit(
                                unit_id=f"{c_id}_g{ix}_{iy}_s{six}_{siy}",
                                geometry=s_inter,
                                centroid_x=float(spt.x),
                                centroid_y=float(spt.y),
                                population=piece_pop * s_share,
                            )
                        )
                    continue

            pt = inter.centroid
            units.append(
                CommunityUnit(
                    unit_id=f"{c_id}_g{ix}_{iy}",
                    geometry=inter,
                    centroid_x=float(pt.x),
                    centroid_y=float(pt.y),
                    population=piece_pop,
                )
            )
    return units


def build_subcommune_units(
    communes_gdf: gpd.GeoDataFrame,
    pop_col: str = "children_5_14",
    id_col: str = "commune_id",
    max_cell_pop: float = 42.0,
    seed: int = 42,
) -> List[CommunityUnit]:
    """Subdivide each commune polygon into natural polygonal Voronoi sub-communes C_i.

    Guarantees exact student population conservation per commune while ensuring every
    sub-commune polygon has <= max_cell_pop students (default 42 <= 0.05 * q_j).
    """
    from shapely.geometry import MultiPoint

    def _subdivide_poly(
        geom: shapely.Geometry,
        pop: float,
        max_p: float,
        rng: np.random.Generator,
    ) -> List[Tuple[shapely.Geometry, float]]:
        if pop <= max_p or geom.area <= 5.0:
            return [(geom, pop)]
        k = max(2, min(12, int(math.ceil(pop / (0.75 * max_p)))))
        minx, miny, maxx, maxy = geom.bounds
        nx = max(3, int(math.ceil(math.sqrt(k * 2.5 * (maxx - minx) / max(1.0, maxy - miny)))))
        ny = max(3, int(math.ceil((k * 2.5) / nx)))
        xs = np.linspace(minx, maxx, nx + 2)[1:-1]
        ys = np.linspace(miny, maxy, ny + 2)[1:-1]
        xx, yy = np.meshgrid(xs, ys)
        dx = (maxx - minx) / (nx * 3.0)
        dy = (maxy - miny) / (ny * 3.0)
        jx = xx.ravel() + rng.uniform(-dx, dx, size=xx.size)
        jy = yy.ravel() + rng.uniform(-dy, dy, size=yy.size)
        cand_pts = shapely.points(jx, jy)
        inside = cand_pts[shapely.contains(geom, cand_pts)]
        if len(inside) > k:
            idx_pick = np.linspace(0, len(inside) - 1, k, dtype=int)
            inside = inside[idx_pick]
        if len(inside) < 2:
            rp = geom.representative_point()
            span = max(maxx - minx, maxy - miny) * 0.15
            inside = [
                Point(rp.x - span, rp.y - span * 0.3),
                Point(rp.x + span, rp.y + span * 0.3),
            ]
        vd = voronoi_diagram(MultiPoint(list(inside)), envelope=geom.envelope.buffer(200.0))
        pieces = [_as_area(_robust(shapely.intersection, geom, reg)) for reg in vd.geoms]
        pieces = [p for p in pieces if not p.is_empty and p.area > 1.0]
        tot_a = sum(p.area for p in pieces)
        if tot_a <= 0.0 or len(pieces) < 2:
            return [(geom, pop)]
        out: List[Tuple[shapely.Geometry, float]] = []
        for p in pieces:
            p_pop = pop * (p.area / tot_a)
            if p_pop > max_p:
                out.extend(_subdivide_poly(p, p_pop, max_p, rng))
            else:
                out.append((p, p_pop))
        return out

    rng = np.random.default_rng(seed)
    units: List[CommunityUnit] = []
    uid_c = 0
    for row in communes_gdf.itertuples():
        geom = _as_area(row.geometry)
        pop = float(getattr(row, pop_col))
        c_id = str(getattr(row, id_col))
        for p_geom, p_pop in _subdivide_poly(geom, pop, max_cell_pop, rng):
            uid_c += 1
            pt = p_geom.centroid
            units.append(
                CommunityUnit(
                    unit_id=f"{c_id}_sc{uid_c}",
                    geometry=p_geom,
                    centroid_x=float(pt.x),
                    centroid_y=float(pt.y),
                    population=p_pop,
                )
            )
    return units


def two_school_voronoi_cells(
    s1_id: str,
    p1: Point,
    s2_id: str,
    p2: Point,
    domain: shapely.Geometry,
) -> Dict[str, shapely.Geometry]:
    """Split domain along the exact perpendicular bisector between two schools (Step 6)."""
    if domain.is_empty:
        return {s1_id: Polygon(), s2_id: Polygon()}

    dx = float(p2.x - p1.x)
    dy = float(p2.y - p1.y)
    dist = math.hypot(dx, dy)
    if dist < 1e-6:
        return {s1_id: domain, s2_id: Polygon()}

    mx = 0.5 * (p1.x + p2.x)
    my = 0.5 * (p1.y + p2.y)
    # Unit normal perpendicular to (dx, dy)
    nx = -dy / dist
    ny = dx / dist

    minx, miny, maxx, maxy = domain.bounds
    span = max(maxx - minx, maxy - miny, 1000.0) * 5.0
    bisector = LineString(
        [(mx - nx * span, my - ny * span), (mx + nx * span, my + ny * span)]
    )

    parts = split(domain, bisector)
    g1_list = []
    g2_list = []
    for geom in getattr(parts, "geoms", [parts]):
        geom_area = _as_area(geom)
        if geom_area.is_empty:
            continue
        rep = geom_area.representative_point()
        if rep.distance(p1) <= rep.distance(p2):
            g1_list.append(geom_area)
        else:
            g2_list.append(geom_area)

    return {
        s1_id: _as_area(unary_union(g1_list)) if g1_list else Polygon(),
        s2_id: _as_area(unary_union(g2_list)) if g2_list else Polygon(),
    }


def active_voronoi_cells(
    active_schools: Dict[str, dict],
    domain: shapely.Geometry,
) -> Dict[str, shapely.Geometry]:
    """Construct Voronoi cells for active schools (supports >=3, ==2, and ==1 schools)."""
    n = len(active_schools)
    if n == 0 or domain.is_empty:
        return {s_id: Polygon() for s_id in active_schools}
    if n == 1:
        only_id = next(iter(active_schools))
        return {only_id: domain}
    if n == 2:
        (id1, info1), (id2, info2) = list(active_schools.items())
        return two_school_voronoi_cells(id1, info1["point"], id2, info2["point"], domain)

    pts = unary_union([v["point"] for v in active_schools.values()])
    envelope = domain.envelope.buffer(100000.0)
    raw_regions = voronoi_diagram(pts, envelope=envelope)

    cells: Dict[str, shapely.Geometry] = {}
    reg_list = list(raw_regions.geoms)
    reg_tree = STRtree(reg_list)
    for s_id, info in active_schools.items():
        pt = info["point"]
        cand_idxs = reg_tree.query(pt)
        matched = None
        for idx in cand_idxs:
            reg = reg_list[int(idx)]
            if reg.contains(pt) or reg.touches(pt):
                matched = _as_area(_robust(shapely.intersection, reg, domain))
                break
        if matched is None:
            for reg in reg_list:
                if reg.contains(pt) or reg.touches(pt):
                    matched = _as_area(_robust(shapely.intersection, reg, domain))
                    break
        cells[s_id] = matched if matched is not None else Polygon()
    return cells


def slice_unit_left_to_right(
    unit: CommunityUnit,
    needed_pop: float,
) -> Tuple[CommunityUnit, CommunityUnit]:
    """Slice a CommunityUnit vertically from Left to Right so the left piece has needed_pop."""
    geom = _as_area(unit.geometry)
    total_area = float(geom.area)
    frac = max(0.0, min(1.0, needed_pop / unit.population))
    minx, miny, maxx, maxy = geom.bounds

    lo, hi = minx, maxx
    target_area = total_area * frac
    best_left = Polygon()
    for _ in range(25):
        mid = 0.5 * (lo + hi)
        left_box = box(minx - 1.0, miny - 1.0, mid, maxy + 1.0)
        left_piece = _as_area(_robust(shapely.intersection, geom, left_box))
        if left_piece.area < target_area:
            lo = mid
        else:
            hi = mid
        best_left = left_piece

    right_box = box(0.5 * (lo + hi), miny - 1.0, maxx + 1.0, maxy + 1.0)
    right_piece = _as_area(_robust(shapely.intersection, geom, right_box))
    if right_piece.is_empty:
        right_piece = _as_area(_robust(shapely.difference, geom, best_left))

    c_left = best_left.centroid if not best_left.is_empty else Point(unit.centroid_x, unit.centroid_y)
    c_right = right_piece.centroid if not right_piece.is_empty else Point(unit.centroid_x, unit.centroid_y)

    left_unit = CommunityUnit(
        unit_id=f"{unit.unit_id}_L",
        geometry=best_left,
        centroid_x=float(c_left.x),
        centroid_y=float(c_left.y),
        population=needed_pop,
    )
    right_unit = CommunityUnit(
        unit_id=f"{unit.unit_id}_R",
        geometry=right_piece,
        centroid_x=float(c_right.x),
        centroid_y=float(c_right.y),
        population=max(0.0, unit.population - needed_pop),
    )
    return left_unit, right_unit


def run_ccdv_cui2021(
    schools: Dict[str, dict],
    units: List[CommunityUnit],
    study_area: shapely.Geometry,
    eps: float = 0.05,
    init_expand_m: float = 100.0,
    step_expand_m: float = 10.0,
    max_expand_m: float = 150000.0,
    assignment_mode: Literal["atomic", "fractional_last"] = "atomic",
    step3_membership: Literal["centroid", "intersects"] = "centroid",
) -> Tuple[Dict[str, shapely.Geometry], Dict[str, dict], List[CommunityUnit], float]:
    """Execute the 6-step Revised CCDV algorithm (Cui et al., 2021 & Dung's spec).

    Returns:
        (final_zones, stats, unassigned_units, unassigned_population)
    """
    clean_domain = _fill_holes(_as_area(study_area))
    origin_x, origin_y, _, _ = clean_domain.bounds

    active_schools = dict(schools)
    # Pool of unassigned units keyed by integer index
    pool: Dict[int, CommunityUnit] = {i: u for i, u in enumerate(units) if u.population > 0.0}
    next_uid_idx = len(units)

    final_zones: Dict[str, shapely.Geometry] = {}
    stats: Dict[str, dict] = {}
    rank = 0

    def _unit_sort_key(idx: int) -> Tuple[float, float, str]:
        u = pool[idx]
        return (
            round(u.centroid_x - origin_x, 3),
            round(u.centroid_y - origin_y, 3),
            u.unit_id,
        )

    def _accumulate_from_candidates(
        cand_indices: List[int],
        current_load: float,
        q_j: float,
        assigned_geoms: List[shapely.Geometry],
        assigned_ids: List[str],
    ) -> Tuple[float, bool]:
        """Accumulate candidate units (already sorted Left-to-Right) up to [0.95*q_j, 1.05*q_j]."""
        nonlocal next_uid_idx
        low_b = (1.0 - eps) * q_j
        high_b = (1.0 + eps) * q_j

        for idx in cand_indices:
            if idx not in pool:
                continue
            u = pool[idx]
            new_load = current_load + u.population

            # If already within [0.95*q_j, 1.05*q_j], only take u if it gets closer to q_j
            if low_b <= current_load <= high_b:
                if new_load <= high_b and abs(new_load - q_j) <= abs(current_load - q_j):
                    current_load = new_load
                    assigned_geoms.append(u.geometry)
                    assigned_ids.append(u.unit_id)
                    del pool[idx]
                    continue
                return current_load, True

            if new_load <= high_b:
                current_load = new_load
                assigned_geoms.append(u.geometry)
                assigned_ids.append(u.unit_id)
                del pool[idx]
                if current_load >= q_j:
                    return current_load, True
            else:
                # Adding full unit u would exceed (1 + eps) * q_j while current_load < (1 - eps) * q_j
                if assignment_mode == "fractional_last":
                    needed = max(0.0, q_j - current_load)
                    if needed > 0.0:
                        left_u, right_u = slice_unit_left_to_right(u, needed)
                        current_load += left_u.population
                        assigned_geoms.append(left_u.geometry)
                        assigned_ids.append(left_u.unit_id)
                        del pool[idx]
                        if right_u.population > 1e-6 and not right_u.geometry.is_empty:
                            pool[next_uid_idx] = right_u
                            next_uid_idx += 1
                    return current_load, True
                else:
                    # Atomic mode: decide whether taking u gets closer to q_j than stopping now
                    if current_load == 0.0 or abs(new_load - q_j) <= abs(current_load - q_j):
                        current_load = new_load
                        assigned_geoms.append(u.geometry)
                        assigned_ids.append(u.unit_id)
                        del pool[idx]
                        return current_load, True
                    # Otherwise do not take this oversized unit; try next or stop if none fit
        return current_load, (low_b <= current_load <= high_b)

    while active_schools and pool:
        rank += 1
        # Step 1 & Step 6: Build Voronoi diagram for active schools (analytic bisector when 2 left)
        vor_cells = active_voronoi_cells(active_schools, clean_domain)

        # Step 2: Compute centroid G_j of each Voronoi cell V_j and sort by (X_j, Y_j) ascending
        def _school_sort_key(s_id: str) -> Tuple[float, float, float, float, str]:
            pt: Point = active_schools[s_id]["point"]
            cell = vor_cells.get(s_id, Polygon())
            g_pt = cell.centroid if (cell is not None and not cell.is_empty) else pt
            return (
                round(float(g_pt.x - origin_x), 3),
                round(float(g_pt.y - origin_y), 3),
                round(float(pt.x - origin_x), 3),
                round(float(pt.y - origin_y), 3),
                str(s_id),
            )

        s_id = min(active_schools.keys(), key=_school_sort_key)
        q_j = float(active_schools[s_id]["capacity"])
        v_j = vor_cells.get(s_id, Polygon())
        if v_j is None or v_j.is_empty:
            v_j = active_schools[s_id]["point"].buffer(1.0)

        # Step 3: Find unassigned community units inside V_j
        pool_keys = list(pool.keys())
        if step3_membership == "centroid":
            pts_arr = shapely.points(
                [pool[k].centroid_x for k in pool_keys],
                [pool[k].centroid_y for k in pool_keys],
            )
            mask_in = shapely.contains(v_j, pts_arr) | shapely.touches(v_j, pts_arr)
        else:
            geoms_arr = np.array([pool[k].geometry for k in pool_keys], dtype=object)
            mask_in = shapely.intersects(v_j, geoms_arr)

        in_vor_indices = [pool_keys[i] for i, flag in enumerate(mask_in) if flag]
        in_vor_indices.sort(key=_unit_sort_key)

        assigned_geoms: List[shapely.Geometry] = []
        assigned_ids: List[str] = []
        current_load = 0.0
        expand_radius_m = 0.0
        expand_steps = 0

        current_load, satisfied = _accumulate_from_candidates(
            in_vor_indices, current_load, q_j, assigned_geoms, assigned_ids
        )

        # Step 4: If initial Voronoi units provide < 0.95 * q_j, expand outward (100m + 10m/step)
        if not satisfied and current_load < (1.0 - eps) * q_j and pool:
            rem_keys = list(pool.keys())
            if step3_membership == "centroid":
                rem_targets = shapely.points(
                    [pool[k].centroid_x for k in rem_keys],
                    [pool[k].centroid_y for k in rem_keys],
                )
            else:
                rem_targets = np.array([pool[k].geometry for k in rem_keys], dtype=object)

            dists = shapely.distance(v_j, rem_targets)
            # Group remaining units by the exact expansion radius r = 100 + 10*k at which they enter
            ring_buckets: Dict[float, List[int]] = {}
            for k_idx, d_val in zip(rem_keys, dists):
                d_f = float(d_val)
                if d_f > max_expand_m:
                    continue
                if d_f <= init_expand_m:
                    r_entry = float(init_expand_m)
                else:
                    steps_above = math.ceil((d_f - init_expand_m) / step_expand_m)
                    r_entry = float(init_expand_m + steps_above * step_expand_m)
                if r_entry <= max_expand_m:
                    ring_buckets.setdefault(r_entry, []).append(k_idx)

            for r_curr in sorted(ring_buckets.keys()):
                expand_steps += 1
                expand_radius_m = r_curr
                ring_cands = [k for k in ring_buckets[r_curr] if k in pool]
                ring_cands.sort(key=_unit_sort_key)
                current_load, satisfied = _accumulate_from_candidates(
                    ring_cands, current_load, q_j, assigned_geoms, assigned_ids
                )
                if satisfied or current_load >= (1.0 - eps) * q_j:
                    break

        # Step 5: Record zone Z_j and remove school s_j from active set
        z_j = _as_area(unary_union(assigned_geoms)) if assigned_geoms else Polygon()
        err_pct = abs(current_load - q_j) / q_j * 100.0 if q_j > 0 else 0.0
        final_zones[s_id] = z_j
        stats[s_id] = {
            "processing_rank": rank,
            "allocated_students": round(current_load, 2),
            "capacity": q_j,
            "error_pct": round(err_pct, 2),
            "within_5pct": bool(abs(current_load - q_j) <= eps * q_j + 1e-6),
            "n_units": len(assigned_ids),
            "expand_radius_m": round(expand_radius_m, 1),
            "expand_steps": expand_steps,
        }
        del active_schools[s_id]

    # Mark any remaining schools if pool became empty early
    for s_id, info in active_schools.items():
        rank += 1
        q_j = float(info["capacity"])
        final_zones[s_id] = Polygon()
        stats[s_id] = {
            "processing_rank": rank,
            "allocated_students": 0.0,
            "capacity": q_j,
            "error_pct": 100.0 if q_j > 0 else 0.0,
            "within_5pct": False,
            "n_units": 0,
            "expand_radius_m": 0.0,
            "expand_steps": 0,
        }

    leftover_units = list(pool.values())
    unassigned_pop = float(sum(u.population for u in leftover_units))
    ordered_zones = {s_id: final_zones[s_id] for s_id in schools}
    return ordered_zones, stats, leftover_units, unassigned_pop
