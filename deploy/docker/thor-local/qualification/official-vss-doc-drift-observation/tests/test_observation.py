# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

LANE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "official_vss_doc_drift_observation", LANE / "validate_observation.py"
)
assert SPEC is not None and SPEC.loader is not None
VALIDATOR = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VALIDATOR
SPEC.loader.exec_module(VALIDATOR)


def test_metadata_observation_is_exact_and_non_advancing() -> None:
    result = VALIDATOR.validate()
    assert result["verified_baseline"]["url_count"] == 172
    assert result["verified_baseline"]["canonical_directed_edge_count"] == 26449
    assert result["recorded_observation"] == {
        "observed_on": "2026-08-01",
        "raw_sha256_changed_count": 172,
        "per_page_byte_count_match_count": 172,
        "canonical_url_set_identical": True,
        "directed_edge_topology_identical": True,
        "semantic_equality": "unproven",
    }
    assert result["evidence_boundary"]["external_observation_reproduced_by_validator"] is False
    assert result["promotion"]["runtime_evidence"] == []
    assert result["promotion"]["feature_evidence"] == []
    assert result["promotion"]["feature_or_runtime_promotion"] is False


def test_all_172_urls_and_26449_edges_are_recomputed_from_baseline() -> None:
    observation = VALIDATOR._strict_json(LANE / "observation.json")
    hashes = VALIDATOR._verify_baseline(observation)
    assert hashes == VALIDATOR.SOURCE_BINDINGS


def test_graph_edge_mutation_fails_closed() -> None:
    targets = VALIDATOR._strict_json(
        VALIDATOR._repo_file(list(VALIDATOR.SOURCE_BINDINGS)[1])
    )["targets"]
    graph = deepcopy(
        VALIDATOR._strict_json(
            VALIDATOR._repo_file(list(VALIDATOR.SOURCE_BINDINGS)[2])
        )
    )
    graph["scans"][0]["outbound_target_indexes"].pop()
    with pytest.raises(VALIDATOR.ObservationError, match="topology drift"):
        VALIDATOR._verify_graph(graph, targets)


def test_schema_rejects_semantic_or_promotion_overclaim() -> None:
    observation = VALIDATOR._strict_json(LANE / "observation.json")
    schema = VALIDATOR._strict_json(LANE / "observation.schema.json")
    semantic = deepcopy(observation)
    semantic["interpretation"]["semantic_equality"] = "proven_equal"
    promoted = deepcopy(observation)
    promoted["promotion"]["runtime_evidence"] = ["invented"]
    relabelled = deepcopy(observation)
    relabelled["promotion"]["source_lock_relabelled"] = True
    validator = Draft202012Validator(schema)
    assert list(validator.iter_errors(semantic))
    assert list(validator.iter_errors(promoted))
    assert list(validator.iter_errors(relabelled))


def test_schema_rejects_invented_august_hash_availability() -> None:
    observation = VALIDATOR._strict_json(LANE / "observation.json")
    schema = VALIDATOR._strict_json(LANE / "observation.schema.json")
    invented = deepcopy(observation)
    invented["evidence_availability"]["august_per_page_sha256_values_available"] = True
    assert list(Draft202012Validator(schema).iter_errors(invented))


def test_baseline_source_hash_tamper_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    original = VALIDATOR._sha256_file
    source_lock_path = VALIDATOR._repo_file(next(iter(VALIDATOR.SOURCE_BINDINGS)))

    def tampered(path: Path) -> str:
        if path == source_lock_path:
            return "0" * 64
        return original(path)

    monkeypatch.setattr(VALIDATOR, "_sha256_file", tampered)
    observation = VALIDATOR._strict_json(LANE / "observation.json")
    with pytest.raises(VALIDATOR.ObservationError, match="baseline hash drift"):
        VALIDATOR._verify_baseline(observation)


def test_strict_json_rejects_duplicate_keys_and_symlink(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"a":1,"a":2}', encoding="utf-8")
    with pytest.raises(VALIDATOR.ObservationError, match="duplicate JSON key"):
        VALIDATOR._strict_json(duplicate)
    link = tmp_path / "link.json"
    link.symlink_to(duplicate)
    with pytest.raises(VALIDATOR.ObservationError, match="non-symlink"):
        VALIDATOR._strict_json(link)


def test_validator_has_no_transport_process_or_write_surface() -> None:
    tree = ast.parse((LANE / "validate_observation.py").read_text(encoding="utf-8"))
    imports: set[str] = set()
    calls: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".", 1)[0])
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                calls.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                calls.add(node.func.attr)
    assert imports.isdisjoint(
        {"aiohttp", "docker", "httpx", "requests", "socket", "subprocess", "urllib"}
    )
    assert calls.isdisjoint({"Popen", "run", "system", "urlopen", "write_text", "write_bytes"})


def test_result_schema_is_exact() -> None:
    result = VALIDATOR.validate()
    schema = json.loads((LANE / "result.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(result)
    invented = deepcopy(result)
    invented["evidence_boundary"]["exact_august_relock_materialized"] = True
    assert list(Draft202012Validator(schema).iter_errors(invented))
