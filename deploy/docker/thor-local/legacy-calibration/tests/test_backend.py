# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest

LANE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "thor_legacy_calibration", LANE / "backend.py"
)
assert SPEC and SPEC.loader
backend = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backend)


def project(project_type: str = "gis") -> dict:
    image = [
        [0, 0],
        [100, 0],
        [100, 100],
        [0, 100],
        [50, 0],
        [100, 50],
        [50, 100],
        [0, 50],
    ]
    correspondences = [
        {"image": point, "world": [point[0] + 10, point[1] - 5]} for point in image
    ]
    value = {
        "schema_version": 1,
        "project_id": f"clean-{project_type}",
        "project_type": project_type,
        "provider": "local_coordinate_plane",
        "calibration_type": (
            "geo"
            if project_type in {"gis", "geo"}
            else (
                "cartesian"
                if project_type in {"manual", "cartesian", "mtmc"}
                else "image"
            )
        ),
        "osm_url": "",
        "road_city": "Operator City",
        "road_intersection": "Operator Intersection",
        "camera": {
            "id": "camera-01",
            "image_size": [1920, 1080],
            "correspondences": correspondences,
            "origin": {"lat": 0, "lng": 0},
            "geo_location": {"lat": 37.39, "lng": -121.95},
            "coordinates": {"x": 0, "y": 0},
            "scale_factor": 1,
            "attributes": [{"name": "source", "value": "operator-custom"}],
            "place": [{"name": "city", "value": "Operator City"}],
        },
        "rois": [
            {
                "id": "roi-01",
                "points": [
                    [0, 0],
                    [25, 0],
                    [50, 0],
                    [50, 25],
                    [50, 50],
                    [25, 50],
                    [0, 50],
                    [0, 25],
                ],
            }
        ],
        "tripwires": [
            {
                "id": "tripwire-01",
                "points": [[10, 10], [40, 40]],
                "direction": [[20, 10], [20, 40]],
            }
        ],
        "road_links": (
            [
                {
                    "id": "road-01",
                    "direction": "E",
                    "points": [
                        {"lat": 37.39, "lon": -121.96, "alt": 0},
                        {"lat": 37.39, "lon": -121.95, "alt": 0},
                        {"lat": 37.39, "lon": -121.94, "alt": 0},
                    ],
                }
            ]
            if project_type in {"gis", "geo"}
            else []
        ),
    }
    if project_type == "mtmc":
        second = deepcopy(value["camera"])
        second["id"] = "camera-02"
        value["cameras"] = [value.pop("camera"), second]
    return value


def test_gis_project_solves_and_exports_with_provider_free_identity(
    tmp_path: Path,
) -> None:
    result = backend.export_project(project(), tmp_path)
    calibration = result["outputs"]["calibration.json"]
    road = result["outputs"]["road-network.json"]
    assert calibration["calibrationType"] == "geo"
    attributes = {
        item["name"]: item["value"] for item in calibration["sensors"][0]["attributes"]
    }
    assert attributes["providerAlternateIdentity"] == "thor-clean-room-provider-free-v1"
    assert calibration["sensors"][0]["homography"] == [
        [1.0, 0.0, 10.0],
        [0.0, 1.0, -5.0],
        [0.0, 0.0, 1.0],
    ]
    assert float(attributes["reprojectionRms"]) <= 1e-12
    assert len(calibration["sensors"][0]["rois"][0]["roiCoordinates"]) == 8
    assert road == {
        "city": "Operator City",
        "docType": "roadNetwork",
        "intersections": [
            {
                "name": "Operator Intersection",
                "segments": [
                    {
                        "id": "road-01",
                        "direction": "E",
                        "start": {"lat": 37.39, "lon": -121.96, "alt": 0.0},
                        "end": {"lat": 37.39, "lon": -121.94, "alt": 0.0},
                        "points": [
                            {"lat": 37.39, "lon": -121.96, "alt": 0.0},
                            {"lat": 37.39, "lon": -121.95, "alt": 0.0},
                            {"lat": 37.39, "lon": -121.94, "alt": 0.0},
                        ],
                    }
                ],
            }
        ],
    }
    assert Path(result["project_dir"]).parent == tmp_path


