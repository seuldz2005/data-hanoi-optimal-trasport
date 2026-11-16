"""Unit tests for the Revised Discrete-Cell CCDV algorithm (Cui et al., 2021 & Dung's spec)."""
from __future__ import annotations

from shapely.geometry import Point, box

from hanoi_ot.ccdv_cui2021 import (
    CommunityUnit,
    run_ccdv_cui2021,
    two_school_voronoi_cells,
)


def test_two_school_voronoi_bisector():
    """When 2 schools remain (Step 6), perpendicular bisector splits the domain accurately."""
    domain = box(0, 0, 1000, 1000)
    cells = two_school_voronoi_cells("S1", Point(250, 500), "S2", Point(750, 500), domain)
    assert abs(cells["S1"].area - 500_000.0) < 1.0
    assert abs(cells["S2"].area - 500_000.0) < 1.0
    assert cells["S1"].contains(Point(250, 500))
    assert cells["S2"].contains(Point(750, 500))


def test_left_to_right_school_and_cell_accumulation_atomic():
    """Schools and cells are processed Left-to-Right (x asc, y asc) and converge within +-5%."""
    # 10x10 grid of 100m x 100m cells in a 1000m x 1000m square, each with 30 students (total 3000)
    units = []
    for ix in range(10):
        for iy in range(10):
            poly = box(ix * 100, iy * 100, (ix + 1) * 100, (iy + 1) * 100)
            units.append(
                CommunityUnit(
                    unit_id=f"c_{ix}_{iy}",
                    geometry=poly,
                    centroid_x=poly.centroid.x,
                    centroid_y=poly.centroid.y,
                    population=30.0,
                )
            )
    study_area = box(0, 0, 1000, 1000)
    # Place S_left in a dense left region so it has to shrink (leave right-side cells for S_mid)
    schools = {
        "S_right": {"point": Point(850, 500), "capacity": 900.0},
        "S_left": {"point": Point(250, 500), "capacity": 900.0},
        "S_mid": {"point": Point(650, 500), "capacity": 1200.0},
    }
    zones, stats, leftover, unassigned_pop = run_ccdv_cui2021(
        schools, units, study_area, eps=0.05, assignment_mode="atomic"
    )
    assert stats["S_left"]["processing_rank"] == 1
    assert stats["S_mid"]["processing_rank"] == 2
    assert stats["S_right"]["processing_rank"] == 3
    assert stats["S_left"]["within_5pct"] is True
    assert stats["S_mid"]["within_5pct"] is True
    assert stats["S_right"]["within_5pct"] is True
    assert abs(unassigned_pop) < 1e-6
    assert len(leftover) == 0


def test_step4_expansion_100m_plus_10m():
    """When initial Voronoi cell has < 0.95*q_j students, Step 4 expands by 100m + k*10m."""
    units = []
    for ix in range(10):
        poly = box(ix * 50, 0, (ix + 1) * 50, 200)
        units.append(
            CommunityUnit(
                unit_id=f"u_{ix}",
                geometry=poly,
                centroid_x=poly.centroid.x,
                centroid_y=poly.centroid.y,
                population=100.0,
            )
        )
    study_area = box(0, 0, 500, 200)
    # S1 at x=25 is very close to S2 at x=125, so S1's initial Voronoi cell only covers x in [0, 75]
    # (only unit u_0 has centroid at x=25 inside [0, 75], giving 100 students < capacity 400).
    # S1 must expand into x > 75 via 100m + 10m steps to reach 400 students (4 units).
    schools = {
        "S1": {"point": Point(25, 100), "capacity": 400.0},
        "S2": {"point": Point(125, 100), "capacity": 300.0},
        "S3": {"point": Point(400, 100), "capacity": 300.0},
    }
    zones, stats, leftover, unassigned_pop = run_ccdv_cui2021(
        schools, units, study_area, eps=0.05, assignment_mode="atomic"
    )
    assert stats["S1"]["allocated_students"] == 400.0
    assert stats["S1"]["expand_radius_m"] >= 100.0
    assert stats["S2"]["allocated_students"] == 300.0
    assert stats["S3"]["allocated_students"] == 300.0
    assert abs(unassigned_pop) < 1e-6


def test_coarse_cell_fractional_last_cuts_along_x():
    """When a single cell is larger than capacity, fractional_last slices it from left to right."""
    units = [
        CommunityUnit("big_1", box(0, 0, 500, 500), 250.0, 250.0, 2000.0),
        CommunityUnit("big_2", box(500, 0, 1000, 500), 750.0, 250.0, 2000.0),
    ]
    study_area = box(0, 0, 1000, 500)
    schools = {
        "S1": {"point": Point(200, 250), "capacity": 1000.0},
        "S2": {"point": Point(500, 250), "capacity": 1500.0},
        "S3": {"point": Point(800, 250), "capacity": 1500.0},
    }
    zones, stats, leftover, unassigned_pop = run_ccdv_cui2021(
        schools, units, study_area, eps=0.05, assignment_mode="fractional_last"
    )
    assert stats["S1"]["within_5pct"] is True
    assert stats["S2"]["within_5pct"] is True
    assert stats["S3"]["within_5pct"] is True
    assert abs(unassigned_pop) < 1.0


def test_build_grid_units_conserves_population_and_bounds_cell_pop():
    """build_grid_units conserves total population and caps per-cell population when max_cell_pop is set."""
    import geopandas as gpd
    from hanoi_ot.ccdv_cui2021 import build_grid_units

    gdf = gpd.GeoDataFrame(
        {"commune_id": ["c_dense", "c_sparse"], "children_5_14": [2000, 120]},
        geometry=[box(0, 0, 500, 500), box(500, 0, 1500, 1000)],
        crs=32648,
    )
    units = build_grid_units(gdf, cell_size_m=500.0, max_cell_pop=50.0)
    total_pop = sum(u.population for u in units)
    assert abs(total_pop - 2120.0) < 1e-6
    assert max(u.population for u in units) <= 50.0 + 1e-6

