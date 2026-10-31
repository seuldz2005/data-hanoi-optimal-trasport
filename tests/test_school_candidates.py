"""Candidate-site validation and shipped model alignment."""
import numpy as np
import pandas as pd
import pytest
from hanoi_ot.facilities import prepare_school_candidates, FacilityError


def test_school_ids_idempotent_and_capacity_unknown():
    schools = pd.read_csv('data/processed/case2/scenario2_education_facilities.csv')
    once = prepare_school_candidates(schools)
    pd.testing.assert_frame_equal(once, prepare_school_candidates(once))
    assert once.facility_id.is_unique
    assert once.capacity.isna().all()
    invalid = schools.iloc[:1].copy()
    invalid['latitude'] = 'invalid'
    with pytest.raises(FacilityError):
        prepare_school_candidates(invalid)
    invalid = schools.iloc[:1].copy()
    invalid['facility_id'] = None
    with pytest.raises(FacilityError):
        prepare_school_candidates(invalid)


def test_combined_model_alignment_and_conservation():
    root = 'data/processed/case1/'
    sites = pd.read_csv(root + 'facilities.csv', dtype={'facility_id': str})
    pop = pd.read_csv(root + 'population.csv')
    matrix = pd.read_csv(root + 'distance_matrix.csv', index_col=0)
    capacity = pd.read_csv(root + 'sites_capacity.csv', dtype={'facility_id': str}).set_index('facility_id').capacity
    allocation = pd.read_csv(root + 'allocation_demo.csv', dtype={'facility_id': str})
    assert sites.facility_id.is_unique
    assert set(sites.vaccination_site_status) == {'candidate'}
    assert sites.capacity.isna().all()
    schools = pd.read_csv('data/processed/case2/scenario2_education_facilities.csv', dtype={'facility_id': str})
    assert (sites.site_class == 'school').sum() == len(schools)
    assert sites.loc[sites.site_class == 'school', 'facility_id'].tolist() == ('school_' + schools.facility_id).tolist()
    assert matrix.columns.tolist() == sites.facility_id.tolist() == capacity.index.tolist()
    assert matrix.index.tolist() == pop.commune_id.tolist()
    assert matrix.shape == (len(pop), len(sites))
    assert np.isfinite(matrix.to_numpy()).all()
    assert (matrix.to_numpy() >= 0).all()
    demand = pop.set_index('commune_id').children_under_5
    assert demand.sum() == capacity.sum() == allocation.children_assigned.sum()
    np.testing.assert_allclose(allocation.groupby('commune_id').children_assigned.sum().reindex(demand.index), demand)
    np.testing.assert_allclose(allocation.groupby('facility_id').children_assigned.sum().reindex(capacity.index), capacity)
