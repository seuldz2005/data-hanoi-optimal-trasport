"""Hand-solved benchmarks for the temporal_100x50 package.

Run from the repo root:
    PYTHONPATH=src ../.venv/bin/python data-test/temporal_100x50/benchmarks/benchmarks.py

Benchmark 1 (transport LP, 3x2): x=[100,120,80], y=[150,150],
D=[[2,5],[4,1],[3,2]]. Hand optimum: A->Y1 100 (200), B->Y2 120 (120),
C->Y1 50 (150) + C->Y2 30 (60) => total 530. Solved independently with
sparse scipy linprog to confirm the checker, allocation asserted exactly.

Benchmark 2 (queue bottleneck): global per-hour capacity >= per-hour
arrivals everywhere, yet origin A can only reach the constrained site S1,
whose hour-1 capacity (30) is below A's hour-1 arrivals (40). A queue
forms (q(2)=10) and drains in hour 2; the terminal queue q(5) must be 0.
Queues evolve as q(t+1) = max(0, q(t) + arrivals_to_site(t) - capacity(t))
for hours t = 1..4, q(1) = 0 initial state before hour 1, so the state
after hour 4 is q(5). Expected queues below are immutable fixture results.
Total capacity adequacy does NOT guarantee zero local queues; unused
service capacity is never banked across hours, and vaccine stock/supply
is a separate quantity from this service capacity.

Benchmark 3 (package smoke): the real sites_capacity.csv /
capacity_by_hour.csv / arrivals files satisfy per-hour conservation, so
the system-wide service queue stays at 0 in the balanced scenario.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import linprog
from scipy.sparse import coo_matrix, vstack

OUT = Path(__file__).resolve().parents[1]

X = [100, 120, 80]
Y = [150, 150]
D = [[2, 5], [4, 1], [3, 2]]
EXPECTED_COST = 530
EXPECTED_ALLOC = {(0, 0): 100, (1, 1): 120, (2, 0): 50, (2, 1): 30}

HOURS = [1, 2, 3, 4]
A_ARRIVALS = [40, 40, 0, 0]          # origin A: only site S1 reachable
B_ARRIVALS = [30, 30, 30, 30]        # origin B: both sites reachable
S1_CAP = [30, 60, 30, 30]            # locally constrained site
S2_CAP = [40, 40, 40, 40]
EXPECTED_S1_QUEUE = [10, 0, 0, 0]    # q(2)..q(5); terminal q(5) == 0


def transport_lp():
    """Solve the 3x2 transport problem with sparse linprog; assert 530."""
    n, m = len(X), len(Y)
    c = np.array(D, dtype=float).reshape(-1)
    r_i = np.arange(n * m)
    A_row = coo_matrix((np.ones(n * m), (np.repeat(np.arange(n), m), r_i)), shape=(n, n * m))
    A_col = coo_matrix((np.ones(n * m), (np.tile(np.arange(m), n), r_i)), shape=(m, n * m))
    res = linprog(c, A_eq=vstack([A_row, A_col]).tocsr(),
                  b_eq=np.concatenate([X, Y]), bounds=(0, None), method='highs')
    assert res.status == 0, res.message
    z = res.x.round().astype(int).reshape(n, m)
    assert abs(res.fun - EXPECTED_COST) < 1e-6, f'LP cost {res.fun} != hand optimum {EXPECTED_COST}'
    for (i, j), v in EXPECTED_ALLOC.items():
        assert z[i, j] == v, f'allocation differs from hand solution at ({i},{j}): {z[i, j]} != {v}'
    assert z.sum(axis=1).tolist() == X and z.sum(axis=0).tolist() == Y
    return int(res.fun)


def simulate_queue(arrivals_to_site, capacity):
    """q(t+1) = max(0, q(t) + arrivals(t) - capacity(t)); returns states q(2)..q(5)."""
    q, states = 0, []
    for a, cap in zip(arrivals_to_site, capacity):
        q = max(0, q + a - cap)
        states.append(q)
    return states


def queue_bottleneck():
    """Global adequacy with local bottleneck: queue forms, then drains; terminal 0."""
    for t in HOURS:  # global capacity >= global arrivals every hour
        assert S1_CAP[t - 1] + S2_CAP[t - 1] >= A_ARRIVALS[t - 1] + B_ARRIVALS[t - 1]
    s1_in = [A_ARRIVALS[t - 1] for t in HOURS]  # A is forced onto S1 (only reachable site)
    q = simulate_queue(s1_in, S1_CAP)
    assert q == EXPECTED_S1_QUEUE, f'queue states {q} != expected {EXPECTED_S1_QUEUE}'
    assert q[-1] == 0, 'terminal queue q(5) must be zero in this fixture'
    return q


def package_smoke():
    """Real package files: balanced per-hour conservation keeps system queue at 0."""
    cap = pd.read_csv(OUT / 'sites_capacity.csv', dtype={'facility_id': str})
    cap_hour = pd.read_csv(OUT / 'capacity_by_hour.csv', dtype={'facility_id': str})
    arrivals = {h: pd.read_csv(OUT / f'arrivals/hour_{h}.csv') for h in HOURS}
    per_site = cap_hour.groupby('facility_id').capacity_balanced.sum()
    np.testing.assert_array_equal(per_site.reindex(cap.facility_id).to_numpy(), cap.capacity.to_numpy())
    for h in HOURS:
        assert int(arrivals[h].arrivals.sum()) == int(
            cap_hour[cap_hour.hour == h].capacity_balanced.sum())
    q = simulate_queue([int(arrivals[h].arrivals.sum()) for h in HOURS],
                       [int(cap_hour[cap_hour.hour == h].capacity_balanced.sum()) for h in HOURS])
    assert q == [0, 0, 0, 0]
    return q


def main():
    if str(OUT.parents[1] / 'src') not in sys.path:
        sys.path.insert(0, str(OUT.parents[1] / 'src'))
    cost = transport_lp()
    queues = queue_bottleneck()
    sys_q = package_smoke()
    print(json.dumps({
        'transport_3x2_optimum': cost,
        'queue_fixture_expected': EXPECTED_S1_QUEUE,
        'queue_fixture_simulated': queues,
        'queue_terminal_q5': queues[-1],
        'package_system_queue_balanced': sys_q,
        'verdict': 'PASS'}, indent=2))


if __name__ == '__main__':
    main()
