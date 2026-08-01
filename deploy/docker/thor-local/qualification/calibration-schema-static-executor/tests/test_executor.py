# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

LANE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "calibration_schema_static_executor", LANE / "executor.py"
)
assert SPEC and SPEC.loader
executor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(executor)


def test_complete_candidate_execution_is_deterministic_and_non_advancing() -> None:
    result = executor.execute()
    schema = json.loads((LANE / "result.schema.json").read_text(encoding="utf-8"))

    assert list(Draft202012Validator(schema).iter_errors(result)) == []
    assert result["result"] == "candidate_static_pass_non_advancing"
    assert result["official_capability_effect"] == "none_candidate_only"
    assert result["runtime_evidence"] == []
    assert result["policy"]["advances_live_acceptance"] is False
    assert result["determinism"] == {
        "independent_runs": 2,
        "run_tree_sha256": (
            "674bd43c12c904ff17519e2a8f9bbaa8cf4f1fb2349c85d49334034a629c2f5a"
        ),
        "byte_identical": True,
    }
    assert result["confinement"] == {
        "generated_inputs_in_memory": True,
        "private_temporary_root": True,
        "exact_regular_output_files": 16,
        "symlinks_observed": 0,
        "cleanup_verified": True,
    }


def test_exact_global_vector_capability_and_oracle_are_bound() -> None:
    result = executor.execute()
    binding = result["binding"]

    assert binding["planning_requirement_id"] == "calibration-schema-static"
    assert binding["planning_owner_type"] == "global_acceptance_vector"
    assert binding["owner_type_observed"] == "global_acceptance_vector"
    assert binding["capability_id"] == "calibration.schema.vss-json"
    assert binding["oracle_id"] == "oracle.calibration.schema.vss-json"
    assert binding["planning_applicable_record_count"] == 7
    assert len(binding["not_evaluated_record_ids"]) == 6
    assert binding["canonical_state_advanced"] is False


def test_generated_operator_fixture_denominator_and_mtmc_identity() -> None:
    fixtures = [executor.generated_fixture(kind) for kind in executor.FIXTURE_TYPES]
    assert [row["project_type"] for row in fixtures] == [
        "geo",
        "cartesian",
        "image",
        "mtmc",
    ]
    assert [row["calibration_type"] for row in fixtures] == [
        "geo",
        "cartesian",
        "image",
        "cartesian",
    ]
    assert len(fixtures[0]["rois"][0]["points"]) == 8
    assert len(fixtures[-1]["cameras"]) == 2
    assert len({camera["id"] for camera in fixtures[-1]["cameras"]}) == 2
    canonical = json.dumps(fixtures, sort_keys=True, separators=(",", ":"))
    assert "warehouse" not in canonical.lower()
    assert "google" not in canonical.lower()


def test_schema_semantics_match_exact_capability_contract() -> None:
    schemas = {
        role: executor._strict_json(executor._repo_file(path))
        for role, path in executor.SCHEMA_PATHS.items()
    }
    observed = executor._schema_contract(schemas)
    contract = executor._strict_json(LANE / "contract.json")

    assert observed == contract["schema_contract"]
    assert observed["matrix_shapes"] == {
        "intrinsic": [3, 3],
        "extrinsic": [3, 4],
        "camera": [3, 4],
        "homography": [3, 3],
    }
    assert observed["strict_calibration_additional_properties"] is False
    assert observed["behavior_calibration_additional_properties"] is True


def test_all_adjacent_invalid_cases_fail_closed() -> None:
    backend = executor._load_backend()
    schemas = {
        role: executor._strict_json(executor._repo_file(path))
        for role, path in executor.SCHEMA_PATHS.items()
    }
    observed = executor._run_adjacent_negatives(backend, schemas)
    contract = executor._strict_json(LANE / "contract.json")

    assert [row["case_id"] for row in observed] == contract["adjacent_negative_ids"]
    assert all(row["rejected"] for row in observed)
    missing = next(
        row
        for row in observed
        if row["case_id"] == "calibration-missing-required-version"
    )
    assert missing["rejected_by"] == [
        "strict_spatialai_calibration",
        "strict_video_api_calibration",
        "behavior_calibration",
    ]


def test_source_lock_tamper_fails_closed(tmp_path: Path, monkeypatch) -> None:
    contract = executor._load_contract()
    altered = tmp_path / "backend.py"
    altered.write_text("# altered\n", encoding="utf-8")
    original = executor._repo_file

    def redirected(relative: str) -> Path:
        if relative == executor.BACKEND_PATH:
            return altered
        return original(relative)

    monkeypatch.setattr(executor, "_repo_file", redirected)
    with pytest.raises(executor.QualificationError, match="source lock mismatch"):
        executor._verify_source_locks(contract)


def test_output_tree_rejects_symlinks(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    (tmp_path / "link.json").symlink_to(target)

    with pytest.raises(
        executor.QualificationError, match="unexpected output file type"
    ):
        executor._regular_tree(tmp_path)


def test_contract_drift_cannot_be_mistaken_for_a_pass(monkeypatch) -> None:
    original = executor._load_contract

    def altered_contract() -> dict:
        value = deepcopy(original())
        value["fixture_locks"][0]["input_sha256"] = "0" * 64
        return value

    monkeypatch.setattr(executor, "_load_contract", altered_contract)
    with pytest.raises(executor.QualificationError, match="output lock drift"):
        executor.execute()


def test_strict_json_rejects_duplicate_keys(tmp_path: Path) -> None:
    invalid = tmp_path / "duplicate.json"
    invalid.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")

    with pytest.raises(executor.QualificationError, match="duplicate JSON key"):
        executor._strict_json(invalid)


def test_executor_has_no_network_docker_subprocess_or_live_client() -> None:
    source = (LANE / "executor.py").read_text(encoding="utf-8")
    for forbidden in (
        "import socket",
        "import requests",
        "import subprocess",
        "import docker",
        "urllib",
        "http.client",
    ):
        assert forbidden not in source
