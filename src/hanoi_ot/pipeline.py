"""End-to-end pipeline orchestration.

Stages: download -> boundaries -> population -> facilities (health +
school candidates) -> distances -> validation -> outputs (incl.
dataset_metadata.json).

Each stage is independently callable; ``run`` executes all with real
data, ``run_synthetic`` executes with the tiny synthetic fixture, and
``run_from_existing`` rebuilds the combined candidate-site outputs from
the already-committed CSVs (no downloads, no population rerun).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd

from . import __version__
from .boundaries import geometry_union, hanoi_communes, save_boundaries
from .config import REPO_ROOT, data_dir, get_logger, load_config, output_path
from .distances import build_distance_matrix, save_distance_matrix
from .download import download_source, sha256
from .facilities import (
    build_facilities,
    combine_candidate_sites,
    prepare_school_candidates,
    save_facilities,
)
from .population import build_population, save_population
from .validation import validate_outputs

log = get_logger("pipeline")

DEFAULT_OSRM_URL = "http://127.0.0.1:5000"


class PipelineError(RuntimeError):
    """Raised when a pipeline stage cannot complete."""


def _stage_download() -> dict[str, Path]:
    """Download all configured sources; return their extract directories."""
    dirs = {}
    for key in (
        "admin_boundaries", "population_under5", "health_facilities", "education_facilities",
    ):
        dirs[key] = download_source(key)
    return dirs


def _site_summary(facilities: pd.DataFrame, summary: dict[str, Any]) -> dict[str, Any]:
    """Add per-class candidate-site counts to a validation summary."""
    counts = facilities["site_class"].value_counts()
    summary["n_health_facilities"] = int(counts.get("health_facility", 0))
    summary["n_school_candidates"] = int(counts.get("school", 0))
    return summary


def _refresh_road_matrix(
    population: pd.DataFrame, facilities: pd.DataFrame, osrm_url: str
) -> str:
    """Rebuild the OSRM road matrix, or explicitly invalidate the stale one.

    Road distances are never fabricated: when local OSRM is unreachable
    (or routing fails) the stale ``road_distance_matrix.csv`` — which no
    longer matches the expanded candidate sites — is removed and the
    unavailability is reported for metadata.

    Args:
        population: Population frame (origins).
        facilities: Combined candidate-site frame (destinations).
        osrm_url: Local OSRM base URL.

    Returns:
        Human-readable road-distance status string for the metadata.
    """
    from .road_routes import RoadRoutingError, build_road_distance_matrix, osrm_available

    road_path = output_path("road_distance_matrix")
    if not osrm_available(osrm_url):
        if road_path.exists():
            road_path.unlink()
            log.warning(
                "Local OSRM unreachable at %s: removed stale road matrix %s "
                "(it no longer matches the combined candidate sites)",
                osrm_url, road_path,
            )
        return (
            "unavailable: local OSRM not reachable; the stale matrix "
            f"(built for the previous 320-site dataset) was removed from "
            "data/processed/case1/. Restart OSRM (scripts/start_osrm.sh) and "
            "rerun scripts/run_pipeline.py --from-existing to rebuild it for "
            "the combined sites. Road distances are never substituted with "
            "straight-line values."
        )
    try:
        road = build_road_distance_matrix(population, facilities, osrm_url)
    except RoadRoutingError as e:
        if road_path.exists():
            road_path.unlink()
        return f"unavailable: OSRM road routing failed ({e}); stale matrix removed"
    road.to_csv(road_path, index=True, index_label="commune_id")
    log.info("Road matrix %dx%d -> %s", *road.shape, road_path)
    return f"available: rebuilt {road.shape[0]}x{road.shape[1]} matrix from local OSRM"


def _write_metadata(
    summary: dict[str, Any],
    sources: dict[str, Any],
    raw_files: dict[str, Path],
    extra: dict[str, Any] | None = None,
) -> Path:
    """Write dataset_metadata.json describing every output.

    Args:
        summary: Validation summary (counts/totals).
        sources: Config ``sources`` block (or a previously written
            metadata ``sources`` block, whose sha256 checksums are
            preserved verbatim when ``raw_files`` is empty).
        raw_files: Raw archive path per source key (for checksums).
        extra: Additional top-level metadata keys (e.g. road status).

    Returns:
        Path to the metadata JSON.
    """
    cfg = load_config()
    meta = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pipeline_version": __version__,
        "study_area": cfg["project"]["study_area"],
        "case": (
            "Case 1 - children under five -> vaccination candidate sites "
            "(health facilities + school candidates)"
        ),
        "outputs": {
            "boundaries": cfg["paths"]["outputs"]["boundaries"],
            "population": cfg["paths"]["outputs"]["population"],
            "facilities": cfg["paths"]["outputs"]["facilities"],
            "distance_matrix": cfg["paths"]["outputs"]["distance_matrix"],
        },
        "summary": summary,
        "sources": {
            k: {
                "dataset": v["dataset"],
                "provider": v["provider"],
                "license": v["license"],
                "file": v["file"],
                # Re-hashed from raw files when available; otherwise a
                # checksum carried over from a previously written metadata
                # (sources may be the old metadata block) is preserved.
                **(
                    {"sha256": sha256(raw_files[k])} if k in raw_files
                    else ({"sha256": v["sha256"]} if "sha256" in v else {})
                ),
            }
            for k, v in sources.items()
        },
        "population_unit": cfg["population"]["unit"],
        "population_year": cfg["sources"]["population_under5"]["year"],
        "distance_method": cfg["distance"]["method"],
        "distance_unit": cfg["distance"]["unit"],
        "candidate_sites_note": (
            "Health facilities AND schools are CANDIDATE vaccination sites "
            "only. No site has been verified as an actual vaccination "
            "location. School ids are namespaced 'school_<osm_id>'; health "
            "facility ids are unchanged OSM ids. REAL capacities are missing "
            "for both classes (blank capacity column)."
        ),
        "balanced_ot_note": (
            "Balanced optimal transport requires sum(x) == sum(y). "
            "Facility capacities are MISSING (OSM has no capacity data), so "
            "this dataset is NOT yet ready for real-world capacity-"
            "constrained optimization. Use synthetic capacities (labeled) "
            "for method development only."
        ),
        "capacity_status": (
            "missing - no verified capacity source integrated yet"
            if not summary.get("capacity_available")
            else "present"
        ),
    }
    meta.update(extra or {})
    out = output_path("metadata")
    out.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log.info("Metadata -> %s", out)
    return out


def run(force_download: bool = False) -> dict[str, Any]:
    """Run the full real-data pipeline.

    Args:
        force_download: Re-download sources even if present.

    Returns:
        Validation summary dict.

    Raises:
        PipelineError: If any stage fails (with cause chained).
    """
    cfg = load_config()
    try:
        dirs = _stage_download()
        raw_files = {
            k: data_dir("raw") / k / cfg["sources"][k]["file"]
            for k in (
                "admin_boundaries", "population_under5",
                "health_facilities", "education_facilities",
            )
        }
        log.info("Stage: boundaries")
        communes = hanoi_communes(dirs["admin_boundaries"])
        save_boundaries(communes)
        hanoi_geom = geometry_union(communes)

        log.info("Stage: population")
        population = build_population(dirs["population_under5"], communes)
        save_population(population)

        log.info("Stage: facilities (health + school candidates)")
        health = build_facilities(dirs["health_facilities"], hanoi_geom)
        schools = build_facilities(dirs["education_facilities"], hanoi_geom)
        schools["source"] = "HOT OSM education facilities export (ODbL) via HDX"
        facilities = combine_candidate_sites(
            health, prepare_school_candidates(schools)
        )
        save_facilities(facilities)

        log.info("Stage: distances")
        matrix = build_distance_matrix(population, facilities)
        save_distance_matrix(matrix)

        log.info("Stage: validation")
        summary = validate_outputs(
            population, facilities, matrix, communes,
            expected_year=cfg["sources"]["population_under5"]["year"],
            max_km=cfg["validation"]["max_haversine_distance_km"],
        )
        _write_metadata(
            _site_summary(facilities, summary), cfg["sources"], raw_files,
            extra={"road_distance_status": _refresh_road_matrix(
                population, facilities, DEFAULT_OSRM_URL
            )},
        )
        log.info("Pipeline complete.")
        return summary
    except Exception as e:
        raise PipelineError(f"Pipeline failed: {e}") from e


def run_from_existing(osrm_url: str = DEFAULT_OSRM_URL) -> dict[str, Any]:
    """Rebuild the combined Case 1 candidate-site outputs from existing CSVs.

    No downloads and no population rerun: the committed ``population.csv``
    (584 communes, whole-children demand) and the Case 2 education export
    (332 schools) are reused. Health facility rows are taken from the
    current ``facilities.csv`` (idempotent: a combined file is split back
    into its health subset first). The Haversine matrix is recomputed for
    the combined sites, outputs are validated, metadata is refreshed
    (preserving source sha256 provenance), and the OSRM road matrix is
    rebuilt or explicitly invalidated (see ``_refresh_road_matrix``).

    Args:
        osrm_url: Local OSRM base URL used for the road-matrix decision.

    Returns:
        Validation summary dict.

    Raises:
        PipelineError: If any stage fails (with cause chained).
    """
    cfg = load_config()
    meta_path = output_path("metadata")
    try:
        population = pd.read_csv(output_path("population"))
        demand = pd.to_numeric(population["children_under_5"], errors="raise")
        if not ((demand % 1) == 0).all():
            raise PipelineError(
                "population.csv carries fractional demand: run "
                "scripts/export_integer_population.py first (whole children only)"
            )

        fac_path = output_path("facilities")
        existing = pd.read_csv(fac_path, dtype={"facility_id": str})
        if {"site_class", "vaccination_site_status"} <= set(existing.columns):
            health = existing[existing["site_class"] == "health_facility"].copy()
        else:
            health = existing.copy()

        schools_csv = data_dir("processed") / cfg["paths"]["school_candidates_input"]
        if not schools_csv.exists():
            raise PipelineError(
                f"School export missing: {schools_csv} "
                "(built by scripts/run_scenario2_data.py)"
            )
        schools = prepare_school_candidates(
            pd.read_csv(schools_csv, dtype={"facility_id": str})
        )
        facilities = combine_candidate_sites(health, schools)

        log.info("Stage: boundaries (existing)")
        communes = gpd.read_file(
            data_dir("processed") / cfg["paths"]["outputs"]["boundaries"]
        )

        log.info("Stage: distances (%d communes x %d candidate sites)",
                 len(population), len(facilities))
        matrix = build_distance_matrix(population, facilities)

        log.info("Stage: validation")
        summary = validate_outputs(
            population, facilities, matrix, communes,
            expected_year=cfg["sources"]["population_under5"]["year"],
            max_km=cfg["validation"]["max_haversine_distance_km"],
        )

        save_facilities(facilities)
        save_distance_matrix(matrix)

        log.info("Stage: road matrix")
        road_status = _refresh_road_matrix(population, facilities, osrm_url)

        summary = _site_summary(facilities, summary)
        old_meta = {}
        if meta_path.exists():
            try:
                old_meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                old_meta = {}
        old_summary = old_meta.get("summary", {})
        raw_total = old_summary.get(
            "estimated_raster_total_children_under_5",
            old_summary.get("total_children_under_5"),
        )
        if raw_total is not None and float(raw_total) != float(
            summary["total_children_under_5"]
        ):
            summary["estimated_raster_total_children_under_5"] = float(raw_total)
        sources = old_meta.get("sources") or cfg["sources"]
        _write_metadata(
            summary, sources, {}, extra={"road_distance_status": road_status}
        )
        log.info("From-existing rebuild complete.")
        return summary
    except Exception as e:
        raise PipelineError(f"From-existing rebuild failed: {e}") from e


def run_synthetic(fixture_dir: Path | None = None) -> dict[str, Any]:
    """Run the pipeline stages against the tiny synthetic fixture.

    Loads synthetic communes/facilities from ``tests/fixtures``, builds
    the distance matrix, validates, and writes outputs into
    ``data/processed`` with a ``synthetic_`` prefix avoided — instead the
    metadata records ``synthetic: true``.

    Args:
        fixture_dir: Directory with ``synthetic_boundaries.geojson`` and
            ``synthetic_facilities.csv``. Defaults to repo tests/fixtures.

    Returns:
        Validation summary dict.

    Raises:
        PipelineError: If fixture files are missing.
    """
    fdir = fixture_dir or (REPO_ROOT / "tests" / "fixtures")
    bnd_path = fdir / "synthetic_boundaries.geojson"
    fac_path = fdir / "synthetic_facilities.csv"
    if not bnd_path.exists() or not fac_path.exists():
        raise PipelineError(f"Synthetic fixtures missing in {fdir}")

    communes = gpd.read_file(bnd_path)
    facilities = pd.read_csv(fac_path)
    facilities["capacity_source"] = "SYNTHETIC (testing only, not real data)"

    population = pd.DataFrame(
        {
            "commune_id": communes["commune_id"],
            "commune_name": communes["commune_name"],
            "children_under_5": communes["children_under_5"].astype(float),
            "centroid_lat": communes["centroid_lat"],
            "centroid_lon": communes["centroid_lon"],
            "data_year": 2020,
            "source": "SYNTHETIC fixture (testing only)",
        }
    )
    matrix = build_distance_matrix(population, facilities)
    summary = validate_outputs(
        population, facilities, matrix, communes,
        expected_year=2020,
        max_km=10_000.0,  # synthetic coords may be far apart
    )
    summary["synthetic"] = True
    log.info("Synthetic run complete: %s", summary)
    return summary
