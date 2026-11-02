"""Small stdlib test for the Hanoi commune health stations inventory (pytest-compatible).

Run: python3 tests/test_health_stations.py   (or: pytest tests/test_health_stations.py)
Validates bounds, uniqueness, provenance sha256, class vocabulary, evidence-based
station classification (no synthetic stations), and that the geolocated subset is
consistent with the full inventory. Every row must carry an OSM id + source url;
station class requires name evidence; no geocoded/centroid coordinates allowed.
"""
import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
from collect_hanoi_health_stations import (  # noqa: E402
    ALLOWED_CLASSES, LAT_MAX, LAT_MIN, LON_MAX, LON_MIN, STATION_CLASS,
    TYT_RE, classify_facility, commune_in_name, normalize_name, sha256_file,
)

OUT = REPO / "data/processed/hanoi_health_stations"
RAW = REPO / "data/raw/hanoi_health_stations"


def _load(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def test_classifiers():
    assert classify_facility("Trạm Y tế xã Nghĩa Hương", "hospital", "") == STATION_CLASS
    assert classify_facility("Trạm y tế phường Kiến Hưng", "clinic", "clinic") == STATION_CLASS
    assert classify_facility("Trạm xá Gia Lâm", "", "") == STATION_CLASS  # historical name
    assert classify_facility("Trung tâm Y tế quận Cầu Giấy", "clinic", "") == "trung tâm y tế (quận/huyện)"
    assert classify_facility("Bệnh viện Việt Đức", "hospital", "hospital") == "bệnh viện"
    assert classify_facility("Phòng khám Đa khoa Hồng Ngọc", "clinic", "") == "phòng khám"
    assert classify_facility("Nhà thuốc ABC", "pharmacy", "") not in {STATION_CLASS}
    assert classify_facility("", "hospital", "") == "bệnh viện"  # tag evidence, not assumption
    assert commune_in_name("Trạm y tế xã Ba Vì") == "xã Ba Vì"
    assert commune_in_name("Trạm Y tế phường Vĩnh Tuy (cơ sở 2)") == "phường Vĩnh Tuy"
    assert commune_in_name("Phòng khám đa khoa Việt Pháp") == ""
    print("OK: classifier rules")


def test_inventory():
    assert (OUT / "hanoi_health_stations_inventory.csv").exists(), "run scripts/collect_hanoi_health_stations.py first"
    rows = _load(OUT / "hanoi_health_stations_inventory.csv")
    ids = [(r["osm_type"], r["osm_id"]) for r in rows]
    assert len(ids) == len(set(ids)), "duplicate (osm_type,osm_id)"
    n_station = 0
    for r in rows:
        lat, lon = float(r["latitude"]), float(r["longitude"])
        assert LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX, (r["osm_id"], lat, lon)
        assert r["facility_class"] in ALLOWED_CLASSES, r["facility_class"]
        assert r["match_status_case1"] in {
            "mới (không có trong case1)", "trùng điểm case1 (HOT OSM points)",
            "cùng tên case1, khác vị trí"}, r["match_status_case1"]
        assert r["source_url"].startswith("https://www.openstreetmap.org/")
        assert r["source_date"] and r["license"]
        assert r["coordinate_basis"] in {"osm_node", "osm_way_center", "osm_relation_center"}
        # station class MUST be name-evidenced (no synthetic stations per commune)
        if r["facility_class"] == STATION_CLASS:
            assert TYT_RE.search(r["facility_name"]) or "tram y te" in r["name_normalized"] \
                or "trạm xá" in r["name_normalized"], ("station without name evidence", r["osm_id"])
            assert r["facility_name"], "unnamed station"
            n_station += 1
        if r["commune_in_name"]:
            assert r["commune_in_name"] in r["facility_name"], ("commune token not from name", r["osm_id"])
    # expansion beyond the 19 named case1 points is the whole point of this collection
    assert n_station > 19, f"expected >19 named stations, got {n_station}"

    # geolocated subset: named TYT only, coords present, subset of full ids
    geo = _load(OUT / "hanoi_health_stations_geolocated.csv")
    full_ids = set(ids)
    for r in geo:
        assert r["facility_class"] == STATION_CLASS and r["facility_name"]
        assert (r["osm_type"], r["osm_id"]) in full_ids
        assert r["latitude"] and r["longitude"]
    assert len(geo) == n_station

    # provenance: recorded sha256 must still match the raw file on disk
    prov = json.loads((RAW / "provenance.json").read_text())
    for entry in prov["raw_files"]:
        p = RAW / entry["name"]
        assert p.exists() and sha256_file(p) == entry["sha256"], entry["name"]
        assert entry["elements"] >= len(rows)
    assert prov["osm_data_timestamp"]
    assert "ODbL" in prov["source"]

    findings = (OUT / "findings.md").read_text(encoding="utf-8")
    assert "ODbL" in findings and str(len(rows)) in findings and str(n_station) in findings
    assert "584" in findings  # historical GADM commune count stated
    assert "126" in findings  # post-reorg commune count stated
    print(f"OK: {len(rows)} inventory rows, {n_station} named trạm y tế, provenance verified")


if __name__ == "__main__":
    test_classifiers()
    test_inventory()
    print("ALL TESTS PASSED")
