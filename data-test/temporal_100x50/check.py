"""Validate the temporal_100x50 package: PYTHONPATH=src ../.venv/bin/python data-test/temporal_100x50/check.py

Checks counts, ID alignment, exact arrival bounds (20-30% per row), per-hour
conservation against capacities, seed stability, source locality, subset
distance integrity, baseline LP feasibility (4 sparse hourly LPs), and the
recorded regeneration hashes. Writes solver_summary.json.
"""
from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import linprog
from scipy.sparse import coo_matrix

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
spec = importlib.util.spec_from_file_location('tgen', OUT / 'prepare.py')
tgen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tgen)

N, M, H = 100, 50, 4


def main() -> None:
    pop = pd.read_csv(OUT / 'population.csv')
    sites = pd.read_csv(OUT / 'facilities.csv', dtype={'facility_id': str})
    cap = pd.read_csv(OUT / 'sites_capacity.csv', dtype={'facility_id': str})
    cap_hour = pd.read_csv(OUT / 'capacity_by_hour.csv', dtype={'facility_id': str})
    matrix = pd.read_csv(OUT / 'distance_matrix.csv', index_col=0)
    meta = json.loads((OUT / 'metadata.json').read_text(encoding='utf-8'))
    arr = {h: pd.read_csv(OUT / f'arrivals/hour_{h}.csv') for h in range(1, H + 1)}

    # counts / IDs / shapes
    assert len(pop) == N and len(sites) == M and len(cap) == M and len(cap_hour) == M * H
    assert pop.commune_id.is_unique and sites.facility_id.is_unique and cap.facility_id.is_unique
    assert matrix.shape == (N, M)
    assert matrix.index.tolist() == pop.commune_id.tolist()
    assert matrix.columns.tolist() == sites.facility_id.tolist() == cap.facility_id.tolist()

    # finite / nonnegative / coordinate ranges / integer masses
    D = matrix.to_numpy()
    assert np.isfinite(D).all() and (D >= 0).all()
    assert sites.latitude.between(-90, 90).all() and sites.longitude.between(-180, 180).all()
    assert pop.children_under_5.dtype.kind == 'i' and cap.capacity.dtype.kind == 'i'
    assert cap_hour.capacity_balanced.dtype.kind == 'i' and cap_hour.capacity_surplus.dtype.kind == 'i'
    assert arr[1].arrivals.dtype.kind == 'i'
    assert sites.capacity.isna().all()  # no real capacity in facilities.csv
    assert set(sites.site_class) <= {'health_facility', 'school'} and sites.facility_name.notna().all()
    banned = sites.facility_name.fillna('').str.contains(
        'Đại học|đại học|Cao đẳng|cao đẳng|College|University|university')
    assert not banned.any() and not sites.facility_type.isin(['pharmacy', 'dentist', 'doctors']).any()

    # exact 20-30% per-row bounds and per-commune conservation
    rng = np.random.default_rng(tgen.SEED)
    for row in pop.itertuples():
        lo, hi = tgen.hour_bounds(int(row.children_under_5))
        assert lo == math.ceil(0.2 * row.children_under_5)
        assert hi == math.floor(0.3 * row.children_under_5)
        got = [int(arr[h].set_index('commune_id').loc[row.commune_id, 'arrivals']) for h in range(1, H + 1)]
        assert all(lo <= a <= hi for a in got), f'hour bound violated for {row.commune_id}'
        assert sum(got) == int(row.children_under_5)
        assert got == tgen.sample_hourly_arrivals(int(row.children_under_5), rng)  # seed stability

    # per-hour conservation: balanced == arrivals, surplus == ceil(1.1*arrivals)
    for h in range(1, H + 1):
        a = int(arr[h].arrivals.sum())
        bal = cap_hour[cap_hour.hour == h].capacity_balanced.sum()
        sur = cap_hour[cap_hour.hour == h].capacity_surplus.sum()
        assert bal == a
        assert sur == (11 * a + 9) // 10
    # per-site aggregate across hours == sites_capacity
    agg = cap_hour.groupby('facility_id').capacity_balanced.sum()
    np.testing.assert_array_equal(agg.reindex(cap.facility_id).to_numpy(), cap.capacity.to_numpy())
    assert int(cap_hour.capacity_balanced.sum()) == int(pop.children_under_5.sum())
    assert (cap_hour.capacity_surplus >= cap_hour.capacity_balanced).all()

    # source locality: sites inside cluster, communes connected, subset distances unaltered
    import geopandas as gpd
    cluster = gpd.read_file(OUT / 'commune_boundaries.geojson')
    assert len(cluster) == N and cluster.commune_id.is_unique
    assert set(cluster.commune_id) == set(pop.commune_id)
    pts = gpd.GeoSeries(gpd.points_from_xy(sites.longitude, sites.latitude), crs=4326)
    assert pts.intersects(cluster.geometry.union_all()).all()
    geoms = cluster.set_index('commune_id').geometry
    ids = cluster.commune_id.tolist()
    seen, stack = {ids[0]}, [ids[0]]
    while stack:
        node = stack.pop()
        for other in ids:
            if other not in seen and geoms[node].intersects(geoms[other]):
                seen.add(other)
                stack.append(other)
    assert len(seen) == N, 'commune cluster not connected'
    src_matrix = pd.read_csv(ROOT / 'data/processed/case1/distance_matrix.csv', index_col=0)
    np.testing.assert_array_equal(D, src_matrix.loc[pop.commune_id, sites.facility_id].to_numpy())

    # baseline LP feasibility per hour: sparse linprog (A_eq 200x5000)
    summary = {'package': 'temporal_100x50', 'scenario': 'baseline', 'solver': 'scipy.optimize.linprog/highs (sparse)'}
    for h in range(1, H + 1):
        demand = arr[h].set_index('commune_id').loc[pop.commune_id, 'arrivals'].to_numpy()
        supply = cap_hour[cap_hour.hour == h].set_index('facility_id').loc[
            sites.facility_id, 'capacity_balanced'].to_numpy()
        c = D.reshape(-1).astype(float)
        r_i = np.arange(N * M)
        A_row = coo_matrix((np.ones(N * M), (np.repeat(np.arange(N), M), r_i)), shape=(N, N * M))
        A_col = coo_matrix((np.ones(N * M), (np.tile(np.arange(M), N), r_i)), shape=(M, N * M))
        from scipy.sparse import vstack
        A_eq = vstack([A_row, A_col]).tocsr()
        res = linprog(c, A_eq=A_eq, b_eq=np.concatenate([demand, supply]),
                      bounds=(0, None), method='highs')
        assert res.status == 0, f'hour {h} LP status {res.status}'
        summary[f'hour_{h}'] = {'status': 'success', 'total_child_km': round(float(res.fun), 3),
                               'arrivals': int(demand.sum())}
    summary['total_child_km_4h'] = round(sum(summary[f'hour_{h}']['total_child_km'] for h in range(1, H + 1)), 3)
    (OUT / 'solver_summary.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')

    # deterministic regeneration hashes (outputs; metadata/solver timestamps excluded)
    import hashlib
    for name, digest in meta['outputs'].items():
        assert hashlib.sha256((OUT / name).read_bytes()).hexdigest() == digest, f'hash drift: {name}'
    src_dir = ROOT / 'data/processed'
    for name, digest in meta['inputs'].items():
        assert hashlib.sha256((src_dir / name).read_bytes()).hexdigest() == digest, f'input drift: {name}'

    print('PASS:', json.dumps({'communes': N, 'sites': M, 'hours': H,
                               'total_children': int(pop.children_under_5.sum()),
                               'per_hour_arrivals': [summary[f'hour_{h}']['arrivals'] for h in range(1, H + 1)],
                               'per_hour_child_km': [summary[f'hour_{h}']['total_child_km'] for h in range(1, H + 1)]}))


if __name__ == '__main__':
    main()
