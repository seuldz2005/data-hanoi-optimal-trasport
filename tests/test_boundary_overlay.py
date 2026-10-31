"""Boundary overlay is independent of the population feature group."""
import re
import json
from pathlib import Path


def test_boundary_overlay_is_independent():
    html = Path('docs/index.html').read_text()
    label = 'Ranh giới xã/phường (GADM 4.1)'
    match = re.search(r'"' + re.escape(json.dumps(label)[1:-1]) + r'"\s*:\s*(geo_json_[a-f0-9]+)', html)
    assert match, 'Standalone boundary checkbox missing'
    layer = match.group(1)
    assert re.search(re.escape(layer) + r'\.addTo\(map_[a-f0-9]+\)', html)
    assert '"fill": false' in html
    assert 'MAP-1: Population under age 5 (2020)' in html
    assert Path('docs/index.html').read_bytes() == Path('data/processed/case1/allocation_map.html').read_bytes()
