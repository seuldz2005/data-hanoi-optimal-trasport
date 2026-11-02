"""Update docs/index.html by merging new collected stations into the clinic layer; Case1 unchanged."""
import csv
import json
import re
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'data/processed/hanoi_health_stations/hanoi_health_stations_geolocated.csv'
OUT = ROOT / 'docs/index.html'
START, END = '// BEGIN HEALTH STATIONS SURVEY', '// END HEALTH STATIONS SURVEY'


def build():
    rows = list(csv.DictReader(SOURCE.open(encoding='utf-8-sig')))
    assert rows and len({(r['osm_type'], r['osm_id']) for r in rows}) == len(rows)
    html = OUT.read_text(encoding='utf-8')
    html = re.sub(re.escape(START) + r'.*?' + re.escape(END) + r'\n?', '', html, flags=re.S)
    html = re.sub(r'^\s*"MAP-1: Facility (?:—|\\u2014) Trạm y tế khảo sát[^\n]+\n', '', html, flags=re.M)
    clinic = re.search(r'"MAP-1: Facility (?:—|\\u2014) clinic"\s*:\s*(feature_group_\w+)', html).group(1)
    marker = re.search(r'L\.circleMarker\(\s*\[[^]]+\],\s*(\{[^}]+\})\s*\)\.addTo\(' + clinic + r'\)', html)
    assert marker, 'Clinic marker style not found'
    clinic_style = json.loads(marker.group(1))
    control = re.search(r'var layer_control_\w+_layers = \{', html)
    assert control, 'Existing Leaflet layer control not found'
    js = [START]
    new_rows = [r for r in rows if r['match_status_case1'].startswith('mới')]
    for r in new_rows:
        lat, lon = float(r['latitude']), float(r['longitude'])
        assert 20 < lat < 22 and 105 < lon < 107
        assert r['source_url'].startswith('https://www.openstreetmap.org/')
        text = '<b>' + escape(r['facility_name']) + '</b><br>' + '<br>'.join(escape(x) for x in [
            r['ward_gadm41'] + ' · ' + r['district_gadm41'] + ' (ranh giới cũ)',
            r['address'] or 'Chưa có địa chỉ đường phố', r['match_status_case1'],
            'Tọa độ nguồn: ' + r['coordinate_basis'],
            'Khảo sát OSM ' + r['source_date'] + '; chưa xác minh điểm tiêm.',
            'Chưa có năng lực phục vụ; chưa dùng tính tuyến phân bổ.',
        ]) + '<br><a target="_blank" rel="noopener noreferrer" href="' + escape(r['source_url'], quote=True) + '">Nguồn OSM</a>'
        options = clinic_style
        safe = lambda x: json.dumps(x, ensure_ascii=False).replace('<', '\\u003c')
        js.append(f'L.circleMarker([{lat},{lon}],{safe(options)}).bindTooltip({safe(escape(r["facility_name"]))}).bindPopup({safe(text)}).addTo({clinic});')
    js.append(END)
    html = html[:control.start()] + '\n'.join(js) + '\n' + html[control.start():]
    assert html.count(START) == 1 and 'health_stations_survey' not in html
    OUT.write_text(html, encoding='utf-8')
    print(f'Updated {OUT}: {len(new_rows)} stations merged into clinic, {len(rows)-len(new_rows)} existing stations skipped; Case1 allocation unchanged')


if __name__ == '__main__':
    build()
