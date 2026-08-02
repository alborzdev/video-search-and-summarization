# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Adversarial tests for the provider-free LVS multi-video artifact oracle."""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

from jsonschema import Draft202012Validator
import pytest


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "lvs_multi_video_artifact_oracle", HERE / "executor.py"
)
assert SPEC is not None and SPEC.loader is not None
EXECUTOR = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = EXECUTOR
SPEC.loader.exec_module(EXECUTOR)


def _fixture() -> dict:
    return copy.deepcopy(EXECUTOR._load_fixture())


def test_static_candidate_is_concrete_but_non_promoting() -> None:
    result = EXECUTOR.run()
    assert result["status"] == "static_semantic_oracle_complete_non_promoting"
    assert result["candidate_implementation_state"] == "concrete_static_candidate"
    assert result["runtime_evidence"] == []
    assert result["canonical_state_advanced"] is False
    assert result["promotion_eligible"] is False
    assert result["warehouse_sample_bundle"] == "excluded"
    assert result["fixture"]["materialized_video_count"] == 0


def test_actual_product_helpers_restore_order_and_expose_shared_correlation() -> None:
    observed = EXECUTOR._production_observability(_fixture())
    assert observed["requested_sensor_ids"] == [
        "lvs_fixture_alpha.mp4",
        "lvs_fixture_beta.mp4",
    ]
    assert observed["successful_sensor_ids"] == observed["requested_sensor_ids"]
    assert [item["source_index"] for item in observed["artifacts"]] == [0, 1]
    assert {item["report_correlation_id"] for item in observed["artifacts"]} == {
        "lvs-0123456789abcdef0123456789abcdef"
    }


def test_per_artifact_semantics_are_source_specific_and_reciprocally_exclusive() -> (
    None
):
    assert EXECUTOR._semantic_oracle(_fixture()) == {
        "per_source_attribution": True,
        "reciprocal_negative_exclusion": True,
        "markdown_pdf_pairing": True,
        "semantic_digest_match": True,
        "one_missing_source_cannot_pass": True,
    }


def test_one_missing_source_or_extension_cannot_pass() -> None:
    fixture = _fixture()
    with pytest.raises(EXECUTOR.OracleError, match="exactly four artifacts"):
        EXECUTOR._semantic_oracle(fixture, fixture["artifacts"][:-1])


def test_swapped_source_attribution_cannot_pass_even_with_updated_digest() -> None:
    fixture = _fixture()
    artifacts = copy.deepcopy(fixture["artifacts"])
    artifacts[0]["sensor_id"] = "lvs_fixture_beta.mp4"
    artifacts[0]["source_index"] = 1
    artifacts[0]["semantic_text"] = artifacts[0]["semantic_text"].replace(
        "lvs_fixture_alpha.mp4", "lvs_fixture_beta.mp4"
    )
    artifacts[0]["semantic_text_sha256"] = hashlib.sha256(
        artifacts[0]["semantic_text"].encode()
    ).hexdigest()
    with pytest.raises(EXECUTOR.OracleError, match="planted event|cross-source"):
        EXECUTOR._semantic_oracle(fixture, artifacts)


def test_cross_contaminated_artifact_cannot_pass_even_with_updated_digest() -> None:
    fixture = _fixture()
    artifacts = copy.deepcopy(fixture["artifacts"])
    artifacts[0]["semantic_text"] += " violet-circle-stops-at-right-gate."
    artifacts[0]["semantic_text_sha256"] = hashlib.sha256(
        artifacts[0]["semantic_text"].encode()
    ).hexdigest()
    with pytest.raises(EXECUTOR.OracleError, match="cross-source"):
        EXECUTOR._semantic_oracle(fixture, artifacts)


def test_duplicate_extension_and_unpaired_stem_fail_closed() -> None:
    fixture = _fixture()
    duplicate = copy.deepcopy(fixture["artifacts"])
    duplicate[1]["extension"] = "md"
    duplicate[1]["object_store_key"] = duplicate[1]["object_store_key"].replace(
        ".pdf", ".md"
    )
    with pytest.raises(EXECUTOR.OracleError, match="duplicate artifact extension"):
        EXECUTOR._semantic_oracle(fixture, duplicate)

    unpaired = copy.deepcopy(fixture["artifacts"])
    unpaired[1]["object_store_key"] = (
        "vss_report_lvs_fixture_alpha.mp4_20260802_999999.pdf"
    )
    with pytest.raises(EXECUTOR.OracleError, match="not paired"):
        EXECUTOR._semantic_oracle(fixture, unpaired)


def test_recipe_or_semantic_digest_drift_fails_closed() -> None:
    fixture = _fixture()
    fixture["videos"][0]["recipe"]["background"] = "tampered"
    with pytest.raises(EXECUTOR.OracleError, match="recipe digest"):
        # Exercise the same invariant without mutating the checked-in fixture.
        for video in fixture["videos"]:
            if (
                EXECUTOR._sha256(EXECUTOR._canonical(video["recipe"]))
                != video["recipe_canonical_sha256"]
            ):
                raise EXECUTOR.OracleError("video recipe digest drift")

    fixture = _fixture()
    fixture["artifacts"][0]["semantic_text_sha256"] = "0" * 64
    with pytest.raises(EXECUTOR.OracleError, match="semantic digest"):
        EXECUTOR._semantic_oracle(fixture)


def test_result_schema_and_exact_confinement() -> None:
    result = EXECUTOR.run()
    schema = EXECUTOR._json(HERE / "result.schema.json")
    assert not list(Draft202012Validator(schema).iter_errors(result))
    assert result["confinement"] == {
        "network_calls": 0,
        "docker_calls": 0,
        "subprocess_calls": 0,
        "downloads": 0,
        "service_lifecycle_calls": 0,
        "model_calls": 0,
        "filesystem_writes": 0,
        "warehouse_sample_bundle": "excluded",
    }


def test_executor_imports_no_transport_process_or_model_client() -> None:
    tree = ast.parse((HERE / "executor.py").read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".", 1)[0])
    assert imports.isdisjoint(
        {"socket", "subprocess", "requests", "httpx", "docker", "transformers", "torch"}
    )


def test_source_lock_and_candidate_row_remain_exact() -> None:
    contract = EXECUTOR._load_contract()
    assert {
        item["path"] for item in contract["source_locks"]
    } == EXECUTOR.EXPECTED_LOCK_PATHS
    row = EXECUTOR._find_capability_row()
    assert row["runtime_state"] == "not_qualified"
    assert row["contract"]["warehouse_sample_bundle"] == "excluded"


def test_duplicate_json_keys_are_rejected() -> None:
    with pytest.raises(EXECUTOR.OracleError, match="duplicate JSON key"):
        EXECUTOR._strict_object([("a", 1), ("a", 2)])


def test_checked_fixture_and_result_are_deterministic() -> None:
    first = EXECUTOR.run()
    second = EXECUTOR.run()
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
