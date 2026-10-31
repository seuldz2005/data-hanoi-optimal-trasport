"""Conservative school dedup and regenerated HTML checks."""
import csv
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from merge_school_inventory import merge


def test_merge_dedup_and_idempotence():
    base = [dict(facility_id='1', facility_name='THPT A', facility_type='school', latitude='21', longitude='105.8', capacity='', capacity_source='missing', source='baseline')]
    def school(osm_id, name, lat='21', osm_type='way'):
        return dict(osm_type=osm_type, osm_id=osm_id, school_name=name, latitude=lat, longitude='105.8')
    inventory = [school('1', 'Renamed', osm_type='node'), school('2', 'THPT A'), school('3', 'THPT B'), school('4', 'THPT A', '21.1')]
    rows, log, stats = merge(base, inventory)
    assert len(rows) == 3
    assert stats['added'] == 2
    assert stats['skipped_duplicate_exact_osm_id'] == 1
    assert stats['skipped_duplicate_name_within_150m'] == 1
    again, _, repeat = merge(rows, inventory)
    assert again == rows
    assert repeat['added'] == 0


def test_school_html_and_merge_audit():
    root = Path(__file__).resolve().parents[1]
    def read(path):
        with path.open(encoding='utf-8-sig') as f:
            return list(csv.DictReader(f))
    schools = read(root / 'data/processed/case2/scenario2_education_facilities.csv')
    audit = read(root / 'data/processed/case2/scenario2_merge_log.csv')
    assert len(audit) == 1332
    added = [r for r in audit if r['decision'] == 'added']
    assert len(schools) == 332 + len(added)
    assert len({r['facility_id'] for r in schools}) == len(schools)
    html = (root / 'docs/index.html').read_text()
    assert html.count('Trường học — ứng viên tiêm chủng') == len(schools)
    assert (root / 'docs/index.html').read_bytes() == (root / 'data/processed/case1/allocation_map.html').read_bytes()
