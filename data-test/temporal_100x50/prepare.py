"""Generate the 100-commune / 50-site / 4-hour temporal data package.

Interpretation: the 100 communes are demand ORIGINS; the 50 selected
facilities are candidate vaccination SITES that serve them (complete
routing graph, no travel limit). Communes are not 100 on-site clinics.

Run: PYTHONPATH=src ../.venv/bin/python data-test/temporal_100x50/prepare.py
"""
from __future__ import annotations

import datetime
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from hanoi_ot.capacity import largest_remainder_split  # noqa: E402

N_COMMUNES = 100
N_SITES = 50
HOURS = 4
SEED = 20260101
# Historical central urban districts excluded so the cluster stays peripheral.
URBAN_DISTRICTS = ['HoànKiếm', 'BaĐình', 'ĐốngĐa', 'HaiBàTrưng', 'CầuGiấy',
                   'ThanhXuân', 'TâyHồ', 'HoàngMai', 'LongBiên', 'BắcTừLiêm',
                   'NamTừLiêm', 'HàĐông']
SEED_DISTRICTS = ['HoàiĐức', 'QuốcOai']
PROJECTED = 32648  # UTM 48N for centroid distances (CRS84 degrees are not metric)

INPUT_FILES = ['case1/population.csv', 'case1/facilities.csv',
               'case1/distance_matrix.csv', 'hanoi_boundaries.geojson']


def load_sources():
    src = ROOT / 'data/processed'
    boundaries = gpd.read_file(src / 'hanoi_boundaries.geojson')
    population = pd.read_csv(src / 'case1/population.csv')
    facilities = pd.read_csv(src / 'case1/facilities.csv', dtype={'facility_id': str})
    matrix = pd.read_csv(src / 'case1/distance_matrix.csv', index_col=0)
    return boundaries, population, facilities, matrix


def hour_bounds(x: int) -> tuple[int, int]:
    """Exact integer bounds ceil(0.2*x) <= a <= floor(0.3*x) (no float rounding)."""
    return (x + 4) // 5, (3 * x) // 10


def sample_hourly_arrivals(x: int, rng: np.random.Generator,
                          n_hours: int = HOURS) -> list[int]:
    """Constrained sequential sampling: sum == x, each hour within bounds.

    Feasible remainder keeps every partial draw completable; a random hour
    permutation removes the last-hour bias of plain forward sampling.
    """
    lo, hi = hour_bounds(x)
    if n_hours * lo > x or n_hours * hi < x:
        raise ValueError(f'infeasible small total x={x}: 4*{lo} > x or 4*{hi} < x')
    order = rng.permutation(n_hours)
    arrivals = [0] * n_hours
    remaining = x
    for k, h in enumerate(order):
        hours_left = n_hours - k - 1
        if hours_left == 0:
            arrivals[h] = remaining
            continue
        low = max(lo, remaining - hi * hours_left)
        high = min(hi, remaining - lo * hours_left)
        v = int(rng.integers(low, high + 1))
        arrivals[h] = v
        remaining -= v
    assert sum(arrivals) == x
    return arrivals


