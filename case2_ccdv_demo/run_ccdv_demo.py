#!/usr/bin/env python3
"""Standalone runner for Case 2: Revised 6-Step Density-Based CCDV Algorithm on Hanoi (1,215 Schools).

Usage:
    python run_ccdv_demo.py                     # Runs default fast benchmark (Boundary-Slice & Bounded-Grid)
    python run_ccdv_demo.py --mode all          # Runs all 4 spatial unit variants
    python run_ccdv_demo.py --mode bounded_grid # Runs Bounded-Grid C_i (p_i <= 42 students, 100% within +-5%)
    python run_ccdv_demo.py --mode slice        # Runs 584 Communes + Left-to-Right Boundary Slice (99.9% within +-5%)
    python run_ccdv_demo.py --mode commune      # Runs 584 Uncut Communes (shows why communes are too coarse: 2.7%)
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import make_valid
from shapely.geometry import box
from shapely.ops import unary_union

from ccdv_cui2021 import (
    build_commune_units,
    build_grid_units,
    largest_remainder_split,
    run_ccdv_cui2021,
)

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
OUT = HERE / "outputs"
CRS = 32648


def evaluate(
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
        mean_km = round(float(d.mean()), 2)
        median_km = round(float(np.median(d)), 2)
        p90_km = round(float(np.percentile(d, 90)), 2)
    else:
        mean_km = median_km = p90_km = 0.0

    valid_geoms = [make_valid(g).buffer(0) for g in zg.geometry if g is not None and not g.is_empty]
    covered = unary_union(valid_geoms) if valid_geoms else box(0, 0, 0, 0)
    unass_km2 = max(0.0, float(city_geom.difference(covered).area) / 1e6)
    if unass_km2 < 0.05:
        unass_km2 = 0.0

    n_schools = len(caps_arr)
    within_5 = int((np.abs(loads_arr - caps_arr) <= 0.05 * caps_arr).sum())

    return {
        "method": name,
        "within_5pct": f"{within_5}/{n_schools} ({100.0 * within_5 / n_schools:.1f}%)",
        "empty_zones": int((loads_arr <= 1e-6).sum()),
        "overloaded_gt_5pct": int((loads_arr > caps_arr * 1.05).sum()),
        "max_load": round(float(loads_arr.max())),
        "unassigned_students": round(float(total_pop - loads_arr.sum())),
        "unassigned_area_km2": f"{unass_km2:.1f} ({100.0 * unass_km2 / city_area_km2:.1f}%)",
        "mean_km": mean_km,
        "median_km": median_km,
        "p90_km": p90_km,
        "seconds": round(sec, 1),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Run Case 2 Revised Density-Based CCDV on 1,215 Hanoi Schools.")
    ap.add_argument(
        "--mode",
        default="default",
        choices=["default", "all", "bounded_grid", "slice", "commune", "grid500m"],
        help="Which spatial unit variant(s) to execute (default runs slice + bounded_grid).",
    )
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)

    print("Loading Hanoi Case 2 spatial datasets (EPSG:32648)...")
    bnd = gpd.read_file(DATA / "hanoi_boundaries.geojson").to_crs(CRS)
    dens = pd.read_csv(DATA / "scenario2_commune_density.csv")
    bnd["children_5_14"] = dens["children_5_14"].to_numpy()
    total_pop = int(dens["children_5_14"].sum())
    city_geom = unary_union([make_valid(g).buffer(0) for g in bnd.geometry])
    city_area_km2 = float(city_geom.area) / 1e6

    s = pd.read_csv(DATA / "scenario2_schools_age5_14.csv", dtype={"facility_id": str})
    g = gpd.GeoDataFrame(s, geometry=gpd.points_from_xy(s.longitude, s.latitude), crs=4326).to_crs(CRS)
    caps = largest_remainder_split(total_pop, len(g))
    sch = {r.facility_id: {"point": r.geometry, "capacity": float(caps[i])} for i, r in enumerate(g.itertuples())}
    sch_xy = np.c_[g.geometry.x, g.geometry.y]

    pts = gpd.read_file(DATA / "scenario2_sampled_children.geojson").to_crs(CRS)
    print(f"Loaded {len(g):,} schools, {len(bnd):,} communes ({city_area_km2:,.2f} km^2), and {total_pop:,} students.\n")

    configs = []
    if args.mode in ("commune", "all"):
        configs.append(("cui2021_commune_atomic", build_commune_units(bnd), "atomic"))
    if args.mode in ("grid500m", "all"):
        configs.append(("cui2021_grid500m_atomic", build_grid_units(bnd, cell_size_m=500.0), "atomic"))
    if args.mode in ("slice", "default", "all"):
        configs.append(("cui2021_commune_fractional", build_commune_units(bnd), "fractional_last"))
    if args.mode in ("bounded_grid", "default", "all"):
        configs.append(
            ("cui2021_grid_adaptive_atomic", build_grid_units(bnd, cell_size_m=500.0, max_cell_pop=42.0), "atomic")
        )

    rows = []
    for name, units, assign_mode in configs:
        print(f"Running {name} ({len(units):,} spatial units, mode={assign_mode})...")
        t0 = time.perf_counter()
        zones, st, _, _ = run_ccdv_cui2021(sch, units, city_geom, eps=0.05, assignment_mode=assign_mode)
        sec = time.perf_counter() - t0
        loads = [float(st[sid]["allocated_students"]) for sid in sch]
        row = evaluate(name, zones, loads, caps, pts, sch_xy, sec, total_pop, city_geom, city_area_km2)
        rows.append(row)

        out_geojson = OUT / f"{name}_zones.geojson"
        z_gdf = gpd.GeoDataFrame(
            {
                "facility_id": list(sch.keys()),
                "target_capacity": caps,
                "allocated_students": loads,
                "within_5pct": [st[sid]["within_5pct"] for sid in sch],
            },
            geometry=[zones[sid] for sid in sch],
            crs=CRS,
        )
        z_gdf.to_file(out_geojson, driver="GeoJSON")
        print(f"  -> Completed in {sec:.1f}s | Within ±5%: {row['within_5pct']} | Saved {out_geojson.name}")

    df_res = pd.DataFrame(rows)
    print("\n=== BENCHMARK RESULTS SUMMARY ===")
    print(df_res.to_string(index=False))
    df_res.to_csv(OUT / "demo_run_summary.csv", index=False)


if __name__ == "__main__":
    main()