def test_manual_project_exports_cartesian_without_road_links(tmp_path: Path) -> None:
    result = backend.export_project(project("manual"), tmp_path)
    assert result["outputs"]["calibration.json"]["calibrationType"] == "cartesian"
    assert result["outputs"]["road-network.json"]["intersections"][0]["segments"] == []


@pytest.mark.parametrize(
    ("project_type", "exported_type"),
    [
        ("cartesian", "cartesian"),
        ("image", "image"),
        ("geo", "geo"),
    ],
)
def test_official_single_camera_project_types_export(
    project_type: str, exported_type: str, tmp_path: Path
) -> None:
    result = backend.export_project(project(project_type), tmp_path)

    assert result["outputs"]["calibration.json"]["calibrationType"] == exported_type
    assert len(result["outputs"]["calibration.json"]["sensors"]) == 1


def test_mtmc_project_requires_and_exports_distinct_cameras(tmp_path: Path) -> None:
    value = project("mtmc")
    result = backend.export_project(value, tmp_path)

    calibration = result["outputs"]["calibration.json"]
    assert calibration["calibrationType"] == "cartesian"
    assert [sensor["id"] for sensor in calibration["sensors"]] == [
        "camera-01",
        "camera-02",
    ]

    duplicate = project("mtmc")
    duplicate["cameras"][1]["id"] = "camera-01"
    with pytest.raises(backend.CalibrationError, match="camera ids must be unique"):
        backend.compile_project(duplicate)

    too_small = project("mtmc")
    too_small["cameras"] = too_small["cameras"][:1]
    with pytest.raises(backend.CalibrationError, match="need 2..16 cameras"):
        backend.compile_project(too_small)


def test_export_is_deterministic_and_refuses_overwrite(tmp_path: Path) -> None:
    value = project()
    first = backend.export_project(value, tmp_path / "first")
    second = backend.export_project(value, tmp_path / "second")
    for name in ("calibration.json", "road-network.json"):
        assert (Path(first["project_dir"]) / name).read_bytes() == (
            Path(second["project_dir"]) / name
        ).read_bytes()
    with pytest.raises(backend.CalibrationError, match="overwrite is forbidden"):
        backend.export_project(value, tmp_path / "first")


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.__setitem__("provider", "google_maps"), "provider-free"),
        (
            lambda value: value["rois"][0].__setitem__(
                "points", value["rois"][0]["points"][:7]
            ),
            "needs 8",
        ),
        (
            lambda value: value["camera"].__setitem__(
                "correspondences", value["camera"]["correspondences"][:3]
            ),
            "needs 4",
        ),
        (
            lambda value: value["camera"]["correspondences"].__setitem__(
                0, {"image": [0, 0], "world": [0, 0]}
            ),
            "reprojection error",
        ),
        (
            lambda value: value.__setitem__("project_id", "../escape"),
            "plain identifier",
        ),
        (
            lambda value: value.__setitem__("project_type", "unknown"),
            "must be cartesian, image, geo, or mtmc",
        ),
        (
            lambda value: value.__setitem__("warehouse_sample_bundle", True),
            "unknown or missing",
        ),
        (
            lambda value: value["road_links"][0].__setitem__("direction", "NE"),
            "must be E, W, N, or S",
        ),
    ],
)
def test_unsafe_incomplete_and_non_provider_free_projects_fail_closed(
    mutate, message: str
) -> None:
    value = project()
    mutate(value)
    with pytest.raises(backend.CalibrationError, match=message):
        backend.compile_project(value)


def test_degenerate_correspondences_fail_closed() -> None:
    value = project()
    value["camera"]["correspondences"] = [
        {"image": [index, index], "world": [index, index]} for index in range(4)
    ]
    with pytest.raises(backend.CalibrationError, match="unique homography"):
        backend.compile_project(value)


def test_strict_loader_rejects_duplicates_nonfinite_and_symlinks(
    tmp_path: Path,
) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schema_version":1,"schema_version":1}')
    with pytest.raises(backend.CalibrationError, match="duplicate JSON key"):
        backend.load_project(duplicate)
    nonfinite = tmp_path / "nonfinite.json"
    nonfinite.write_text('{"value":NaN}')
    with pytest.raises(backend.CalibrationError, match="non-finite"):
        backend.load_project(nonfinite)
    link = tmp_path / "link.json"
    link.symlink_to(duplicate)
    with pytest.raises(backend.CalibrationError, match="non-symlink"):
        backend.load_project(link)