def select_cluster(boundaries: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Grow 100 connected peripheral communes from the Hoài Đức + Quốc Oai seed.

    Each step adds the non-urban-district frontier commune (exact polygon
    touch against the cluster union) nearest to the seed centroid; ties by
    commune_id. Connectivity is verified by BFS afterwards.
    """
    cluster = boundaries[boundaries.district_name.isin(SEED_DISTRICTS)].copy()
    seed_center = gpd.GeoSeries([cluster.geometry.union_all()], crs=4326).to_crs(
        PROJECTED).centroid.iloc[0]
    while len(cluster) < N_COMMUNES:
        union = cluster.geometry.union_all()
        frontier = boundaries[(~boundaries.commune_id.isin(cluster.commune_id))
                              & (~boundaries.district_name.isin(URBAN_DISTRICTS))
                              & boundaries.geometry.intersects(union)]
        if frontier.empty:
            raise RuntimeError('peripheral frontier exhausted before 100 communes')
        d = frontier.geometry.to_crs(PROJECTED).centroid.distance(seed_center)
        pick = frontier.loc[[d.idxmin()]]
        cluster = pd.concat([cluster, pick])
    cluster = cluster.sort_values('commune_id').reset_index(drop=True)
    assert len(cluster) == N_COMMUNES
    geoms = cluster.set_index('commune_id').geometry
    ids = cluster.commune_id.tolist()
    seen, stack = {ids[0]}, [ids[0]]
    while stack:
        node = stack.pop()
        for other in ids:
            if other not in seen and geoms[node].intersects(geoms[other]):
                seen.add(other)
                stack.append(other)
    assert len(seen) == N_COMMUNES, 'cluster is not exactly connected'
    return cluster


def eligible_sites(cluster: gpd.GeoDataFrame, facilities: pd.DataFrame) -> gpd.GeoDataFrame:
    """Named health stations/clinics and non-university schools inside the cluster.

    Excluded: pharmacies, dentists, doctors offices, unnamed facilities,
    university/college entries. Source IDs and labels retained.
    """
    union = cluster.geometry.union_all()
    points = gpd.GeoDataFrame(facilities, geometry=gpd.points_from_xy(
        facilities.longitude, facilities.latitude), crs=4326)
    inside = points[points.intersects(union)].copy()
    named = inside.facility_name.notna()
    health = inside[(inside.site_class == 'health_facility') & named
                    & (~inside.facility_type.isin(['pharmacy', 'dentist', 'doctors']))]
    school = inside[(inside.site_class == 'school') & named
                    & (~inside.facility_name.fillna('').str.contains(
                        'Đại học|đại học|Cao đẳng|cao đẳng|College|University|university'))]
    return pd.concat([health, school])


def _local_km(frame: pd.DataFrame) -> dict[str, np.ndarray]:
    """Equirectangular local-km coordinates per facility (deterministic)."""
    lat0 = float(frame.latitude.mean())
    return {str(fid): np.array([lon * np.cos(np.radians(lat0)), lat]) * 111.32
            for fid, lon, lat in zip(frame.facility_id, frame.longitude, frame.latitude)}


def select_sites(eligible: gpd.GeoDataFrame) -> list[str]:
    """Deterministic 50-site mix: all eligible health first, schools spread-fill.

    Farthest-point greedy in local km against already-chosen sites; the first
    school is the one nearest the eligible-pool centroid. Ties break on
    facility_id order (argmax over sorted candidates).
    """
    health = eligible[eligible.site_class == 'health_facility'].sort_values('facility_id')
    school = eligible[eligible.site_class == 'school'].sort_values('facility_id')
    xy = _local_km(eligible)
    chosen = health.facility_id.tolist()[:N_SITES]
    if not chosen:
        center = np.mean([xy[s] for s in school.facility_id], axis=0)
        start = school.facility_id.iloc[int(np.argmax(
            [-np.linalg.norm(xy[s] - center) for s in school.facility_id]))]
        chosen.append(start)
    while len(chosen) < N_SITES:
        rest = sorted(set(school.facility_id) - set(chosen))
        if not rest:
            rest = sorted(set(health.facility_id) - set(chosen))
        assert rest, 'site pool exhausted before 50 sites'
        sep = np.array([min(np.linalg.norm(xy[s] - xy[c]) for c in chosen) for s in rest])
        chosen.append(rest[int(sep.argmax())])
    assert len(chosen) == N_SITES
    return sorted(chosen)


def split_hourly(total: int, site_ids: list[str], hour: int) -> dict[str, int]:
    """Deterministic integer split of one hourly total across sites.

    Site order is rotated by hour so largest-remainder +1 increments do not
    always land on the same first sites.
    """
    n = len(site_ids)
    parts = largest_remainder_split(int(total), n)
    rot = site_ids[(hour - 1) % n:] + site_ids[:(hour - 1) % n]
    return dict(zip(rot, parts))


def assign_commune_ids(cluster: gpd.GeoDataFrame, sites: pd.DataFrame) -> list[str]:
    """Commune containing each site point (lowest commune_id on ties)."""
    out = []
    for p in gpd.points_from_xy(sites.longitude, sites.latitude):
        hit = cluster[cluster.geometry.intersects(p)].commune_id.tolist()
        out.append(sorted(hit)[0])
    return out


def main() -> None:
    boundaries, population, facilities, matrix = load_sources()
    cluster = select_cluster(boundaries)
    union = cluster.geometry.union_all()

    pop = population[population.commune_id.isin(cluster.commune_id)].sort_values(
        'commune_id').reset_index(drop=True)
    assert len(pop) == N_COMMUNES

    eligible = eligible_sites(cluster, facilities)
    site_ids = select_sites(eligible)
    sites = eligible.set_index('facility_id').loc[site_ids].reset_index()
    sites = pd.DataFrame(sites.drop(columns='geometry'))
    sites['commune_id'] = assign_commune_ids(cluster, sites)
    assert sites.facility_name.notna().all()
    assert set(sites.commune_id) <= set(pop.commune_id)
    # Locality: every site point lies inside the selected commune union.
    assert gpd.GeoSeries(gpd.points_from_xy(sites.longitude, sites.latitude),
                         crs=4326).intersects(union).all()

    costs = matrix.loc[pop.commune_id, site_ids]

    rng = np.random.default_rng(SEED)
    arrivals = {h: [] for h in range(1, HOURS + 1)}
    for x in pop.children_under_5.astype('int64'):
        a = sample_hourly_arrivals(int(x), rng, HOURS)
        for h in range(1, HOURS + 1):
            arrivals[h].append(a[h - 1])

    balanced, surplus = {}, {}
    for h in range(1, HOURS + 1):
        total = int(sum(arrivals[h]))
        balanced[h] = split_hourly(total, site_ids, h)
        surplus[h] = split_hourly((11 * total + 9) // 10, site_ids, h)  # ceil(1.1*arr)

    rng2 = np.random.default_rng(SEED)
    assert all(sample_hourly_arrivals(int(x), rng2) == a for x, a in zip(
        pop.children_under_5.astype('int64'),
        [[arrivals[h][i] for h in range(1, HOURS + 1)] for i in range(N_COMMUNES)]))

    per_site = {s: sum(balanced[h][s] for h in range(1, HOURS + 1)) for s in site_ids}
    capacity = pd.DataFrame({'facility_id': site_ids,
                            'capacity': [per_site[s] for s in site_ids],
                            'capacity_source': 'synthetic',
                            'capacity_unit': 'modeled children per 4-hour session'})
    long_rows = [{'facility_id': s, 'hour': h,
                  'capacity_balanced': balanced[h][s], 'capacity_surplus': surplus[h][s]}
                 for h in range(1, HOURS + 1) for s in site_ids]
    capacity_hourly = pd.DataFrame(long_rows)

    (OUT / 'arrivals').mkdir(exist_ok=True)
    pop.to_csv(OUT / 'population.csv', index=False, encoding='utf-8-sig')
    sites.to_csv(OUT / 'facilities.csv', index=False, encoding='utf-8-sig')
    capacity.to_csv(OUT / 'sites_capacity.csv', index=False, encoding='utf-8-sig')
    costs.to_csv(OUT / 'distance_matrix.csv', index_label='commune_id', encoding='utf-8-sig')
    for h in range(1, HOURS + 1):
        pd.DataFrame({'commune_id': pop.commune_id, 'arrivals': arrivals[h]}
                     ).to_csv(OUT / f'arrivals/hour_{h}.csv', index=False, encoding='utf-8-sig')
    capacity_hourly.to_csv(OUT / 'capacity_by_hour.csv', index=False, encoding='utf-8-sig')
    cluster.to_file(OUT / 'commune_boundaries.geojson', driver='GeoJSON')

    scenarios = {
        'package': 'temporal_100x50', 'hours': HOURS,
        'scenarios': {
            'baseline': {'mode': 'balanced',
                         'rule': 'per-hour site capacity sums equal per-hour arrivals'},
            'surplus': {'mode': 'surplus',
                        'rule': 'per-hour site capacity sums = ceil(1.1 * per-hour arrivals)'}},
        'lambda_grid': [0, 1, 5],
        'lambda_note': ('optional congestion/latency weight grid for future queue '
                        'experiments; no solver architecture implemented in this package'),
        'routing': ('complete graph by default: every origin commune may send arrivals '
                    'to any candidate site; no travel limit imposed'),
        'service_model': ('capacity_by_hour.csv is hourly SERVICE capacity; vaccine '
                          'stock/supply is a separate quantity, and unused service '
                          'capacity cannot be banked into later hours'),
    }
    (OUT / 'scenarios.json').write_text(
        json.dumps(scenarios, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    src_dir = ROOT / 'data/processed'
    inputs = {f: hashlib.sha256((src_dir / f).read_bytes()).hexdigest() for f in INPUT_FILES}
    outputs = {name: hashlib.sha256((OUT / name).read_bytes()).hexdigest() for name in [
        'population.csv', 'facilities.csv', 'sites_capacity.csv', 'distance_matrix.csv',
        'capacity_by_hour.csv', 'commune_boundaries.geojson', 'scenarios.json',
        'arrivals/hour_1.csv', 'arrivals/hour_2.csv', 'arrivals/hour_3.csv',
        'arrivals/hour_4.csv']}
    metadata = {
        'package': 'temporal_100x50',
        'generated_date': datetime.date.today().isoformat(),
        'seed': SEED,
        'communes': N_COMMUNES, 'sites': N_SITES, 'hours': HOURS,
        'selection': (
            f'100 contiguous peripheral communes grown from the {"/".join(SEED_DISTRICTS)} '
            f'seed by exact polygon-touch BFS-nearest-to-seed-centroid, excluding the '
            f'{len(URBAN_DISTRICTS)} historical central urban districts '
            f'({", ".join(URBAN_DISTRICTS)}); connectivity verified'),
        'districts': cluster.district_name.value_counts().to_dict(),
        'interpretation': ('communes are demand origins SERVED by the 50 candidate '
                           'sites (complete routing graph), not 100 on-site facilities'),
        'arrivals': ('integer children per commune per hour drawn in '
                     '[ceil(0.2x), floor(0.3x)] with x the commune children_under_5, '
                     'sum preserved; constrained sequential sampling over a random '
                     'hour permutation with feasible remainder; small infeasible '
                     'totals rejected'),
        'capacity': ('balanced: per-hour totals split across sites with '
                     'largest_remainder_split over hour-rotated site order; surplus '
                     'per-hour total = ceil(1.1 * arrivals); synthetic, no real '
                     'operational capacity in facilities.csv'),
        'demand': ('children_under_5 is the HRSL 2020 integer proxy estimate '
                   '(Meta HRSL under-5 via HDX), NOT observed vaccine demand'),
        'distance': ('haversine kilometres subset by source IDs from '
                     'data/processed/case1/distance_matrix.csv; NOT road distance, '
                     'no road data forged'),
        'coordinate_caveats': (
            'GADM 4.1 historical commune boundaries differ from current Hanoi '
            'administrative units; facility coordinates are OSM polygon centers '
            '(school entrances unverified); site status is candidate, unverified'),
        'site_classes': sites.site_class.value_counts().to_dict(),
        'total_children': int(pop.children_under_5.sum()),
        'inputs': inputs, 'outputs': outputs,
    }
    (OUT / 'metadata.json').write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: metadata[k] for k in
                      ['package', 'generated_date', 'seed', 'communes', 'sites', 'hours',
                       'districts', 'site_classes', 'total_children']},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
