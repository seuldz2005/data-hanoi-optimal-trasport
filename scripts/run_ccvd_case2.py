#!/usr/bin/env python3
"""Run CCVD on the current Case-2 school inventory, filtered to schools serving ages 5-14.

Filter rule (whitelist): keep only rows whose name says mầm non / mẫu giáo / nhà trẻ /
tiểu học / THCS / liên cấp; drop unnamed rows, centers, universities, colleges, vocational.
Writes the filtered list and a JSON metrics file per order mode.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

import geopandas as gpd
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from hanoi_ot.capacity import largest_remainder_split  # noqa: E402
from hanoi_ot.ccvd import run_ccvd_vector_gis  # noqa: E402

CASE2 = REPO / "data" / "processed" / "case2"
LEVEL = re.compile(r"mầm non|mẫu giáo|nhà trẻ|tiểu học|trung học cơ sở|\bthcs\b|liên cấp", re.I)
NOT_SCHOOL = re.compile(r"trung tâm|ngoại ngữ|tiếng anh|anh ngữ|đại học|cao đẳng|học viện|"
                        r"trung cấp|nghề|giáo dục thường xuyên|gdtx", re.I)


def filter_age_5_14(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only named kindergartens, primary and lower-secondary schools (whitelist by name)."""
    name = df["facility_name"].fillna("").map(lambda s: unicodedata.normalize("NFC", s))
    keep = ~df["facility_type"].isin(["university", "college"]) & name.str.contains(LEVEL) \
        & ~name.str.contains(NOT_SCHOOL)
    return df[keep].reset_index(drop=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--order", default="center_voronoi",
                    choices=["csv", "reverse", "center_school", "center_voronoi"])
    args = ap.parse_args()

    schools = pd.read_csv(CASE2 / "scenario2_education_facilities.csv", dtype={"facility_id": str})
    kept = filter_age_5_14(schools)
    kept.to_csv(CASE2 / "scenario2_schools_age5_14.csv", index=False)

    bnd = gpd.read_file(REPO / "data" / "processed" / "hanoi_boundaries.geojson").to_crs(32648)
    dens = pd.read_csv(CASE2 / "scenario2_commune_density.csv")
    assert list(dens.commune_id) == list(bnd.commune_id)
    density = (dens.children_5_14 / bnd.geometry.area.to_numpy()).tolist()
    total = int(dens.children_5_14.sum())

    g = gpd.GeoDataFrame(kept, geometry=gpd.points_from_xy(kept.longitude, kept.latitude),
                         crs=4326).to_crs(32648)
    caps = largest_remainder_split(total, len(g))
    sch = {r.facility_id: {"point": r.geometry, "capacity": caps[i]} for i, r in enumerate(g.itertuples())}

    t0 = time.perf_counter()
    zones, stats, remaining, unassigned = run_ccvd_vector_gis(
        sch, list(bnd.geometry), density, eps=0.05, delta_r=50.0, max_iter=100, order_by=args.order)
    sec = time.perf_counter() - t0

    st = pd.DataFrame.from_dict(stats, orient="index")
    st["allocated_students"] = st["allocated_students"].astype(float)
    over = (st.allocated_students - st.capacity).clip(lower=0)
    metrics = {
        "order": args.order, "schools_in_inventory": len(schools), "schools_age5_14": len(kept),
        "total_children": total, "capacity_per_school": [min(caps), max(caps)],
        "within_5pct": int((st.error_pct <= 5).sum()),
        "empty_zones": int((st.allocated_students == 0).sum()),
        "overloaded_gt_5pct": int((st.allocated_students > st.capacity * 1.05).sum()),
        "max_allocated": round(st.allocated_students.max()),
        "students_above_capacity": round(over.sum()),
        "allocated_sum": round(st.allocated_students.sum()),
        "unassigned": round(unassigned),
        "conservation_gap": round(st.allocated_students.sum() + unassigned - total),
        "unassigned_area_km2": round(remaining.area / 1e6, 2),
        "seconds": round(sec, 1),
    }
    out = CASE2 / f"ccvd_age5_14_{args.order}.json"
    out.write_text(json.dumps(metrics, indent=2, ensure_ascii=False))
    st.to_csv(CASE2 / f"ccvd_age5_14_{args.order}_stats.csv", index_label="facility_id")
    print(json.dumps(metrics, ensure_ascii=False))


if __name__ == "__main__":
    main()