def test_contract_is_exact_and_does_not_claim_runtime_or_full_parity() -> None:
    contract = json.loads((LANE / "contract.json").read_text())
    assert contract["planning_rows"] == [
        "smartcity-manual-calibration",
        "smartcity-gis-calibration",
    ]
    assert contract["capability_subset"] == [
        "calibration.legacy.core",
        "calibration.legacy.gis",
    ]
    assert contract["warehouse_sample_bundle"] == "excluded"
    assert contract["runtime_evidence"] == []
    assert contract["can_mark_capability_passed"] is False
    assert {
        "cartesian_project_validation",
        "image_project_validation",
        "gis_project_validation",
        "multi_camera_project_validation",
    }.issubset(contract["implemented"])
    assert "interactive_browser_editor" in contract["not_implemented"]
    assert (
        "cartesian_image_and_multi_camera_project_parity"
        not in contract["not_implemented"]
    )
    assert "runtime_qualification_on_Thor" in contract["not_implemented"]


def test_outputs_validate_against_both_vss_consumers_and_strict_road_schema() -> None:
    calibration, road = backend.compile_project(project())

    for schema_path in backend.CALIBRATION_SCHEMAS:
        assert (
            list(
                backend.Draft7Validator(backend._load_schema(schema_path)).iter_errors(
                    calibration
                )
            )
            == []
        )
    assert (
        list(
            backend.Draft7Validator(
                backend._load_schema(backend.ROAD_NETWORK_SCHEMA)
            ).iter_errors(road)
        )
        == []
    )


def test_multi_camera_requires_explicit_legal_output_calibration_type() -> None:
    value = project("mtmc")
    value["calibration_type"] = "mtmc"
    with pytest.raises(backend.CalibrationError, match="cartesian, image, or geo"):
        backend.compile_project(value)


def test_operator_metadata_is_required_instead_of_invented() -> None:
    value = project()
    del value["road_city"]
    with pytest.raises(backend.CalibrationError, match="unknown or missing"):
        backend.compile_project(value)

    value = project()
    del value["camera"]["origin"]
    with pytest.raises(backend.CalibrationError, match="camera has unknown or missing"):
        backend.compile_project(value)


def test_contract_is_raw_bound_to_open_architecture_and_capability_contracts() -> None:
    import hashlib

    contract = json.loads((LANE / "contract.json").read_text())
    repo = LANE.parents[3]
    loaded = {}
    for lock in contract["source_contracts"]:
        path = repo / lock["path"]
        assert not path.is_symlink() and path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == lock["raw_sha256"]
        loaded[lock["path"]] = json.loads(path.read_text())
    architecture = loaded[
        "deploy/docker/thor-local/qualification/architecture-gap-contracts/contract.json"
    ]
    rows = {row["id"]: row for row in architecture["rows"]}
    assert (
        rows["smartcity-manual-calibration"]["current_state"] == "blocked_architecture"
    )
    assert rows["smartcity-gis-calibration"]["current_state"] == "blocked_architecture"
    official = loaded["deploy/docker/thor-local/parity/official-capabilities.json"]
    capabilities = {row["id"]: row for row in official["capabilities"]}
    assert (
        capabilities["calibration.legacy.core"]["contract"][
            "minimum_gis_points_per_polygon"
        ]
        == 8
    )
    assert (
        capabilities["calibration.legacy.gis"]["contract"]["transform"]
        == "3x3_homography"
    )
    assert (
        capabilities["calibration.legacy.gis"]["contract"][
            "google_maps_key_for_roi_refiner"
        ]
        is True
    )


def test_module_has_no_network_docker_or_subprocess_imports() -> None:
    source = (LANE / "backend.py").read_text()
    for forbidden in (
        "import socket",
        "import requests",
        "import subprocess",
        "import docker",
        "urllib",
    ):
        assert forbidden not in source
