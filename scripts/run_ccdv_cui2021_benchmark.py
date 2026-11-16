#!/usr/bin/env python3
"""Benchmark Revised 6-Step Discrete-Cell CCDV (Cui et al., 2021 & Dung's spec) on Hanoi Case 2.

Evaluates 3 cell variants on the 1,215 age 5-14 schools (and 235-school subset):
  1. cui2021_commune_atomic      : 584 communes as atomic C_i (no polygon cutting)
  2. cui2021_commune_fractional  : 584 communes with Left-to-Right x-slice on boundary cell
  3. cui2021_grid500m_atomic     : 500m x 500m grid cells clipped to communes as atomic C_i

Outputs:
  - data/processed/case2/cui2021_benchmark_summary.csv
  - data/processed/case2/figure4_cui2021_comparison.png
  - data/processed/case2/figure4_cui2021_variants_detail.png
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402
from shapely import make_valid  # noqa: E402
from shapely.geometry import box  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from hanoi_ot.capacity import largest_remainder_split  # noqa: E402
from hanoi_ot.ccdv_cui2021 import (  # noqa: E402
    build_commune_units,
    build_grid_units,
    run_ccdv_cui2021,
)
from hanoi_ot.ccvd import _fill_holes  # noqa: E402

CASE2 = REPO / "data" / "processed" / "case2"
CRS = 32648
SERIF = {"family": "serif", "size": 11}
INSETS = {
    "A": (105.80, 21.10, 105.90, 21.17),
    "B": (105.82, 21.00, 105.87, 21.04),
    "C": (105.74, 20.95, 105.80, 21.00),
}
PALETTE = [
    "#66c2a5", "#fc8d62", "#8da0cb", "#e78ac3", "#a6d854", "#ffd92f", "#e5c494",
    "#80b1d3", "#fb8072", "#bebada", "#bc80bd", "#ccebc5", "#ffed6f", "#fdb462",
    "#b3de69", "#4c78b8", "#f0198a", "#d1e8cb", "#fde98a", "#c48fc4",
]


def evaluate_zones(
    name: str,
    zones: dict,
    loads: list[float],
    caps: list[float],
    pts: gpd.GeoDataFrame,
    sch_xy: np.ndarray,
    sec: float,
    total_pop: int,
    city_geom,
    city_area_km2: float,
) -> dict:
    loads_arr = np.asarray(loads, float)
    caps_arr = np.asarray(caps, float)
    ids = list(zones.keys())
    zg = gpd.GeoDataFrame({"k": range(len(ids))}, geometry=[zones[i] for i in ids], crs=CRS)
    zg = zg[~zg.geometry.is_empty]

    # Sampled children distance evaluation
    j = gpd.sjoin(pts, zg, how="left", predicate="within").groupby(level=0)["k"].first()
    ok = j.notna().to_numpy()
    if ok.sum() > 0:
        k = j[ok].astype(int).to_numpy()
        d = (
            np.hypot(
                pts.geometry.x.to_numpy()[ok] - sch_xy[k, 0],
                pts.geometry.y.to_numpy()[ok] - sch_xy[k, 1],
            )
            / 1000.0
        )
        nearest = np.asarray(pts["nearest_km"])[ok]
        mean_km = round(float(d.mean()), 3)
        median_km = round(float(np.median(d)), 3)
        p90_km = round(float(np.percentile(d, 90)), 3)
        max_km = round(float(d.max()), 2)
        pct_not_nearest = round(100.0 * float((d > nearest + 1e-6).mean()), 2)
    else:
        mean_km = median_km = p90_km = max_km = pct_not_nearest = 0.0

    # Covered area vs unassigned area
    valid_geoms = [make_valid(g).buffer(0) for g in zg.geometry if g is not None and not g.is_empty]
    covered_geom = unary_union(valid_geoms) if valid_geoms else box(0, 0, 0, 0)
    covered_km2 = float(covered_geom.intersection(city_geom).area) / 1e6
    unassigned_km2 = max(0.0, city_area_km2 - covered_km2)

    n_schools = len(caps_arr)
    within_5 = int((np.abs(loads_arr - caps_arr) <= 0.05 * caps_arr).sum())

    return {
        "method": name,
        "n_schools": n_schools,
        "within_5pct": within_5,
        "pct_within_5pct": round(100.0 * within_5 / n_schools, 1),
        "empty_zones": int((loads_arr <= 1e-6).sum()),
        "overloaded_gt_5pct": int((loads_arr > caps_arr * 1.05).sum()),
        "min_load": round(float(loads_arr.min())),
        "max_load": round(float(loads_arr.max())),
        "std_load": round(float(loads_arr.std()), 1),
        "students_above_capacity": round(float(np.clip(loads_arr - caps_arr, 0, None).sum())),
        "allocated_students": round(float(loads_arr.sum())),
        "unassigned_students": round(float(total_pop - loads_arr.sum())),
        "unassigned_sample_pct": round(100.0 * (1.0 - float(ok.mean())), 2),
        "unassigned_area_km2": round(unassigned_km2, 2),
        "unassigned_area_pct": round(100.0 * unassigned_km2 / city_area_km2, 1),
        "mean_km": mean_km,
        "median_km": median_km,
        "p90_km": p90_km,
        "max_km": max_km,
        "pct_not_nearest_school": pct_not_nearest,
        "seconds": round(sec, 2),
    }


def zone_colors(n: int) -> list[str]:
    rng = np.random.default_rng(42)
    return [PALETTE[i] for i in rng.integers(0, len(PALETTE), n)]


def render_comparison_figure(
    communes: gpd.GeoDataFrame,
    schools: gpd.GeoDataFrame,
    panels_data: list[tuple[str, gpd.GeoDataFrame, dict]],
    out_path: Path,
) -> None:
    """Render 4-panel comparison map with zoom insets A, B, C."""
    insets = {k: gpd.GeoSeries([box(*b)], crs=4326).to_crs(CRS).iloc[0].bounds for k, b in INSETS.items()}
    city = unary_union([make_valid(g).buffer(0) for g in communes.geometry])
    xmin, ymin, xmax, ymax = communes.total_bounds

    n_panels = len(panels_data)
    fig = plt.figure(figsize=(16, 6.2 * n_panels))

    for p_idx, (title, zones_gdf, m_row) in enumerate(panels_data):
        # Compute vertical band for this panel (top to bottom)
        band_h = 0.92 / n_panels
        bottom = 0.96 - (p_idx + 1) * band_h

        ax = fig.add_axes([0.02, bottom + 0.015, 0.62, band_h - 0.035])
        z = zones_gdf[~zones_gdf.geometry.is_empty].copy()
        z["color"] = zone_colors(len(z))
        z.plot(ax=ax, color=z["color"], edgecolor="#222222", linewidth=0.25)

        valid_geoms = [make_valid(g).buffer(0) for g in z.geometry if g is not None and not g.is_empty]
        covered = unary_union(valid_geoms) if valid_geoms else box(0, 0, 0, 0)
        unassigned_geom = city.difference(covered)
        unassigned_gs = gpd.GeoSeries([unassigned_geom], crs=CRS)
        if not unassigned_geom.is_empty:
            unassigned_gs.plot(ax=ax, facecolor="#d9d9d9", edgecolor="#444444", hatch="////", linewidth=0.35)

        schools.plot(ax=ax, marker="^", color="black", markersize=2.5)
        ax.set_axis_off()
        ax.set_xlim(xmin, xmax)
        ax.set_ylim(ymin - (ymax - ymin) * 0.04, ymax)

        # Stats box inside map
        stats_txt = (
            f"Within ±5%: {m_row['within_5pct']}/{m_row['n_schools']} ({m_row['pct_within_5pct']}%)\n"
            f"Empty zones: {m_row['empty_zones']} | Over >5%: {m_row['overloaded_gt_5pct']}\n"
            f"Unassigned pop: {m_row['unassigned_students']:,} | Area: {m_row['unassigned_area_pct']}%\n"
            f"Mean dist: {m_row['mean_km']:.2f} km (P90: {m_row['p90_km']:.2f} km) | t={m_row['seconds']}s"
        )
        ax.text(
            0.02,
            0.22,
            stats_txt,
            transform=ax.transAxes,
            fontsize=9.5,
            family="monospace",
            bbox=dict(facecolor="white", alpha=0.92, edgecolor="#333333", boxstyle="round,pad=0.4"),
        )
        fig.text(0.33, bottom + 0.003, title, ha="center", fontdict={**SERIF, "weight": "bold", "size": 12})

        for i, (key, (x0, y0, x1, y1)) in enumerate(insets.items()):
            ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False, edgecolor="black", lw=1.4))
            ax.text(
                x0, y1, key, fontsize=9, fontweight="bold", ha="left", va="bottom",
                bbox=dict(facecolor="white", edgecolor="black", pad=1.2),
            )
            sub_h = (band_h - 0.04) / 3.0
            iax = fig.add_axes([0.66, bottom + 0.015 + (2 - i) * sub_h, 0.31, sub_h - 0.008])
            z.plot(ax=iax, color=z["color"], edgecolor="#222222", linewidth=0.5)
            if not unassigned_geom.is_empty:
                unassigned_gs.plot(ax=iax, facecolor="#d9d9d9", edgecolor="#444444", hatch="////", linewidth=0.35)
            schools.plot(ax=iax, marker="^", color="black", markersize=10)
            iax.set_xlim(x0, x1)
            iax.set_ylim(y0, y1)
            iax.set_xticks([])
            iax.set_yticks([])
            for sp in iax.spines.values():
                sp.set_linewidth(1.2)
            iax.text(
                0.03, 0.93, f"Inset {key}", transform=iax.transAxes, fontsize=9.5, fontweight="bold", va="top",
                bbox=dict(facecolor="white", edgecolor="black", pad=1.2),
            )

    fig.text(
        0.5,
        0.005,
        "Comparison of Old Buffer-Loop CCVD vs. Revised 6-Step Discrete-Cell CCDV (Cui et al., 2021 / Dung's Left-to-Right Spec) on 1,215 Hanoi Schools.",
        ha="center",
        fontdict={**SERIF, "size": 12, "weight": "bold"},
    )
    fig.savefig(out_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"Saved {out_path}")


def main() -> None:
    bnd = gpd.read_file(REPO / "data" / "processed" / "hanoi_boundaries.geojson").to_crs(CRS)
    dens = pd.read_csv(CASE2 / "scenario2_commune_density.csv")
    assert list(dens.commune_id) == list(bnd.commune_id)
    bnd["children_5_14"] = dens["children_5_14"].to_numpy()
    total_pop = int(dens["children_5_14"].sum())

    city_geom = unary_union([make_valid(g).buffer(0) for g in bnd.geometry])
    city_area_km2 = float(city_geom.area) / 1e6

    # Load 1,215 schools
    s = pd.read_csv(CASE2 / "scenario2_schools_age5_14.csv", dtype={"facility_id": str})
    g = gpd.GeoDataFrame(s, geometry=gpd.points_from_xy(s.longitude, s.latitude), crs=4326).to_crs(CRS)
    caps = largest_remainder_split(total_pop, len(g))
    sch = {r.facility_id: {"point": r.geometry, "capacity": float(caps[i])} for i, r in enumerate(g.itertuples())}
    sch_xy = np.c_[g.geometry.x, g.geometry.y]

    # Sampled children for distance metrics
    pts = gpd.read_file(CASE2 / "scenario2_sampled_children.geojson").to_crs(CRS)
    px, py = pts.geometry.x.to_numpy(), pts.geometry.y.to_numpy()
    pts["nearest_km"] = [
        np.hypot(sch_xy[:, 0] - x, sch_xy[:, 1] - y).min() / 1000.0 for x, y in zip(px, py)
    ]

    rows: list[dict] = []

    # 0. Load existing Voronoi and Old Buffer CCVD GeoJSONs to compute unified area + distance metrics
    vor_gdf = gpd.read_file(CASE2 / "scenario2_voronoi_zones.geojson").to_crs(CRS)
    vor_zones = {str(r.facility_id): r.geometry for r in vor_gdf.itertuples()}
    vor_loads = [float(r.voronoi_students) for r in vor_gdf.itertuples()]
    rows.append(
        evaluate_zones(
            "voronoi_plain", vor_zones, vor_loads, caps, pts, sch_xy, 0.2, total_pop, city_geom, city_area_km2
        )
    )

    old_ccvd_gdf = gpd.read_file(CASE2 / "scenario2_ccvd_zones.geojson").to_crs(CRS)
    old_zones = {str(r.facility_id): r.geometry for r in old_ccvd_gdf.itertuples()}
    old_loads = [float(r.allocated_students) for r in old_ccvd_gdf.itertuples()]
    rows.append(
        evaluate_zones(
            "old_ccvd_buffer_center_voronoi",
            old_zones,
            old_loads,
            caps,
            pts,
            sch_xy,
            81.5,
            total_pop,
            city_geom,
            city_area_km2,
        )
    )

    # Build community units
    commune_units = build_commune_units(bnd, pop_col="children_5_14", id_col="commune_id")
    t_grid0 = time.perf_counter()
    grid500_units = build_grid_units(bnd, pop_col="children_5_14", id_col="commune_id", cell_size_m=500.0)
    grid_adapt_units = build_grid_units(
        bnd, pop_col="children_5_14", id_col="commune_id", cell_size_m=500.0, max_cell_pop=42.0
    )
    grid_build_sec = time.perf_counter() - t_grid0
    print(
        f"Built {len(commune_units)} commune units, {len(grid500_units)} 500m-grid units, "
        f"and {len(grid_adapt_units)} adaptive-grid units in {grid_build_sec:.2f}s"
    )

    variants = [
        (
            "cui2021_commune_atomic",
            commune_units,
            "atomic",
            "(b) Revised Cui2021 — Variant 1: 584 Communes Atomic (No Cutting)",
        ),
        (
            "cui2021_grid500m_atomic",
            grid500_units,
            "atomic",
            "(c) Revised Cui2021 — Variant 2: 500m Uniform Grid Atomic (22,023 cells)",
        ),
        (
            "cui2021_grid_adaptive_atomic",
            grid_adapt_units,
            "atomic",
            "(d) Revised Cui2021 — Variant 3: Capacity-Bounded Grid Atomic (p_i <= 0.05*q_j, Dung's Grid Spec)",
        ),
        (
            "cui2021_commune_fractional",
            commune_units,
            "fractional_last",
            "(e) Revised Cui2021 — Variant 4: 584 Communes + Left-to-Right Boundary Slice",
        ),
    ]

    panels_for_fig = [
        (
            f"(a) Old Buffer-Loop CCVD (Center-Out) — {rows[-1]['within_5pct']}/1215 within ±5%, {rows[-1]['empty_zones']} empty zones",
            old_ccvd_gdf,
            rows[-1],
        )
    ]

    for v_name, v_units, v_mode, v_title in variants:
        t0 = time.perf_counter()
        zones, st, leftover, unass_pop = run_ccdv_cui2021(
            sch,
            v_units,
            city_geom,
            eps=0.05,
            init_expand_m=100.0,
            step_expand_m=10.0,
            max_expand_m=150000.0,
            assignment_mode=v_mode,
        )
        sec = time.perf_counter() - t0
        ordered_zones = {sid: zones[sid] for sid in sch}
        loads = [float(st[sid]["allocated_students"]) for sid in sch]
        m_row = evaluate_zones(
            v_name, ordered_zones, loads, caps, pts, sch_xy, sec, total_pop, city_geom, city_area_km2
        )
        rows.append(m_row)
        print(json.dumps(m_row), flush=True)

        # Save GeoJSON for this variant
        z_gdf = gpd.GeoDataFrame(
            {
                "facility_id": list(sch.keys()),
                "target_capacity": caps,
                "allocated_students": loads,
                "within_5pct": [st[sid]["within_5pct"] for sid in sch],
                "processing_rank": [st[sid]["processing_rank"] for sid in sch],
                "expand_radius_m": [st[sid]["expand_radius_m"] for sid in sch],
            },
            geometry=[ordered_zones[sid] for sid in sch],
            crs=CRS,
        )
        z_gdf.to_file(CASE2 / f"scenario2_{v_name}_zones.geojson", driver="GeoJSON")
        panels_for_fig.append((v_title, z_gdf, m_row))

    df_out = pd.DataFrame(rows)
    csv_path = CASE2 / "cui2021_benchmark_summary.csv"
    df_out.to_csv(csv_path, index=False)
    print(f"\nSaved benchmark summary to {csv_path}")
    print(df_out.to_string(index=False))

    # Render main 4-panel comparison figure: (a) Old Buffer CCVD, (b) Commune Atomic, (c) Adaptive Grid Atomic, (d) Commune Fractional
    four_panels = [panels_for_fig[0], panels_for_fig[1], panels_for_fig[3], panels_for_fig[4]]
    render_comparison_figure(
        bnd,
        g,
        four_panels,
        CASE2 / "figure4_cui2021_comparison.png",
    )


if __name__ == "__main__":
    main()
