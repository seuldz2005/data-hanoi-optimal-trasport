#!/usr/bin/env python3
"""Collect public-source Hanoi school inventory (TH/Tiểu học/THCS/THPT + mầm non).

Primary usable public source found: OpenStreetMap via Overpass API (ODbL),
Hanoi admin relation 1903516, ALL geometry types (nodes AND polygons -> centers).
The prior case2 file (332 rows, HOT export via HDX) contained OSM POINTS ONLY,
omitting education polygons (~1300 school buildings in this collection).

Outputs (UTF-8 BOM CSV):
  data/raw/hanoi_schools_inventory/overpass_hanoi_schools_<ts>.json   raw API JSON
  data/raw/hanoi_schools_inventory/provenance.json                     urls, dates, sha256
  data/raw/hanoi_schools_inventory/dedup_log.csv                      dropped duplicates
  data/processed/hanoi_schools_inventory/hanoi_schools_inventory.csv all inventory
  data/processed/hanoi_schools_inventory/hanoi_schools_geolocated.csv TH-level geolocated candidate
  data/processed/hanoi_schools_inventory/findings.md                  Vietnamese findings

No geocoding guesses: lat/lon only from source geometry (node coord or way/relation
center as returned by Overpass `out center`). District/ward historical names from
GADM 4.1 commune polygons (ray casting, stdlib) + OSM addr:* tags when tagged.

Usage:
  python3 scripts/collect_hanoi_schools.py            # fetch + build + export
  python3 scripts/collect_hanoi_schools.py --offline # rebuild from saved raw JSON
  python3 scripts/collect_hanoi_schools.py --self-check
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import re
import sys
import time
import unicodedata
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REPO = Path(__file__).resolve().parents[1]
RAW_DIR = REPO / "data/raw/hanoi_schools_inventory"
OUT_DIR = REPO / "data/processed/hanoi_schools_inventory"
CASE2 = REPO / "data/processed/case2/scenario2_education_facilities.csv"
GADM = REPO / "data/processed/hanoi_boundaries.geojson"

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_QUERY = (
    '[out:json][timeout:200];'
    'area(3601903516)->.h;'  # relation 1903516 "Thành phố Hà Nội" (admin_level=4)
    '('
    'node(area.h)["amenity"="school"];'
    'way(area.h)["amenity"="school"];'
    'relation(area.h)["amenity"="school"];'
    'node(area.h)["amenity"="kindergarten"];'
    'way(area.h)["amenity"="kindergarten"];'
    'relation(area.h)["amenity"="kindergarten"];'
    ');'
    'out center tags;'
)
SOURCE_URL_BULK = OVERPASS_URL
SOURCE_URL_ELEMENT = "https://www.openstreetmap.org/{type}/{id}"
LICENSE = "ODbL 1.0 (OpenStreetMap contributors)"
UA = "hanoi-ot-collector/0.1 (university group project; contact via repo)"

# Hanoi rough bounds (city extent) for validation
LAT_MIN, LAT_MAX = 20.40, 21.50
LON_MIN, LON_MAX = 105.30, 106.10

ALLOWED_LEVELS = {
    "tiểu học", "thcs", "thpt", "tiểu học + thcs", "thcs + thpt",
    "mầm non", "pt dân tộc nội trú", "gdtx/gdtn", "khác/chưa rõ",
}

INVENTORY_COLUMNS = [
    "school_name", "level", "amenity", "address", "ward_osm", "district_osm",
    "ward_gadm41", "district_gadm41", "latitude", "longitude",
    "coordinate_basis", "match_status", "matched_case2_distance_m",
    "source_url", "source_date", "license", "osm_type", "osm_id",
    "name_normalized", "possible_duplicate_of",
]


# ---------------------------------------------------------------- helpers

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_overpass(out_path: Path) -> dict:
    body = urlencode({"data": OVERPASS_QUERY}).encode()
    last_err = None
    for attempt in range(3):
        try:
            req = Request(OVERPASS_URL, data=body, headers={"User-Agent": UA})
            with urlopen(req, timeout=240) as r:
                payload = r.read()
            out_path.write_bytes(payload)
            return json.loads(payload)
        except Exception as e:  # noqa: BLE001 - retry any transport error
            last_err = e
            time.sleep(3 * (attempt + 1))
    raise SystemExit(f"Overpass fetch failed after 3 attempts: {last_err}")


def normalize_name(name: str) -> str:
    """Gentle normalization: unify unicode form, lowercase, collapse spaces/punct."""
    name = unicodedata.normalize("NFC", name).lower().strip()
    name = re.sub(r"[^\w\sàáảãạăắẳẵặâấẩẫậèéẻẽẹêếểễệìíỉĩịòóỏõọôốổỗộơớởỡợùúủũụưứửữựỳýỷỹỵđ]", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def classify_level(name: str, amenity: str) -> str:
    """Education level from Vietnamese school name conventions (name evidence)."""
    n = normalize_name(name)
    if amenity == "kindergarten":
        return "mầm non"
    th = ("tiểu học" in n) or bool(re.search(r"\bth(?!cs|pt)\b", n)) or "tieu hoc" in n
    thcs = ("thcs" in n) or ("trung học cơ sở" in n) or ("trung hoc co so" in n)
    thpt = ("thpt" in n) or ("trung học phổ thông" in n) or ("trung hoc pho thong" in n)
    if th and thcs:
        return "tiểu học + thcs"
    if thcs and thpt:
        return "thcs + thpt"
    if th:
        return "tiểu học"
    if thcs:
        return "thcs"
    if thpt:
        return "thpt"
    if "dân tộc nội trú" in n or "ptdt" in n:
        return "pt dân tộc nội trú"
    if "giáo dục thường xuyên" in n or "gdtx" in n or "gDTN".lower() in n:
        return "gdtx/gdtn"
    if not n:
        return "khác/chưa rõ"
    return "khác/chưa rõ"


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# ------------------------------------------------ GADM 4.1 point-in-polygon

def load_gadm():
    gj = json.loads(GADM.read_text())
    feats = []
    for f in gj["features"]:
        p = f["properties"]
        polys = []
        if f["geometry"]["type"] == "Polygon":
            polys = [f["geometry"]["coordinates"]]
        elif f["geometry"]["type"] == "MultiPolygon":
            polys = f["geometry"]["coordinates"]
        bboxes = []
        rings = []
        for poly in polys:
            ring = poly[0]  # outer ring only (communes are simple)
            if len(ring) < 3:
                continue
            lons = [pt[0] for pt in ring]
            lats = [pt[1] for pt in ring]
            bboxes.append((min(lons), min(lats), max(lons), max(lats)))
            rings.append(ring)
        if rings:
            feats.append((p.get("NAME_2", ""), p.get("NAME_3", ""), rings, bboxes))
    return feats


def point_in_ring(lon, lat, ring) -> bool:
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi + 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def lookup_ward(gadm_feats, lon, lat):
    for name2, name3, rings, bboxes in gadm_feats:
        hit = False
        for ring, bb in zip(rings, bboxes):
            if not (bb[0] <= lon <= bb[2] and bb[1] <= lat <= bb[3]):
                continue
            if point_in_ring(lon, lat, ring):
                hit = True
                break
        if hit:
            return name2, name3
    return "", ""


# --------------------------------------------------------- existing case2

def load_case2_points():
    """Existing 332 HOT points (read-only comparison baseline)."""
    pts = []
    with open(CASE2, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            try:
                pts.append((normalize_name(row["facility_name"] or ""),
                            float(row["latitude"]), float(row["longitude"]),
                            row["facility_type"]))
            except (ValueError, KeyError):
                continue
    return pts


# ------------------------------------------------------------------ build

def build_records(ov: dict, case2_pts, gadm_feats, source_date: str):
    recs, dedup_dropped = [], []
    seen: dict[tuple, dict] = {}
    for el in ov["elements"]:
        tags = el.get("tags") or {}
        name = (tags.get("name") or tags.get("name:vi") or "").strip()
        amenity = tags.get("amenity", "")
        t = el["type"]
        if t == "node":
            lat, lon = el.get("lat"), el.get("lon")
            basis = "osm_node"
        else:
            c = el.get("center") or {}
            lat, lon = c.get("lat"), c.get("lon")
            basis = "osm_way_center" if t == "way" else "osm_relation_center"
        if lat is None or lon is None:
            continue
        nn = normalize_name(name)
        # gentle location dedup: same normalized name AND <150 m => same campus,
        # prefer polygon over node. Never merges distinct-name or far-apart rows.
        dup_of = ""
        keep_key = None
        if nn:
            for k, v in seen.items():
                if k[0] == nn and haversine_m(lat, lon, v["latitude"], v["longitude"]) < 150:
                    keep_key = k
                    dup_of = f"{k[1]}/{k[2]}"
                    break
        key = (nn, el["type"], str(el["id"]))
        prio = {"relation": 3, "way": 2, "node": 1}
        if keep_key is not None:
            kept = seen[keep_key]
            if name and prio.get(el["type"], 0) > prio.get(kept["osm_type"], 0):
                # incoming element richer (polygon) -> swap keep, drop old node
                dedup_dropped.append((kept["osm_type"], kept["osm_id"], kept["school_name"],
                                      f"{el['type']}/{el['id']}", kept["latitude"], kept["longitude"]))
                del seen[keep_key]
            else:
                dedup_dropped.append((el["type"], el["id"], name,
                                      dup_of, lat, lon))
                continue
        addr = " ".join(x for x in [
            tags.get("addr:housenumber", ""),
            tags.get("addr:street", "")] if x)
        district2, ward3 = "", ""
        if not (20.0 < lat < 22.0 and 105.0 < lon < 107.0):
            continue  # defensive: skip out-of-Vietnam junk
        district2, ward3 = lookup_ward(gadm_feats, lon, lat)
        match_status, match_dist = "mới (không có trong case2)", ""
        if name:
            best = None  # (dist_or_None, case2_name, is_real_match)
            for cnn, clat, clon, ctype in case2_pts:
                if not cnn:
                    continue
                d = haversine_m(lat, lon, clat, clon)
                if d < 300 and (best is None or (best[0] is not None and d < best[0])):
                    best = (d, cnn, True)
                elif d >= 300 and cnn == nn and best is None:
                    best = (None, cnn, False)
            if best and best[2]:
                match_status = "trùng điểm case2 (HOT OSM points)"
                match_dist = f"{best[0]:.0f}"
            elif best and best[1] == nn:
                match_status = "cùng tên case2 nhưng khác vị trí"
        seen[key] = {
            "school_name": name, "level": classify_level(name, amenity),
            "amenity": amenity, "address": addr,
            "ward_osm": tags.get("addr:ward", ""), "district_osm": tags.get("addr:district", ""),
            "ward_gadm41": ward3, "district_gadm41": district2,
            "latitude": lat, "longitude": lon, "coordinate_basis": basis,
            "match_status": match_status, "matched_case2_distance_m": match_dist,
            "source_url": SOURCE_URL_ELEMENT.format(type=el["type"], id=el["id"]),
            "source_date": source_date, "license": LICENSE,
            "osm_type": el["type"], "osm_id": str(el["id"]),
            "name_normalized": nn, "possible_duplicate_of": dup_of,
        }
    return list(seen.values()), dedup_dropped


def load_raw_latest() -> tuple[Path, dict]:
    files = sorted(RAW_DIR.glob("overpass_hanoi_schools_*.json"))
    if not files:
        raise SystemExit("no raw Overpass JSON in data/raw/hanoi_schools_inventory; run online mode")
    return files[-1], json.loads(files[-1].read_text())


def write_csv(path: Path, rows: list[dict], columns: list[str]):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def self_check() -> list[str]:
    """Validate bounds, uniqueness, provenance sha256, level values."""
    errs = []
    inv = OUT_DIR / "hanoi_schools_inventory.csv"
    prov_p = RAW_DIR / "provenance.json"
    if not inv.exists():
        return ["missing " + str(inv)]
    with open(inv, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    ids = [(r["osm_type"], r["osm_id"]) for r in rows]
    if len(ids) != len(set(ids)):
        errs.append("duplicate (osm_type,osm_id)")
    n_named = 0
    for r in rows:
        lat, lon = float(r["latitude"]), float(r["longitude"])
        if not (LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX):
            errs.append(f"out of Hanoi bounds: {r['osm_id']} {lat},{lon}")
        if r["level"] not in ALLOWED_LEVELS:
            errs.append(f"bad level: {r['level']!r}")
        if not r["source_url"].startswith("https://www.openstreetmap.org/"):
            errs.append("bad source_url")
        if not r["source_date"]:
            errs.append("missing source_date")
        if r["coordinate_basis"] not in {
            "osm_node", "osm_way_center", "osm_relation_center",
        }:
            errs.append("bad coordinate_basis (no geocoding allowed)")
        if r["school_name"]:
            n_named += 1
    if len(rows) <= 332:
        errs.append(f"inventory ({len(rows)}) not larger than existing 332")
    if n_named < len(rows) * 0.8:
        errs.append(f"too many unnamed rows: {len(rows)-n_named}")
    if prov_p.exists():
        prov = json.loads(prov_p.read_text())
        for f in prov.get("raw_files", []):
            p = RAW_DIR / f["name"]
            if not p.exists() or sha256_file(p) != f["sha256"]:
                errs.append(f"provenance sha mismatch: {f['name']}")
    else:
        errs.append("missing provenance.json")
    if errs:
        print("SELF-CHECK FAILED:")
        for e in errs[:20]:
            print(" -", e)
        raise SystemExit(1)
    msg = f"SELF-CHECK OK: {len(rows)} unique schools, {n_named} named, bounds+provenance+levels valid"
    print(msg)
    return [msg]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--offline", action="store_true", help="rebuild from saved raw JSON")
    ap.add_argument("--self-check", action="store_true", help="validate exports only")
    args = ap.parse_args()

    if args.self_check:
        self_check()
        return

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.offline:
        raw_path, ov = load_raw_latest()
    else:
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        raw_path = RAW_DIR / f"overpass_hanoi_schools_{stamp}.json"
        print(f"fetching Overpass (Hanoi relation 1903516, school+kindergarten, all geometries)...", file=sys.stderr)
        ov = fetch_overpass(raw_path)

    source_date = dt.date.today().isoformat()
    osm_base = ov.get("osm3s", {}).get("timestamp_osm_base", "")
    n_raw = len(ov["elements"])

    prov = {
        "source": "OpenStreetMap via Overpass API (ODbL 1.0)",
        "api_endpoint": SOURCE_URL_BULK,
        "query": OVERPASS_QUERY,
        "retrieved_utc": source_date,
        "osm_data_timestamp": osm_base,
        "generator": ov.get("generator", ""),
        "raw_files": [{"name": raw_path.name, "sha256": sha256_file(raw_path),
                       "bytes": raw_path.stat().st_size, "elements": n_raw}],
        "case2_baseline": {
            "file": "data/processed/case2/scenario2_education_facilities.csv",
            "rows": 332, "note": "HOT OSM export points only (no polygons), via HDX",
        },
        "gadm": {"file": "data/processed/hanoi_boundaries.geojson", "vintage": "GADM 4.1 (historical district/commune names)"},
        "hanoi_edu_gov": "https://hanoi.edu.vn/ probed 2026-11-01: news portal, no machine-readable school directory found (not used as data source)",
    }
    (RAW_DIR / "provenance.json").write_text(json.dumps(prov, ensure_ascii=False, indent=2))

    case2_pts = load_case2_points()
    gadm_feats = load_gadm()
    print(f"gadm: {len(gadm_feats)} communes | case2 baseline: {len(case2_pts)} points", file=sys.stderr)

    t0 = time.time()
    recs, dropped = build_records(ov, case2_pts, gadm_feats, source_date)
    print(f"built {len(recs)} records, dropped {len(dropped)} near-duplicates "
          f"in {time.time()-t0:.1f}s", file=sys.stderr)

    write_csv(OUT_DIR / "hanoi_schools_inventory.csv", recs, INVENTORY_COLUMNS)

    if dropped:
        with open(RAW_DIR / "dedup_log.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["dropped_osm_type", "dropped_osm_id", "dropped_name",
                        "kept_osm", "lat", "lon"])
            w.writerows(dropped)

    # geolocated candidate subset: TH-focus levels with coordinates (all coords here are
    # source-derived, none geocoded), excluding mầm non / unclear "khác"
    th_levels = {"tiểu học", "thcs", "thpt", "tiểu học + thcs", "thcs + thpt"}
    geo = [r for r in recs if r["level"] in th_levels and r["school_name"]]
    write_csv(OUT_DIR / "hanoi_schools_geolocated.csv", geo, INVENTORY_COLUMNS)

    # counts for findings
    from collections import Counter
    lvl = Counter(r["level"] for r in recs)
    d_up = Counter(r["district_gadm41"] or "(ngoài ranh GADM)" for r in recs)
    ms = Counter(r["match_status"].split(" (")[0] for r in recs)
    case2 = Counter()
    with open(CASE2, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            case2[row["facility_type"]] += 1

    lines = []
    A = lines.append
    A("# Kết quả thu thập dữ liệu trường học Hà Nội (2026-11-01)\n")
    A("## Nguồn và phạm vi\n")
    A("- **Nguồn dữ liệu**: OpenStreetMap qua Overpass API, quan hệ hành chính")
    A("  *Thành phố Hà Nội* (relation 1903516, admin_level=4), giấy phép ODbL 1.0.")
    A("- **Truy vấn**: `amenity=school` + `amenity=kindergarten`, **đủ 3 loại hình học**")
    A("  (node, way, relation) — điểm way/relation lấy tâm polygon (`out center`).")
    A("- **URL gốc + sha256 + ngày truy xuất**: xem `data/raw/hanoi_schools_inventory/provenance.json`.")
    A(f"- Dữ liệu gốc OSM chốt thời điểm: `{osm_base}`; truy xuất ngày {source_date}.")
    A("- Cổng Sở GD&ĐT Hà Nội (hanoi.edu.vn) đã thăm dò: là trang tin tức, **không có**")
    A("  danh mục trường máy đọc được công khai → không dùng làm nguồn dữ liệu (ghi rõ hạn chế này).\n")
    A("## Kết quả chính\n")
    A(f"- **Tổng bản ghi sau khử trùng lặp cục bộ: {len(recs)}** (thô {n_raw} phần tử OSM).")
    A(f"- Trong đó có tên trường: {sum(1 for r in recs if r['school_name'])} bản ghi.")
    A(f"- Tập \"geolocated candidate\" (có tên + cấp học TH/tiểu học/THCS/THPT + tọa độ nguồn):")
    A(f"  **{len(geo)} bản ghi** → `data/processed/hanoi_schools_inventory/hanoi_schools_geolocated.csv`.\n")
    A("### Phân theo cấp học (phân loại theo tên trường, kèm bằng chứng tag amenity)\n")
    for k in sorted(lvl, key=lambda x: -lvl[x]):
        A(f"- `{k}`: **{lvl[k]}**")
    A("\n### Phân theo quận/huyện (tên lịch sử GADM 4.1, tọa độ lấy tâm ranh)\n")
    for k in sorted(d_up, key=lambda x: -d_up[x]):
        A(f"- {k}: {d_up[k]}")
    A("\n### So khớp với bộ 332 điểm case2 cũ (HOT export chỉ POINT)\n")
    for k in sorted(ms, key=lambda x: -ms[x]):
        A(f"- {k}: {ms[k]}")
    A("\n- Bộ case2 cũ gồm: " + ", ".join(f"{v} {k}" for k, v in sorted(case2.items(), key=lambda x: -x[1]))
      + " — tức **không phải toàn bộ trường Hà Nội**, đã bỏ sót ~1300 polygon trường học OSM.")
    A("- So với các con số do nhóm cung cấp (124 THPT, 298 tiểu học, 226 THCS — chưa kiểm chứng):")
    A(f"  bộ sưu tầm này có {lvl.get('thpt',0)} THPT, {lvl.get('tiểu học',0)+lvl.get('tiểu học + thcs',0)} tiểu học (cộng liên cấp TH+THCS), "
      f"{lvl.get('thcs',0)+lvl.get('thcs + thpt',0)+lvl.get('tiểu học + thcs',0)} THCS(cộng liên cấp); chưa đối chiếu bắt buộc vì phạm vi nguồn khác nhau.\n")
    A("## Giới hạn / tính trung thực\n")
    A("- Tọa độ way/relation là **tâm polygon từ nguồn**, không phải điểm do port đo độc lập;")
    A("  cột `coordinate_basis` phân biệt rõ (osm_node / osm_way_center / osm_relation_center).")
    A("- **Không geocode suy đoán**: mọi tọa độ đều từ nguồn; bản ghi không tên vẫn giữ lại")
    A("  để khỏi mất dữ liệu nhưng bị loại khỏi tập geolocated candidate.")
    A("- Phân cấp học suy ra từ **quy ước đặt tên tiếng Việt** trong tên OSM (có thể sai ở tên thiếu chuẩn).")
    A("- Quận/phường dùng **GADM 4.1 (tên lịch sử)**; ranh có thể lệch với hiện trạng sau sáp nhập.")
    A("- Khử trùng chỉ gộp **cùng tên chuẩn hóa + cách <150 m**; các chi nhánh/trùng tên khác vị trí **được giữ nguyên**.")
    A(f"- {len(dropped)} phần tử bị đánh dấu trùng lặp gần, xem `data/raw/hanoi_schools_inventory/dedup_log.csv`.")
    A("- Chưa tích hợp vào Case1 (bản đồ/model): cần audit người trước khi dùng.\n")
    A("## Lệnh tái lập\n")
    A("```bash")
    A("python3 scripts/collect_hanoi_schools.py             # tải mới + xuất CSV")
    A("python3 scripts/collect_hanoi_schools.py --offline   # dựng lại từ JSON đã lưu")
    A("python3 scripts/collect_hanoi_schools.py --self-check")
    A("python3 tests/test_school_inventory.py               # test nhỏ (stdlib)")
    A("```")
    (OUT_DIR / "findings.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"\nwrote {OUT_DIR/'hanoi_schools_inventory.csv'} ({len(recs)} rows)")
    print(f"wrote {OUT_DIR/'hanoi_schools_geolocated.csv'} ({len(geo)} rows)")
    print(f"wrote {OUT_DIR/'findings.md'}")
    print(f"wrote {RAW_DIR/'provenance.json'}")
    self_check()


if __name__ == "__main__":
    main()
