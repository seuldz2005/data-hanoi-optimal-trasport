#!/usr/bin/env python3
"""Collect public-source Hanoi commune health stations (trạm y tế xã/phường).

Primary usable public source: OpenStreetMap via Overpass API (ODbL 1.0),
Hanoi admin relation 1903516, ALL geometry types (nodes AND polygons -> centers).
Case1 facilities.csv contains 320 health_facility rows (HOT export, OSM POINTS
ONLY) of which just 19 are named "trạm y tế" — this collection adds polygons and
amenity/healthcare/name evidence to recover the real station network.

Overpass query unions three evidence clauses (each x node/way/relation):
  1) amenity in {clinic, doctors, hospital}
  2) any "healthcare" tag (healthcare=centre/clinic/station/...)
  3) name ~ "tr[ạa]m y t" case-insensitive (catches TYT with no amenity tag)
Union is deduplicated by Overpass itself (each element returned once).

Official directories probed (online mode only, evidence saved, NOT data sources):
  - soyte.hanoi.gov.vn search "danh sách trạm y tế" -> news articles only,
    no machine-readable station directory (HTML saved as evidence)
  - hanoicdc.gov.vn -> blocked/timeout from collection environment (recorded)

Outputs (UTF-8 BOM CSV):
  data/raw/hanoi_health_stations/overpass_hanoi_health_<ts>.json  raw API JSON
  data/raw/hanoi_health_stations/provenance.json                  urls, dates, sha256, probes
  data/raw/hanoi_health_stations/dedup_log.csv                   dropped near-duplicates
  data/raw/hanoi_health_stations/probe_*.html                    official-site probe evidence
  data/processed/hanoi_health_stations/hanoi_health_stations_inventory.csv
  data/processed/hanoi_health_stations/hanoi_health_stations_geolocated.csv  TYT named subset
  data/processed/hanoi_health_stations/findings.md               Vietnamese findings

No geocoding guesses: lat/lon only from source geometry (node coord or
way/relation center as returned by Overpass `out center`). Commune names come
from GADM 4.1 polygons (ray casting, stdlib) + OSM addr:* tags + name text
(e.g. "Trạm y tế xã Ba Vì"); GADM 4.1 is the HISTORICAL pre-2025 584-commune
structure — post-2025-07-01 Hanoi has 126 new phường/xã (see findings.md);
no mapping between old and new communes is fabricated here.

Usage:
  python3 scripts/collect_hanoi_health_stations.py            # fetch + build + export
  python3 scripts/collect_hanoi_health_stations.py --offline  # rebuild from saved raw JSON
  python3 scripts/collect_hanoi_health_stations.py --self-check
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import re
import subprocess
import sys
import time
import unicodedata
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REPO = Path(__file__).resolve().parents[1]
RAW_DIR = REPO / "data/raw/hanoi_health_stations"
OUT_DIR = REPO / "data/processed/hanoi_health_stations"
CASE1 = REPO / "data/processed/case1/facilities.csv"
GADM = REPO / "data/processed/hanoi_boundaries.geojson"

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
OVERPASS_QUERY = (
    '[out:json][timeout:200];'
    'area(3601903516)->.h;'  # relation 1903516 "Thành phố Hà Nội" (admin_level=4)
    '('
    'node(area.h)["amenity"~"^(clinic|doctors|hospital)$"];'
    'way(area.h)["amenity"~"^(clinic|doctors|hospital)$"];'
    'relation(area.h)["amenity"~"^(clinic|doctors|hospital)$"];'
    'node(area.h)["healthcare"];'
    'way(area.h)["healthcare"];'
    'relation(area.h)["healthcare"];'
    'node(area.h)["name"~"tr[ạa]m y t",i];'
    'way(area.h)["name"~"tr[ạa]m y t",i];'
    'relation(area.h)["name"~"tr[ạa]m y t",i];'
    ');'
    'out center tags;'
)
SOURCE_URL_BULK = OVERPASS_ENDPOINTS[0]
SOURCE_URL_ELEMENT = "https://www.openstreetmap.org/{type}/{id}"
LICENSE = "ODbL 1.0 (OpenStreetMap contributors)"
UA = "hanoi-ot-collector/0.1 (university group project; contact via repo)"

# Hanoi rough city bounds (defensive validation only; Overpass area filter is authoritative)
LAT_MIN, LAT_MAX = 20.40, 21.50
LON_MIN, LON_MAX = 105.20, 106.25

# facility classes derived from name/tags evidence (never from assumptions)
ALLOWED_CLASSES = {
    "trạm y tế (xã/phường)",   # name says Trạm y tế / Trạm xá (commune-level station)
    "trung tâm y tế (quận/huyện)",  # TTYT district level
    "bệnh viện",
    "phòng khám",
    "cơ sở y tế khác",
}
STATION_CLASS = "trạm y tế (xã/phường)"
# trạm y tế / Trạm Y Tế / Trạm xá — full Vietnamese e-family (tế U+1EBF etc.), plus ASCII "tram y te" and "TYT" token
TYT_RE = re.compile(r"tr[ạa]m\s+y\s+t[eéèẻẽẹêếềểễệ]|tr[ạa]m\s+x[áa]|\btyt\b", re.IGNORECASE)
TRAM_XA_RE = re.compile(r"tr[ạa]m\s+x[áa]", re.IGNORECASE)     # historical commune station name
COMMUNE_RE = re.compile(r"(phường|xã|thị trấn|TT\.?)\s+([^\s,(]+(?:\s[^\s,(]+)*)", re.IGNORECASE)

INVENTORY_COLUMNS = [
    "facility_name", "facility_class", "amenity", "healthcare", "address",
    "ward_osm", "district_osm", "ward_gadm41", "district_gadm41",
    "commune_in_name", "latitude", "longitude", "coordinate_basis",
    "match_status_case1", "matched_case1_distance_m",
    "source_url", "source_date", "license",
    "osm_type", "osm_id", "name_normalized", "possible_duplicate_of",
]


# ---------------------------------------------------------------- helpers

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize_name(name: str) -> str:
    name = unicodedata.normalize("NFC", name).lower().strip()
    name = re.sub(r"[^\w\sàáảãạăắẳẵặâấẩẫậèéẻẽẹêếểễệìíỉĩịòóỏõọôốổỗộơớởỡợùúủũụưứửữựỳýỷỹỵđ]", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def classify_facility(name: str, amenity: str, healthcare: str) -> str:
    """Facility class from Vietnamese name conventions + OSM tags (name evidence first)."""
    n = normalize_name(name)
    if TYT_RE.search(name) or TRAM_XA_RE.search(name) or "tram y te" in n:
        return STATION_CLASS
    if "trung tâm y tế" in n or "ttyt" in n:
        return "trung tâm y tế (quận/huyện)"
    if ("bệnh viện" in n or "benh vien" in n
            or amenity == "hospital" or healthcare == "hospital"):
        return "bệnh viện"
    if ("phòng khám" in n or "phong kham" in n
            or amenity in {"clinic", "doctors"} or healthcare in {"clinic", "centre"}):
        return "phòng khám"
    return "cơ sở y tế khác"


def commune_in_name(name: str) -> str:
    """Extract the commune token from a facility name, e.g. 'Trạm Y tế xã Ba Vì' -> 'xã Ba Vì'.
    Name-text evidence only — this is NOT geocoding and NOT a commune claim."""
    m = COMMUNE_RE.search(name or "")
    if not m:
        return ""
    token = re.sub(r"\s+", " ", m.group(0)).strip().rstrip(",")
    # avoid matching e.g. 'xã' followed by district words is fine; keep raw token
    return token


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


# --------------------------------------------------------------- fetching

def _overpass_via_curl(endpoint: str, query: str, out_path: Path) -> bytes:
    """Fallback transport when urllib TLS fails (e.g. stock macOS python3.9)."""
    res = subprocess.run(
        ["curl", "-sS", "-m", "240", "-A", UA, endpoint,
         "--data-urlencode", f"data={query}"],
        capture_output=True, timeout=260)
    if res.returncode != 0 or not res.stdout:
        raise RuntimeError(f"curl exit {res.returncode}: {res.stderr[:200]!r}")
    out_path.write_bytes(res.stdout)
    return res.stdout


def fetch_overpass(out_path: Path) -> dict:
    body = urlencode({"data": OVERPASS_QUERY}).encode()
    last_err = None
    for endpoint in OVERPASS_ENDPOINTS * 2:  # 2 rounds of both endpoints
        try:
            req = Request(endpoint, data=body, headers={"User-Agent": UA})
            with urlopen(req, timeout=240) as r:
                payload = r.read()
            out_path.write_bytes(payload)
            return json.loads(payload)
        except Exception as e:  # noqa: BLE001 - retry any transport error
            last_err = f"{endpoint} urllib: {e}"
            print(f"  {last_err}", file=sys.stderr)
            try:
                return json.loads(_overpass_via_curl(endpoint, OVERPASS_QUERY, out_path))
            except Exception as e2:  # noqa: BLE001
                last_err = f"{endpoint} curl: {e2}"
                print(f"  {last_err}", file=sys.stderr)
            time.sleep(5)
    raise SystemExit(f"Overpass fetch failed on all endpoints: {last_err}")


# ---------------------------------------------------------- official probes
# Probes document that no machine-readable official station directory was
# found; they are NOT data sources. Evidence HTML saved under data/raw/.

PROBES = [
    dict(slug="probe_soyte_search_danhsach_tramyte",
         url="https://soyte.hanoi.gov.vn/?q=danh+s%C3%A1ch+tr%E1%BA%A1m+y+t%E1%BA%BF",
         title="Sở Y tế Hà Nội - tìm kiếm 'danh sách trạm y tế'",
         note="cổng Sở Y tế: kết quả là bài tin tức, không có danh mục trạm y tế máy đọc được"),
    dict(slug="probe_soyte_search_tramyte",
         url="https://soyte.hanoi.gov.vn/?q=tr%E1%BA%A1m+y+t%E1%BA%BF",
         title="Sở Y tế Hà Nội - tìm kiếm 'trạm y tế'",
         note="cổng Sở Y tế: chỉ tin tức hoạt động TYT (vd TYT phường Kiến Hưng), không danh mục"),
    dict(slug="probe_hanoicdc_root",
         url="https://hanoicdc.gov.vn/",
         title="CDC Hà Nội - trang chủ",
         note="thăm dò khả năng tiếp cận (kỳ vọng không có danh mục trạm phường/xã)"),
]


def run_probes(retrieval_utc: str) -> list[dict]:
    import urllib.error
    results = []
    for p in PROBES:
        entry = dict(p)
        try:
            req = Request(p["url"], headers={"User-Agent": "Mozilla/5.0 (KHTML, like Gecko)"})
            with urlopen(req, timeout=30) as r:
                payload = r.read()
            (RAW_DIR / f"{p['slug']}.html").write_bytes(payload)
            entry["http_status"] = r.status
            entry["bytes"] = len(payload)
            entry["sha256"] = hashlib.sha256(payload).hexdigest()
            # rough content check: does the search page list directory-like results?
            txt = payload.decode("utf-8", errors="ignore")
            entry["result_titles"] = re.findall(
                r"<a[^>]*title=\"([^\"]{10,140})\"", txt)[:10]
            entry["looks_like_directory"] = bool(
                re.search(r"danh\s*s[áa]ch\s*c[ơo]\s*s[ỷy]", txt, re.I)
                and "trạm y tế" in txt.lower() and "csv" in txt.lower())
        except Exception as e:  # noqa: BLE001 - probes must never kill the run
            entry["http_status"] = f"error: {e}"[:200]
            entry["bytes"] = 0
        entry["retrieved_utc"] = retrieval_utc
        results.append(entry)
        print(f"probe {p['slug']}: {entry['http_status']}", file=sys.stderr)
    return results


# --------------------------------------------------------- existing case1

def load_case1_health_points():
    """Case1 health_facility rows (HOT OSM points, read-only baseline)."""
    pts = []
    with open(CASE1, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row.get("site_class") != "health_facility":
                continue
            try:
                pts.append((normalize_name(row["facility_name"] or ""),
                            float(row["latitude"]), float(row["longitude"])))
            except (ValueError, KeyError):
                continue
    return pts


# ------------------------------------------------------------------ build

def build_records(ov: dict, case1_pts, gadm_feats, source_date: str):
    recs, dedup_dropped = [], []
    seen: dict[tuple, dict] = {}
    for el in ov["elements"]:
        tags = el.get("tags") or {}
        name = (tags.get("name") or tags.get("name:vi") or "").strip()
        amenity = tags.get("amenity", "")
        healthcare = tags.get("healthcare", "")
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
        if not (LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX):
            continue  # defensive: skip out-of-Hanoi junk
        nn = normalize_name(name)
        # gentle location dedup: same normalized name AND <150 m => same facility,
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
                dedup_dropped.append((kept["osm_type"], kept["osm_id"], kept["facility_name"],
                                      f"{el['type']}/{el['id']}", kept["latitude"], kept["longitude"]))
                del seen[keep_key]
            else:
                dedup_dropped.append((el["type"], el["id"], name, dup_of, lat, lon))
                continue
        addr = " ".join(x for x in [
            tags.get("addr:housenumber", ""), tags.get("addr:street", "")] if x)
        district2, ward3 = lookup_ward(gadm_feats, lon, lat)
        match_status, match_dist = "mới (không có trong case1)", ""
        if name:
            best = None  # (dist, case1_name, is_point_match) — point match needs SAME name
            for cnn, clat, clon in case1_pts:
                if not cnn or cnn != nn:
                    continue
                d = haversine_m(lat, lon, clat, clon)
                if d < 300:
                    best = (d, cnn, True)
                    break
            if best:
                match_status = "trùng điểm case1 (HOT OSM points)"
                match_dist = f"{best[0]:.0f}"
            else:
                same_names = [(cnn, clat, clon) for cnn, clat, clon in case1_pts if cnn == nn]
                if same_names:
                    match_status = "cùng tên case1, khác vị trí"
        seen[key] = {
            "facility_name": name,
            "facility_class": classify_facility(name, amenity, healthcare),
            "amenity": amenity, "healthcare": healthcare, "address": addr,
            "ward_osm": tags.get("addr:ward", ""), "district_osm": tags.get("addr:district", ""),
            "ward_gadm41": ward3, "district_gadm41": district2,
            "commune_in_name": commune_in_name(name),
            "latitude": lat, "longitude": lon, "coordinate_basis": basis,
            "match_status_case1": match_status, "matched_case1_distance_m": match_dist,
            "source_url": SOURCE_URL_ELEMENT.format(type=el["type"], id=el["id"]),
            "source_date": source_date, "license": LICENSE,
            "osm_type": el["type"], "osm_id": str(el["id"]),
            "name_normalized": nn, "possible_duplicate_of": dup_of,
        }
    return list(seen.values()), dedup_dropped


def load_raw_latest() -> tuple[Path, dict]:
    files = sorted(RAW_DIR.glob("overpass_hanoi_health_*.json"))
    if not files:
        raise SystemExit("no raw Overpass JSON in data/raw/hanoi_health_stations; run online mode")
    return files[-1], json.loads(files[-1].read_text())


def write_csv(path: Path, rows: list[dict], columns: list[str]):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def self_check() -> list[str]:
    """Validate bounds, uniqueness, provenance sha256, class vocabulary, no fake coords."""
    errs = []
    inv = OUT_DIR / "hanoi_health_stations_inventory.csv"
    prov_p = RAW_DIR / "provenance.json"
    if not inv.exists():
        return ["missing " + str(inv)]
    with open(inv, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    ids = [(r["osm_type"], r["osm_id"]) for r in rows]
    if len(ids) != len(set(ids)):
        errs.append("duplicate (osm_type,osm_id)")
    n_named = n_station = 0
    for r in rows:
        lat, lon = float(r["latitude"]), float(r["longitude"])
        if not (LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX):
            errs.append(f"out of Hanoi bounds: {r['osm_id']} {lat},{lon}")
        if r["facility_class"] not in ALLOWED_CLASSES:
            errs.append(f"bad facility_class: {r['facility_class']!r}")
        if r["match_status_case1"] not in {
                "mới (không có trong case1)", "trùng điểm case1 (HOT OSM points)",
                "cùng tên case1, khác vị trí"}:
            errs.append(f"bad match_status_case1: {r['match_status_case1']!r}")
        if not r["source_url"].startswith("https://www.openstreetmap.org/"):
            errs.append("bad source_url")
        if not r["source_date"]:
            errs.append("missing source_date")
        if r["coordinate_basis"] not in {"osm_node", "osm_way_center", "osm_relation_center"}:
            errs.append("bad coordinate_basis (no geocoding allowed)")
        if r["facility_name"]:
            n_named += 1
        if r["facility_class"] == STATION_CLASS:
            n_station += 1
            if not (TYT_RE.search(r["facility_name"]) or TRAM_XA_RE.search(r["facility_name"])
                    or "tram y te" in r["name_normalized"]):
                errs.append(f"station class without name evidence: {r['osm_id']}")
    if n_station <= 19:
        errs.append(f"station rows ({n_station}) did not expand beyond the 19 case1 names")
    geo = OUT_DIR / "hanoi_health_stations_geolocated.csv"
    if geo.exists():
        with open(geo, encoding="utf-8-sig") as f:
            grows = list(csv.DictReader(f))
        full_ids = set(ids)
        for g in grows:
            if g["facility_class"] != STATION_CLASS or not g["facility_name"]:
                errs.append(f"geolocated row not a named station: {g['osm_id']}")
            if (g["osm_type"], g["osm_id"]) not in full_ids:
                errs.append(f"geolocated row missing from inventory: {g['osm_id']}")
            if not g["latitude"] or not g["longitude"]:
                errs.append(f"geolocated row without coordinates: {g['osm_id']}")
    else:
        errs.append("missing geolocated csv")
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
    msg = (f"SELF-CHECK OK: {len(rows)} unique health facilities, {n_named} named, "
           f"{n_station} trạm y tế station rows, bounds+provenance+classes valid")
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

    retrieval_utc = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if args.offline:
        raw_path, ov = load_raw_latest()
        # keep probe evidence from the online run (probes are not rebuild-able offline)
        prev = RAW_DIR / "provenance.json"
        probes = json.loads(prev.read_text()).get("probes_not_used_as_data", []) \
            if prev.exists() else []
    else:
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        raw_path = RAW_DIR / f"overpass_hanoi_health_{stamp}.json"
        print("fetching Overpass (Hanoi relation 1903516, clinic+doctors+hospital+healthcare+name TYT, all geometries)...",
              file=sys.stderr)
        ov = fetch_overpass(raw_path)
        print("probing official station directories (soyte.hanoi.gov.vn, hanoicdc.gov.vn)...",
              file=sys.stderr)
        probes = run_probes(retrieval_utc)

    source_date = dt.date.today().isoformat()
    osm_base = ov.get("osm3s", {}).get("timestamp_osm_base", "")
    n_raw = len(ov["elements"])
    endpoint_used = SOURCE_URL_BULK
    from collections import Counter
    raw_types = Counter(el["type"] for el in ov["elements"])

    prov = {
        "source": "OpenStreetMap via Overpass API (ODbL 1.0)",
        "api_endpoints": OVERPASS_ENDPOINTS,
        "query": OVERPASS_QUERY,
        "retrieved_utc": retrieval_utc,
        "osm_data_timestamp": osm_base,
        "generator": ov.get("generator", ""),
        "raw_files": [],  # filled below with every raw JSON present (incl. earlier fetches)
        "raw_element_types": dict(raw_types),
        "probes_not_used_as_data": probes,
        "case1_baseline": {
            "file": "data/processed/case1/facilities.csv",
            "health_facility_rows": 320,
            "named_tram_y_te": 19,  # names containing "trạm y tế"
            "named_tram_xa_variants": 2,  # "Tram Xa Co Nhue", "trạm xá" — matched by TYT_RE
            "note": "HOT OSM export points only (no polygons) via HDX; read-only baseline",
        },
        "gadm": {"file": "data/processed/hanoi_boundaries.geojson",
                  "vintage": "GADM 4.1 historical 584 communes (pre-2025 reorg)"},
        "post_reorg_note": ("Hanoi reorganized 2025-07-01 to 126 new phường/xã "
                             "(per Sở Y tế Hà Nội article, see data/raw/hanoi_vaccination_public); "
                             "no old->new commune mapping is fabricated here"),
    }
    for rf in sorted(RAW_DIR.glob("overpass_hanoi_health_*.json")):
        prov["raw_files"].append({"name": rf.name, "sha256": sha256_file(rf),
                                   "bytes": rf.stat().st_size,
                                   "elements": len(json.loads(rf.read_text())["elements"])})
    prov["endpoint_used_for_raw_file"] = endpoint_used
    (RAW_DIR / "provenance.json").write_text(json.dumps(prov, ensure_ascii=False, indent=2))

    case1_pts = load_case1_health_points()
    gadm_feats = load_gadm()
    n_case1_tyt = sum(1 for cnn, _, _ in case1_pts
                      if TYT_RE.search(cnn) or "tram y te" in cnn)
    print(f"gadm: {len(gadm_feats)} historical communes | case1 health baseline: {len(case1_pts)} pts "
          f"({n_case1_tyt} named TYT)", file=sys.stderr)

    t0 = time.time()
    recs, dropped = build_records(ov, case1_pts, gadm_feats, source_date)
    print(f"built {len(recs)} records, dropped {len(dropped)} near-duplicates "
          f"in {time.time()-t0:.1f}s", file=sys.stderr)

    write_csv(OUT_DIR / "hanoi_health_stations_inventory.csv", recs, INVENTORY_COLUMNS)

    if dropped:
        with open(RAW_DIR / "dedup_log.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["dropped_osm_type", "dropped_osm_id", "dropped_name",
                        "kept_osm", "lat", "lon"])
            w.writerows(dropped)

    # geolocated subset: named commune stations (TYT) with source coordinates only
    geo = [r for r in recs if r["facility_class"] == STATION_CLASS and r["facility_name"]]
    write_csv(OUT_DIR / "hanoi_health_stations_geolocated.csv", geo, INVENTORY_COLUMNS)

    # ------------------------------------------------------------- findings
    cls = Counter(r["facility_class"] for r in recs)
    d_up = Counter(r["district_gadm41"] or "(ngoài ranh GADM)" for r in recs)
    ms = Counter(r["match_status_case1"].split(" (")[0] for r in recs)
    stations = [r for r in recs if r["facility_class"] == STATION_CLASS]
    st_named = [r for r in stations if r["facility_name"]]
    st_ms = Counter(r["match_status_case1"].split(" (")[0] for r in st_named)
    st_communes_gadm = sorted({(r["district_gadm41"], r["ward_gadm41"]) for r in st_named
                                if r["ward_gadm41"]})
    st_commune_tokens = sorted({r["commune_in_name"] for r in st_named if r["commune_in_name"]})
    st_basis = Counter(r["coordinate_basis"] for r in st_named)
    case1_covered = sum(1 for r in st_named
                        if r["match_status_case1"].startswith("trùng điểm"))
    new_named_tyt = sum(1 for r in st_named
                        if r["match_status_case1"].startswith("mới"))
    same_name_diff_pos = sum(1 for r in st_named
                             if r["match_status_case1"].startswith("cùng tên"))

    lines = []
    A = lines.append
    A(f"# Kết quả thu thập dữ liệu trạm y tế xã/phường Hà Nội ({source_date})\n")
    A("## Nguồn và phạm vi\n")
    A("- **Nguồn dữ liệu chính**: OpenStreetMap qua Overpass API (ODbL 1.0), quan hệ hành")
    A("  chính *Thành phố Hà Nội* (relation 1903516, admin_level=4).")
    A("- **Truy vấn hợp nhất 3 vế bằng chứng, mỗi vế đủ 3 loại hình học** (node + way +")
    A("  relation, điểm way/relation lấy tâm polygon `out center`):")
    A("  1) `amenity` ∈ {clinic, doctors, hospital}; 2) có tag `healthcare` bất kỳ;")
    A("  3) tên chứa `tr[ạa]m y t` (không phân biệt hoa/thường).")
    A("- **URL gốc + sha256 + ngày truy xuất**: `data/raw/hanoi_health_stations/provenance.json`.")
    A(f"- Dữ liệu gốc OSM chốt thời điểm: `{osm_base}`; truy xuất {retrieval_utc}.")
    A("- Thăm dò cổng chính thức (chỉ lưu bằng chứng, **không dùng làm nguồn dữ liệu**):")
    for p in prov["probes_not_used_as_data"]:
        status = p.get("http_status", "?")
        titles = "; ".join(t[:60] for t in p.get("result_titles", [])[:3])
        A(f"  - `{p['slug']}` ({p['url']}) -> HTTP {status}. {p['note']}."
          + (f" Tiêu đề thấy: {titles}." if titles else ""))
    A("  → **Không tìm thấy danh mục trạm y tế máy đọc được** (địa chỉ từng trạm) trên")
    A("    cổng Sở Y tế / CDC; mọi bản ghi dưới đây đều bằng chứng OSM, không suy đoán.\n")
    A("## Kết quả chính\n")
    A(f"- **Tổng bản ghi cơ sở y tế sau khử trùng lặp cục bộ: {len(recs)}** (thô {n_raw} phần tử OSM: "
      + ", ".join(f"{v} {k}" for k, v in sorted(raw_types.items())) + ").")
    A(f"- **Trạm y tế xã/phường (lớp `trạm y tế`, suy từ tên): {len(st_named)} bản ghi có tên**"
      f" → mở rộng so với case1 (HOT export chỉ POINT) có **19 tên chứa 'trạm y tế'**"
      f" + 2 biến thể 'trạm xá' ({', '.join(sorted({r['facility_name'] for r in st_named if 'trạm y tế' not in r['name_normalized'] and 'tram y te' not in r['name_normalized']}))}).")
    A(f"- Tập \"geolocated\" (chỉ TYT có tên + tọa độ nguồn): **{len(geo)} bản ghi**"
      f" → `data/processed/hanoi_health_stations/hanoi_health_stations_geolocated.csv`.")
    A("- Tọa độ theo nguồn: " + ", ".join(f"{v} {k}" for k, v in sorted(st_basis.items()))
      + " — **100% tọa độ nguồn, 0 bản ghi address-only, không geocode suy đoán**.")
    A(f"- Đối chiếu case1 (19 tên “trạm y tế” + 2 tên biến thể “trạm xá”): **{case1_covered} trùng điểm** (<300 m + cùng tên),"
      f" {same_name_diff_pos} cùng tên khác vị trí, **{new_named_tyt} trạm mới** không có trong case1.\n")
    A("### Phân loại theo bằng chứng tên/tag (không suy đoán)\n")
    for k in sorted(cls, key=lambda x: -cls[x]):
        A(f"- `{k}`: **{cls[k]}**")
    A("\n### Trạm y tế theo quận/huyện (GADM 4.1, tên lịch sử)\n")
    st_d = Counter(r["district_gadm41"] or "(ngoài ranh GADM)" for r in st_named)
    for k in sorted(st_d, key=lambda x: -st_d[x]):
        A(f"- {k}: {st_d[k]}")
    A(f"\n### Phạm vi phủ xã/phường\n")
    A(f"- Trạm TYT có tên nằm trong **{len(st_communes_gadm)} xã/phường GADM 4.1 riêng biệt**")
    A(f"  (trong tổng số **584 xã GADM 4.1 lịch sử**, tức {len(st_communes_gadm)}/584"
      f" = {100*len(st_communes_gadm)/584:.1f}%).")
    A(f"- **{len(st_commune_tokens)}** tên xã/phường/thị trấn khác nhau trích được từ tên trạm"
      f" (`commune_in_name`, bằng chứng chữ trong tên, không phải geocode).")
    A("- **KHÔNG khẳng định mỗi xã đều có trạm**: OSM là crowdsourced, nhiều trạm chưa được")
    A("  vẽ; số trên là chốt dưới của mật độ thực, không phải độ phủ hành chính.")
    A("- Từ 2025-07-01 Hà Nội sáp nhập còn **126 phường/xã mới**; GADM 4.1 trong repo vẫn là")
    A("  584 xã lịch sử → ranh/`ward_gadm41` là TÊN CŨ, chưa có ánh xạ cũ→mới công khai máy")
    A("  đọc được ở đây (không chế tạo ánh xạ).\n")
    A("## Giới hạn / tính trung thực\n")
    A("- Tọa độ way/relation là **tâm polygon từ nguồn** (`coordinate_basis`), không phải đo độc lập.")
    A("- **Không geocode suy đoán, không lấy tâm xã**: mọi tọa độ từ hình học OSM;")
    A("  không có bản ghi address-only vì không nguồn chính thức nào cho ra bản ghi.")
    A("- Phân loại dựa trên **quy ước tên tiếng Việt** (Trạm y tế/Trạm xá) + tag OSM;")
    A("  trạm thiếu tên chuẩn có thể rơi lớp khác — mở raw JSON để kiểm chứng từng phần tử.")
    A("- Khử trùng chỉ gộp **cùng tên chuẩn hóa + cách <150 m**; các cơ sở 1/2, trùng tên khác")
    A(f"  vị trí **giữ nguyên**; {len(dropped)} phần tử bị gộp gần, xem `dedup_log.csv`.")
    A("- Không có **sức chứa/năng lực** nào được gán (không chế tạo capacity).")
    A("- Chưa tích hợp vào Case1 (bản đồ/model): cần audit người trước khi dùng.\n")
    A("## Lệnh tái lập\n")
    A("```bash")
    A("python3 scripts/collect_hanoi_health_stations.py             # tải mới + xuất CSV")
    A("python3 scripts/collect_hanoi_health_stations.py --offline   # dựng lại từ JSON đã lưu")
    A("python3 scripts/collect_hanoi_health_stations.py --self-check")
    A("python3 tests/test_health_stations.py                        # test nhỏ (stdlib)")
    A("```")
    (OUT_DIR / "findings.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"\nwrote {OUT_DIR/'hanoi_health_stations_inventory.csv'} ({len(recs)} rows)")
    print(f"wrote {OUT_DIR/'hanoi_health_stations_geolocated.csv'} ({len(geo)} rows)")
    print(f"wrote {OUT_DIR/'findings.md'}")
    print(f"wrote {RAW_DIR/'provenance.json'}")
    self_check()


if __name__ == "__main__":
    main()
