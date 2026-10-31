"""Regression tests for the data-test/temporal_100x50 temporal package.

Loads the generator module directly (no package install), unit-tests the
constrained integer split/sampler edge cases, re-uses the benchmark
fixtures, and validates the generated CSV outputs when present.
"""
from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / 'data-test/temporal_100x50'

spec = importlib.util.spec_from_file_location('tgen', PKG / 'prepare.py')
tgen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tgen)

spec_b = importlib.util.spec_from_file_location('tbm', PKG / 'benchmarks/benchmarks.py')
tbm = importlib.util.module_from_spec(spec_b)
spec_b.loader.exec_module(tbm)


def test_hour_bounds_exact_integer_math():
    for x in [1, 7, 100, 151, 999, 5121]:
        lo, hi = tgen.hour_bounds(x)
        assert lo == math.ceil(0.2 * x) == -((-x) // 5)
        assert hi == math.floor(0.3 * x) == (3 * x) // 10


def test_sampler_bounds_sum_and_reject():
    rng = np.random.default_rng(tgen.SEED)
    for x in [151, 500, 5121]:
        a = tgen.sample_hourly_arrivals(x, rng)
        lo, hi = tgen.hour_bounds(x)
        assert sum(a) == x and all(lo <= v <= hi for v in a)
    with pytest.raises(ValueError):
        tgen.sample_hourly_arrivals(2, np.random.default_rng(0))  # 4*ceil(0.4) > 2


def test_sampler_seed_stable_and_permuted():
    a = tgen.sample_hourly_arrivals(1000, np.random.default_rng(tgen.SEED))
    b = tgen.sample_hourly_arrivals(1000, np.random.default_rng(tgen.SEED))
    assert a == b != tgen.sample_hourly_arrivals(1000, np.random.default_rng(tgen.SEED + 1))
    assert sorted(a) != sorted([1000] * 4)  # genuinely distributes across hours


def test_split_hourly_conserves_and_rotates():
    ids = [f'S{i:02d}' for i in range(5)]
    parts = [tgen.split_hourly(53, ids, h) for h in range(1, 5)]
    assert all(sum(p.values()) == 53 for p in parts)
    # rotation spreads the +1 remainder across different leading sites
    assert parts[0][ids[0]] != parts[1][ids[0]] or parts[0][ids[1]] != parts[1][ids[1]]
    per_site = {s: sum(parts[h][s] for h in range(4)) for s in ids}
    assert sum(per_site.values()) == 4 * 53


def test_benchmark_fixtures():
    assert tbm.transport_lp() == tbm.EXPECTED_COST == 530
    q = tbm.queue_bottleneck()
    assert q == tbm.EXPECTED_S1_QUEUE and q[-1] == 0
    assert tbm.simulate_queue([40, 40, 0, 0], [30, 60, 30, 30]) == [10, 0, 0, 0]


@pytest.mark.skipif(not (PKG / 'population.csv').exists(), reason='package not generated')
def test_generated_outputs_invariants():
    pop = pd.read_csv(PKG / 'population.csv')
    sites = pd.read_csv(PKG / 'facilities.csv', dtype={'facility_id': str})
    cap = pd.read_csv(PKG / 'sites_capacity.csv', dtype={'facility_id': str})
    cap_hour = pd.read_csv(PKG / 'capacity_by_hour.csv', dtype={'facility_id': str})
    matrix = pd.read_csv(PKG / 'distance_matrix.csv', index_col=0)
    assert len(pop) == 100 and len(sites) == len(cap) == 50 and len(cap_hour) == 200
    assert matrix.shape == (100, 50)
    assert matrix.index.tolist() == pop.commune_id.tolist()
    assert matrix.columns.tolist() == sites.facility_id.tolist()
    assert np.isfinite(matrix.to_numpy()).all() and (matrix.to_numpy() >= 0).all()
    agg = cap_hour.groupby('facility_id').capacity_balanced.sum()
    np.testing.assert_array_equal(agg.reindex(cap.facility_id).to_numpy(), cap.capacity.to_numpy())
    for h in range(1, 5):
        arr = pd.read_csv(PKG / f'arrivals/hour_{h}.csv')
        assert arr.commune_id.tolist() == pop.commune_id.tolist()
        hour = cap_hour[cap_hour.hour == h]
        assert int(arr.arrivals.sum()) == int(hour.capacity_balanced.sum())
        assert int(hour.capacity_surplus.sum()) == (11 * int(arr.arrivals.sum()) + 9) // 10
    # exact 20-30% bounds per commune per hour
    for row in pop.itertuples():
        lo, hi = tgen.hour_bounds(int(row.children_under_5))
        for h in range(1, 5):
            a = pd.read_csv(PKG / f'arrivals/hour_{h}.csv').set_index('commune_id')
            assert lo <= int(a.loc[row.commune_id, 'arrivals']) <= hi
    # distance matrix is a verbatim ID subset of the Case 1 source
    src = pd.read_csv(ROOT / 'data/processed/case1/distance_matrix.csv', index_col=0)
    np.testing.assert_array_equal(matrix.to_numpy(),
                                  src.loc[pop.commune_id, sites.facility_id].to_numpy())
    # site labels/IDs retained; no banned candidate types
    assert sites.facility_name.notna().all()
    assert not sites.facility_type.isin(['pharmacy', 'dentist', 'doctors']).any()
    assert not sites.facility_name.fillna('').str.contains(
        'Đại học|đại học|Cao đẳng|cao đẳng|College|University|university').any()
