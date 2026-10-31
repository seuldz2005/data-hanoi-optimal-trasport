"""Rebuild a 20-commune / 30-site Case 1 experiment from repository data."""
from pathlib import Path
import hashlib
import json
import sys

import geopandas as gpd
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))
from hanoi_ot.capacity import largest_remainder_split
from hanoi_ot.benchmarks import exact_lp, result_dict


def main():
    source = ROOT / 'data/processed'
    boundaries = gpd.read_file(source / 'hanoi_boundaries.geojson')
    boundaries = boundaries[boundaries.district_name == 'HoàiĐức'].sort_values('commune_id')
    population = pd.read_csv(source / 'case1/population.csv')
    population = population.set_index('commune_id').loc[boundaries.commune_id].reset_index()
    sites = pd.read_csv(source / 'case1/facilities.csv', dtype={'facility_id': str})
    points = gpd.GeoDataFrame(sites, geometry=gpd.points_from_xy(sites.longitude, sites.latitude), crs=4326)
    eligible = points.intersects(boundaries.geometry.union_all()) & sites.facility_name.notna()
    # ponytail: only named health stations/clinics, not pharmacies; eligibility still unverified.
    health = sites.site_class.eq('health_facility') & (
        sites.facility_name.fillna('').str.contains('trạm y tế', case=False) | sites.facility_type.eq('clinic'))
    candidates = sites[eligible & (health | sites.site_class.eq('school'))].copy()
    candidates = candidates.sort_values('facility_id').set_index('facility_id')
    distance_path = source / 'case1/distance_matrix.csv'
    costs = pd.read_csv(distance_path, index_col=0).loc[population.commune_id, candidates.index]
    chosen = candidates.index[candidates.site_class.eq('health_facility')].tolist()
    # Cover commune centroids first, then fill with farthest-separated school candidates.
    for commune in costs.index:
        nearest = costs.loc[commune].idxmin()
        if nearest not in chosen:
            chosen.append(nearest)
    while len(chosen) < 30:
        remaining = candidates.loc[~candidates.index.isin(chosen)]
        a = remaining[['latitude', 'longitude']].to_numpy()
        b = candidates.loc[chosen, ['latitude', 'longitude']].to_numpy()
        separation = ((a[:, None] - b[None, :]) ** 2).sum(axis=2).min(axis=1)
        chosen.append(remaining.index[np.argmax(separation)])
    chosen = sorted(chosen[:30])
    sites = candidates.loc[chosen].reset_index()
    sites['commune_id'] = [next(r.commune_id for r in boundaries.itertuples() if r.geometry.intersects(p))
                           for p in gpd.points_from_xy(sites.longitude, sites.latitude)]
    sites = pd.DataFrame(sites)
    matrix = costs.loc[:, chosen]
    demand = population.children_under_5.to_numpy()
    assert len(population) == 20 and len(sites) == 30
    capacity = pd.DataFrame({'facility_id': chosen,
                            'capacity': largest_remainder_split(int(demand.sum()), len(chosen)),
                            'capacity_source': 'synthetic', 'capacity_unit': 'modeled children; no time period'})
    result, plan = exact_lp(demand, capacity.capacity.to_numpy(), matrix.to_numpy())
    if result.status != 'success':
        raise RuntimeError(result.status)
    assigned = plan * demand.sum()
    np.testing.assert_allclose(assigned.sum(axis=1), demand, atol=1e-6)
    np.testing.assert_allclose(assigned.sum(axis=0), capacity.capacity, atol=1e-6)
    # Balanced integer marginals have an integral optimum; check before rounding float dust.
    np.testing.assert_allclose(assigned, assigned.round(), atol=1e-6)
    assigned = assigned.round().astype('int64')
    rows = [(population.commune_id.iloc[i], chosen[j], int(assigned[i,j]), float(matrix.iloc[i,j]))
            for i,j in zip(*np.where(assigned > 0))]
    allocation = pd.DataFrame(rows, columns=['commune_id','facility_id','children_assigned','distance_km'])
    for name, frame in [('population',population), ('facilities',sites), ('sites_capacity',capacity), ('allocation_lp',allocation)]:
        frame.to_csv(OUT / f'{name}.csv', index=False, encoding='utf-8-sig')
    matrix.to_csv(OUT / 'distance_matrix.csv', index_label='commune_id', encoding='utf-8-sig')
    boundaries.to_file(OUT / 'commune_boundaries.geojson', driver='GeoJSON')
    files = ['case1/population.csv','case1/facilities.csv','case1/distance_matrix.csv','hanoi_boundaries.geojson']
    metadata = dict(district='Hoài Đức (GADM 4.1 historical boundary)', communes=len(population), sites=len(sites),
                    site_classes=sites.site_class.value_counts().to_dict(), total_modeled_children=int(demand.sum()),
                    distance='haversine kilometres, not road distance', capacity='synthetic balanced integers, no operational time period',
                    demand='HRSL 2020 estimated under-5 population; not observed vaccination demand',
                    candidate_status='unverified vaccination sites; school polygon centers may not be entrances',
                    selection='All 20 historical Hoai Duc communes; 2 named health stations plus 28 schools. Nearest site per centroid, then spatial spread. Original source IDs preserved.',
                    solver=result_dict(result), mean_distance_km=float((assigned * matrix.to_numpy()).sum()/demand.sum()),
                    total_child_km=float((assigned * matrix.to_numpy()).sum()),
                    inputs={f:hashlib.sha256((source/f).read_bytes()).hexdigest() for f in files})
    (OUT/'metadata.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(metadata,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
