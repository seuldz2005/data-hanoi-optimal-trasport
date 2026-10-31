"""Validate the portable Case 1 test dataset: python data-test/check.py."""
from pathlib import Path
import numpy as np
import pandas as pd

p = Path(__file__).resolve().parent
pop = pd.read_csv(p/'population.csv')
sites = pd.read_csv(p/'facilities.csv', dtype={'facility_id': str})
capacity = pd.read_csv(p/'sites_capacity.csv', dtype={'facility_id': str}).set_index('facility_id').capacity
matrix = pd.read_csv(p/'distance_matrix.csv', index_col=0)
allocation = pd.read_csv(p/'allocation_lp.csv', dtype={'facility_id': str})
assert len(pop) == 20 and len(sites) == 30
assert pop.commune_id.is_unique and sites.facility_id.is_unique
assert matrix.index.tolist() == pop.commune_id.tolist()
assert matrix.columns.tolist() == sites.facility_id.tolist() == capacity.index.tolist()
assert np.isfinite(matrix.to_numpy()).all() and (matrix.to_numpy() >= 0).all()
assert sites.latitude.between(-90, 90).all() and sites.longitude.between(-180, 180).all()
assert set(sites.commune_id) <= set(pop.commune_id)
assert sites.capacity.isna().all()
assert set(sites.vaccination_site_status) == {'candidate'}
assert pop.children_under_5.sum() == capacity.sum() == allocation.children_assigned.sum() == 19769
assert (allocation.children_assigned > 0).all() and (allocation.children_assigned % 1 == 0).all()
np.testing.assert_array_equal(allocation.groupby('commune_id').children_assigned.sum().reindex(pop.commune_id), pop.children_under_5)
np.testing.assert_array_equal(allocation.groupby('facility_id').children_assigned.sum().reindex(capacity.index), capacity)
for row in allocation.itertuples():
    assert row.distance_km == matrix.loc[row.commune_id, row.facility_id]
print('PASS: 20 communes, 30 candidate sites, 20x30 distances, 19769 modeled children conserved.')
