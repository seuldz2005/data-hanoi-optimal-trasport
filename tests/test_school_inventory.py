"""Small stdlib test for the Hanoi school inventory (also pytest-compatible).

Run: python3 tests/test_school_inventory.py   (or: pytest tests/test_school_inventory.py)
Validates bounds, uniqueness, provenance sha256, level vocabulary, and that the
geolocated subset is consistent with the full inventory. No synthetic schools:
every row must carry an OSM id and source url.
"""
import csv
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
from collect_hanoi_schools import (  # noqa: E402
    ALLOWED_LEVELS, LAT_MAX, LAT_MIN, LON_MAX, LON_MIN, sha256_file,
)

OUT = REPO / "data/processed/hanoi_schools_inventory"
RAW = REPO / "data/raw/hanoi_schools_inventory"
TH_LEVELS = {"tiểu học", "thcs", "thpt", "tiểu học + thcs", "thcs + thpt"}


def _load(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def test_inventory():
    assert (OUT / "hanoi_schools_inventory.csv").exists(), "run scripts/collect_hanoi_schools.py first"
    rows = _load(OUT / "hanoi_schools_inventory.csv")
    assert len(rows) > 332, f"expected expansion beyond 332, got {len(rows)}"
    ids = [(r["osm_type"], r["osm_id"]) for r in rows]
    assert len(ids) == len(set(ids)), "duplicate (osm_type,osm_id)"
    for r in rows:
        lat, lon = float(r["latitude"]), float(r["longitude"])
        assert LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX, (r["osm_id"], lat, lon)
        assert r["level"] in ALLOWED_LEVELS, r["level"]
        assert r["source_url"].startswith("https://www.openstreetmap.org/")
        assert r["source_date"] and r["license"]
        assert r["coordinate_basis"] in {"osm_node", "osm_way_center", "osm_relation_center"}
    assert sum(1 for r in rows if r["school_name"]) >= len(rows) * 0.8

    # geolocated subset: TH levels only, named, coords present, subset of full ids
    geo = _load(OUT / "hanoi_schools_geolocated.csv")
    full_ids = set(ids)
    for r in geo:
        assert r["level"] in TH_LEVELS and r["school_name"], (r["osm_id"], r["level"])
        assert (r["osm_type"], r["osm_id"]) in full_ids
        assert r["latitude"] and r["longitude"]

    # provenance: recorded sha256 must still match the raw file on disk
    prov = json.loads((RAW / "provenance.json").read_text())
    for entry in prov["raw_files"]:
        p = RAW / entry["name"]
        assert p.exists() and sha256_file(p) == entry["sha256"], entry["name"]
        assert entry["elements"] >= len(rows)
    assert prov["osm_data_timestamp"]

    findings = (OUT / "findings.md").read_text(encoding="utf-8")
    assert "ODbL" in findings and str(len(rows)) in findings
    print(f"OK: {len(rows)} inventory rows, {len(geo)} geolocated TH-level rows, provenance verified")


def test_classifier_rules():
    from collect_hanoi_schools import classify_level
    assert classify_level("Trường Tiểu học Nghĩa Hương", "school") == "tiểu học"
    assert classify_level("Trường Trung học cơ sở Lương Thế Vinh", "school") == "thcs"
    assert classify_level("THPT Trần Phú", "school") == "thpt"
    assert classify_level("Trường Mầm non Hoa Sen", "kindergarten") == "mầm non"
    assert classify_level("Trường TH & THCS Xuân Phương", "school") == "tiểu học + thcs"
    assert classify_level("Học viện Không Quân", "school") == "khác/chưa rõ"
    print("OK: classifier rules")


if __name__ == "__main__":
    test_classifier_rules()
    test_inventory()
    print("ALL TESTS PASSED")
