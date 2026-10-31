#!/usr/bin/env python3
"""Merge the Overpass TH/THCS/THPT school inventory into the Case 2 baseline.

Reads the existing Case 2 education facilities CSV (the 332-row HOT/OSM
points export — preserved verbatim, original ids kept) and the geolocated
school inventory (data/processed/hanoi_schools_inventory/
hanoi_schools_geolocated.csv, polygon centers from Overpass).

Dedup policy (deliberately conservative — many-to-one proximity matches
in the inventory's match_status are NEVER used to dedup on their own):
  1. already present (idempotent rerun): osm_<type>_<id> already in the CSV;
  2. exact OSM element id: node osm_id equal to a baseline facility_id
     (the HOT export is node points, so ids are directly comparable);
  3. same normalized Vietnamese name AND haversine distance <= 150 m to a
     baseline row (candidate match; requires BOTH name and proximity);
  4. otherwise the row is ADDED with a namespaced id ``osm_<type>_<id>``
     (numeric collisions with baseline node ids and, after the Case 1
     ``school_`` prefix, with health facility ids are impossible).

Out-of-GADM-4.1-boundary coordinates are FLAGGED in the merge log, never
silently dropped: the Overpass Hanoi boundary is the inclusion source and
its vintage differs from GADM (see scenario2_metadata.json limitations).

Outputs (all in data/processed/case2/):
  - scenario2_education_facilities.csv  (baseline rows first, then added)
  - scenario2_merge_log.csv             (one row per inventory record)
  - scenario2_metadata.json            (summary.education_facilities +
                                         merge provenance block appended)

Idempotent: reruns add nothing and rewrite identical CSV content.
Real school capacities are unavailable and stay blank; schools are
unverified vaccination-site CANDIDATES; polygon centers are not gates.
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from collect_hanoi_schools import (  # noqa: E402
    LAT_MAX, LAT_MIN, LON_MAX, LON_MIN, haversine_m, normalize_name, sha256_file,
)

REPO = Path(__file__).resolve().parents[1]
CASE2_DIR = REPO / "data" / "processed" / "case2"
INVENTORY_CSV = REPO / "data" / "processed" / "hanoi_schools_inventory" / "hanoi_schools_geolocated.csv"
BOUNDARY_GEOJSON = REPO / "data" / "processed" / "hanoi_boundaries.geojson"

CASE2_COLUMNS = [
    "facility_id", "facility_name", "facility_type",
    "latitude", "longitude", "capacity", "capacity_source", "source",
]
LOG_COLUMNS = [
    "osm_type", "osm_id", "school_name", "name_normalized", "decision",
    "duplicate_reason", "matched_case2_facility_id", "matched_distance_m",
    "new_facility_id", "flag", "latitude", "longitude",
]
MATCH_RADIUS_M = 150.0
ADDED_SOURCE = (
    "OpenStreetMap via Overpass (ODbL), polygon centers; merged from "
    "hanoi_schools_inventory/hanoi_schools_geolocated.csv "
    "(scripts/merge_school_inventory.py)"
)
BASELINE_ID_MARK = "osm_"


def _read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _boundary_covers(path: Path) -> object:
    """Union of the commune polygons as a single point-in-polygon tester."""
    import geopandas as gpd

    return gpd.read_file(path).geometry.union_all()


def merge(
    baseline_rows: list[dict],
    inventory_rows: list[dict],
    boundary_geom: object | None = None,
) -> tuple[list[dict], list[dict], dict]:
    """Return (merged rows, merge log rows, stats).

    ``baseline_rows`` are the current Case 2 CSV rows; rows whose id starts
    with ``osm_`` are previous merge additions (idempotent rerun) and are
    treated as neither baseline evidence nor re-addable.
    """
    baseline = [r for r in baseline_rows if not r["facility_id"].startswith(BASELINE_ID_MARK)]
    added_before = [r for r in baseline_rows if r["facility_id"].startswith(BASELINE_ID_MARK)]
    existing_ids = {r["facility_id"] for r in baseline_rows}

    def as_float(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    base_pts = [
        {
            "fid": r["facility_id"],
            "name": normalize_name(r["facility_name"] or ""),
            "lat": as_float(r["latitude"]),
            "lon": as_float(r["longitude"]),
        }
        for r in baseline
    ]

    merged = list(baseline_rows)  # preserve original rows + order verbatim
    log_rows: list[dict] = []
    stats = {
        "baseline_rows": len(baseline),
        "previously_added_rows": len(added_before),
        "inventory_rows": len(inventory_rows),
        "added": 0,
        "already_present": 0,
        "skipped_duplicate_exact_osm_id": 0,
        "skipped_duplicate_name_within_150m": 0,
        "rejected_invalid_coordinates": 0,
        "flagged_outside_gadm41_historical_boundary": 0,
    }

    for r in inventory_rows:
        lat, lon = as_float(r["latitude"]), as_float(r["longitude"])
        nn = r.get("name_normalized") or normalize_name(r.get("school_name", ""))
        new_fid = f"osm_{r['osm_type']}_{r['osm_id']}"
        entry = {
            "osm_type": r["osm_type"], "osm_id": r["osm_id"],
            "school_name": r.get("school_name", ""), "name_normalized": nn,
            "decision": "", "duplicate_reason": "",
            "matched_case2_facility_id": "", "matched_distance_m": "",
            "new_facility_id": new_fid, "flag": "", "latitude": r["latitude"],
            "longitude": r["longitude"],
        }
        reason = fid = dist = ""
        if lat is None or lon is None or not (
            LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX
        ):
            # Hard sanity bounds: reject loudly (never a silent drop).
            entry["decision"] = "rejected"
            entry["duplicate_reason"] = "invalid_or_out_of_bounds_coordinates"
            stats["rejected_invalid_coordinates"] += 1
            log_rows.append(entry)
            continue
        if new_fid in existing_ids:
            entry["decision"] = "skipped"
            entry["duplicate_reason"] = "already_merged"
            stats["already_present"] += 1
            log_rows.append(entry)
            continue
        if r["osm_type"] == "node" and r["osm_id"] in {b["fid"] for b in base_pts}:
            entry["decision"] = "skipped"
            entry["duplicate_reason"] = "exact_osm_node_id_in_case2_baseline"
            entry["matched_case2_facility_id"] = r["osm_id"]
            stats["skipped_duplicate_exact_osm_id"] += 1
            log_rows.append(entry)
            continue
        # Candidate match: same normalized name AND <=150 m. Proximity
        # alone is NEVER sufficient (see module docstring).
        best = None
        for b in base_pts:
            if not b["name"] or b["name"] != nn or b["lat"] is None:
                continue
            d = haversine_m(lat, lon, b["lat"], b["lon"])
            if d <= MATCH_RADIUS_M and (best is None or d < best[1]):
                best = (b["fid"], d)
        if best is not None:
            entry["decision"] = "skipped"
            entry["duplicate_reason"] = "same_normalized_name_within_150m"
            entry["matched_case2_facility_id"] = best[0]
            entry["matched_distance_m"] = f"{best[1]:.0f}"
            stats["skipped_duplicate_name_within_150m"] += 1
            log_rows.append(entry)
            continue

        flag = ""
        if boundary_geom is not None:
            from shapely.geometry import Point

            if not boundary_geom.covers(Point(lon, lat)):
                # Kept, but flagged: Overpass Hanoi boundary is the inclusion
                # source; GADM 4.1 vintage differs (never silently dropped).
                flag = "outside_gadm41_historical_boundary"
                stats["flagged_outside_gadm41_historical_boundary"] += 1
        entry["decision"] = "added"
        entry["flag"] = flag
        merged.append({
            "facility_id": new_fid,
            "facility_name": r.get("school_name", ""),
            "facility_type": "school",
            "latitude": r["latitude"], "longitude": r["longitude"],
            "capacity": "", "capacity_source": "missing",
            "source": ADDED_SOURCE,
        })
        existing_ids.add(new_fid)
        stats["added"] += 1
        log_rows.append(entry)

    return merged, log_rows, stats


def _write_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def main() -> int:
    case2_csv = CASE2_DIR / "scenario2_education_facilities.csv"
    log_csv = CASE2_DIR / "scenario2_merge_log.csv"
    meta_path = CASE2_DIR / "scenario2_metadata.json"

    baseline_rows = _read_csv(case2_csv)
    if not baseline_rows:
        raise SystemExit(f"empty baseline: {case2_csv}")
    inventory_rows = _read_csv(INVENTORY_CSV)
    if len(inventory_rows) != 1332:
        print(f"WARNING: inventory rows = {len(inventory_rows)} (expected 1332)")

    boundary_geom = _boundary_covers(BOUNDARY_GEOJSON)
    historical_baseline = [r for r in baseline_rows if not r["facility_id"].startswith(BASELINE_ID_MARK)]
    merged, log_rows, stats = merge(historical_baseline, inventory_rows, boundary_geom)

    ids = [r["facility_id"] for r in merged]
    if len(ids) != len(set(ids)):
        raise SystemExit("merged facility_id collision — aborting, nothing written")

    _write_csv(case2_csv, merged, CASE2_COLUMNS)
    _write_csv(log_csv, log_rows, LOG_COLUMNS)

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["summary"]["education_facilities"] = len(merged)
    meta.setdefault("merge", {}).update({
        "merged_at_utc": datetime.now(timezone.utc).isoformat(),
        "script": "scripts/merge_school_inventory.py",
        "merge_log": "scenario2_merge_log.csv",
        "baseline": {
            "rows_preserved_verbatim": stats["baseline_rows"],
            "source": (
                "HOT OSM education facilities export (points only) via HDX, "
                "ODbL 1.0 — the historical 332-row baseline; original numeric "
                "facility_ids unchanged"
            ),
        },
        "inventory_source": {
            "file": "data/processed/hanoi_schools_inventory/hanoi_schools_geolocated.csv",
            "sha256": sha256_file(INVENTORY_CSV),
            "rows": stats["inventory_rows"],
            "provider": "OpenStreetMap via Overpass",
            "license": "ODbL 1.0 (OpenStreetMap contributors)",
            "coordinate_note": "polygon centers, not surveyed gates",
        },
        "dedup_policy": (
            "exact OSM node id, else identical normalized Vietnamese name "
            "within 150 m of the SAME baseline row; nearest-location alone is "
            "never a duplicate reason (the inventory match_status many-to-one "
            "proximity matches are informational only); genuinely separate "
            "same-name branches farther than 150 m are preserved"
        ),
        **{k: v for k, v in stats.items() if k not in (
            "baseline_rows", "inventory_rows")},
    })
    for note in (
        "Merged rows carry namespaced ids osm_<type>_<id>; real OSM element "
        "type/id stay recoverable and cannot collide with baseline numeric ids.",
        "Added schools are unverified vaccination-site CANDIDATES; polygon "
        "centers are not gates; capacities remain missing.",
        "Rows flagged outside_gadm41_historical_boundary in the merge log are "
        "kept: the Overpass Hanoi boundary is the inclusion source and the "
        "GADM 4.1 vintage differs.",
    ):
        if note not in meta.setdefault("limitations", []):
            meta["limitations"].append(note)
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(json.dumps({
        "final_rows": len(merged),
        **stats,
        "total_duplicates_skipped": stats["skipped_duplicate_exact_osm_id"]
            + stats["skipped_duplicate_name_within_150m"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
