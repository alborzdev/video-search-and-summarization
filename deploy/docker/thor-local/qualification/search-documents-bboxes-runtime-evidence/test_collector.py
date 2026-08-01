from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path

import pytest


PACKAGE_DIR = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "search_documents_bboxes_collector", PACKAGE_DIR / "collector.py"
)
assert SPEC is not None and SPEC.loader is not None
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)


def _simulation() -> dict:
    return json.loads(
        (PACKAGE_DIR / "fake-simulation.json").read_text(encoding="utf-8")
    )


def _validate_failure(payload: object, match: str | None = None) -> None:
    with pytest.raises(collector.ContractError, match=match):
        collector.validate_simulation(payload)


def test_plan_is_exact_non_advancing_14_by_14() -> None:
    plan = collector.compile_plan()
    assert plan["status"] == "candidate_plan_valid_non_advancing"
    assert plan["promotion_eligible"] is False
    assert plan["runtime_requests"] == plan["runtime_actions"] == 0
    assert plan["simulated_requests"] == plan["simulated_actions"] == 0
    assert plan["execution_bounds"]["max_requests"] == 14
    assert plan["execution_bounds"]["max_actions"] == 14
    assert len(plan["workflow"]) == 14
    assert sum(step["request_cost"] for step in plan["workflow"]) == 14
    assert sum(step["action_cost"] for step in plan["workflow"]) == 14
    assert plan["canonical_binding"]["canonical_current_state"] == "open_unexecuted"
    assert plan["canonical_binding"]["canonical_evidence_count"] == 0


def test_plan_preserves_exact_route_gap_and_alias_boundary() -> None:
    routes = collector.compile_plan()["route_contract"]
    assert routes["required_exact_paths"] == [
        "/api/v1/search",
        "/api/v1/search/attribute",
        "/api/v1/search/fusion",
        "/api/v1/search/image",
    ]
    assert (
        routes["currently_absent_required_paths"] == routes["required_exact_paths"][1:]
    )
    assert routes["forbidden_alias_equivalences"] == [
        "/api/v1/attribute_search",
        "/api/v1/embed_search",
    ]


def test_plan_preserves_selected_bbox_material_gap() -> None:
    fixture = collector.compile_plan()["fixture"]
    assert fixture["selected_bbox_image_bytes_present"] is False
    assert fixture["selected_bbox_image_digest_present"] is False


def test_valid_fake_simulation_is_non_advancing() -> None:
    result = collector.validate_simulation(_simulation())
    assert result["valid"] is True
    assert result["status"] == "candidate_simulation_valid_non_advancing"
    assert result["promotion_eligible"] is False
    assert result["runtime_requests"] == result["runtime_actions"] == 0
    assert result["simulated_requests"] == result["simulated_actions"] == 14
    assert result["canonical_current_state"] == "open_unexecuted"
    assert result["canonical_evidence"] == []


def test_second_allowed_negative_status_is_valid() -> None:
    payload = _simulation()
    payload["observations"][11]["expected_status"] = 400
    assert collector.validate_simulation(payload)["valid"] is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("promotion_eligible", True),
        ("runtime_requests", 1),
        ("runtime_actions", 1),
        ("simulated_requests", 13),
        ("simulated_actions", 15),
        ("canonical_current_state", "qualified"),
        ("canonical_evidence", [{"fake": True}]),
    ],
)
def test_top_level_advancement_or_count_mutations_fail(
    field: str, value: object
) -> None:
    payload = _simulation()
    payload[field] = value
    _validate_failure(payload, "schema validation failed")


def test_extra_top_level_property_fails_closed() -> None:
    payload = _simulation()
    payload["execute"] = True
    _validate_failure(payload, "schema validation failed")


def test_missing_observation_fails_closed() -> None:
    payload = _simulation()
    payload["observations"].pop()
    _validate_failure(payload, "schema validation failed")


def test_reordered_observations_fail_closed() -> None:
    payload = _simulation()
    payload["observations"][1], payload["observations"][2] = (
        payload["observations"][2],
        payload["observations"][1],
    )
    _validate_failure(payload, "schema validation failed")


@pytest.mark.parametrize("alias", ["/api/v1/attribute_search", "/api/v1/embed_search"])
def test_alias_cannot_replace_required_exact_route(alias: str) -> None:
    payload = _simulation()
    payload["observations"][2]["exact_path"] = alias
    _validate_failure(payload, "schema validation failed")


def test_forbidden_alias_use_flag_fails() -> None:
    payload = _simulation()
    payload["observations"][2]["forbidden_alias_used"] = True
    _validate_failure(payload, "schema validation failed")


def test_absent_route_cannot_be_reported_registered() -> None:
    payload = _simulation()
    payload["observations"][3]["currently_registered"] = True
    _validate_failure(payload, "schema validation failed")


def test_fake_route_cannot_claim_actual_http_response() -> None:
    payload = _simulation()
    payload["observations"][4]["actual_http_response_observed"] = True
    _validate_failure(payload, "schema validation failed")


@pytest.mark.parametrize("field", ["image_bytes_present", "image_digest_present"])
def test_selected_bbox_material_cannot_be_invented(field: str) -> None:
    payload = _simulation()
    payload["observations"][10][field] = True
    _validate_failure(payload, "schema validation failed")


def test_selected_bbox_cannot_claim_actual_knn() -> None:
    payload = _simulation()
    payload["observations"][10]["actual_semantic_observed"] = True
    _validate_failure(payload, "schema validation failed")


@pytest.mark.parametrize("status", [200, 404, 500])
def test_invalid_index_negative_requires_400_or_422(status: int) -> None:
    payload = _simulation()
    payload["observations"][11]["expected_status"] = status
    _validate_failure(payload, "schema validation failed")


@pytest.mark.parametrize("field", ["backend_query_count", "backend_write_count"])
def test_invalid_index_negative_cannot_reach_backend(field: str) -> None:
    payload = _simulation()
    payload["observations"][11][field] = 1
    _validate_failure(payload, "schema validation failed")


def test_invalid_index_negative_cannot_use_allowed_family() -> None:
    payload = _simulation()
    payload["observations"][11]["index_family"] = "mdx-raw-*"
    _validate_failure(payload, "schema validation failed")


def test_cleanup_requires_exact_registration_allowlist() -> None:
    payload = _simulation()
    payload["observations"][12]["registered_documents"].reverse()
    _validate_failure(payload, "registration list")


def test_cleanup_requires_exact_lifo_order() -> None:
    payload = _simulation()
    payload["observations"][12]["simulated_deleted_documents"].reverse()
    _validate_failure(payload, "not exact LIFO")


@pytest.mark.parametrize(
    "field",
    [
        "index_delete_attempted",
        "ambiguous_resource_delete_attempted",
        "foreign_resource_delete_attempted",
    ],
)
def test_cleanup_forbidden_delete_modes_fail(field: str) -> None:
    payload = _simulation()
    payload["observations"][12][field] = True
    _validate_failure(payload, "schema validation failed")


def test_fake_cleanup_cannot_claim_actual_delete() -> None:
    payload = _simulation()
    payload["observations"][12]["actual_delete_count"] = 1
    _validate_failure(payload, "schema validation failed")


@pytest.mark.parametrize(
    "field",
    ["service_state_digest", "configuration_digest", "non_owned_indices_digest"],
)
def test_postcondition_digests_must_match_prestate(field: str) -> None:
    payload = _simulation()
    payload["observations"][13][field] = "a" * 64
    _validate_failure(payload, "does not match pre-state")


def test_postcondition_cannot_claim_delayed_reappearance_observation() -> None:
    payload = _simulation()
    payload["observations"][13]["late_reappearance_window_observed"] = True
    _validate_failure(payload, "schema validation failed")


def test_blocker_cannot_be_removed() -> None:
    payload = _simulation()
    payload["blockers"].pop()
    _validate_failure(payload, "schema validation failed")


class _TrapDict(dict):
    def items(self):  # pragma: no cover - must never be invoked
        raise AssertionError("caller-controlled mapping callback was invoked")


def test_mapping_subclass_is_rejected_without_callback() -> None:
    payload = _TrapDict(_simulation())
    _validate_failure(payload, "non-plain JSON value rejected")


def test_callable_value_is_rejected_without_invocation() -> None:
    payload = _simulation()

    def trap() -> None:  # pragma: no cover - must never be invoked
        raise AssertionError("callback was invoked")

    payload["callback"] = trap
    _validate_failure(payload, "non-plain JSON value rejected")


def test_non_finite_json_number_is_rejected() -> None:
    payload = _simulation()
    payload["observations"][0]["not_a_number"] = float("nan")
    _validate_failure(payload, "non-finite number")


def test_duplicate_source_lock_fails_closed() -> None:
    contract = copy.deepcopy(collector._load_json(collector.CONTRACT_PATH))
    contract["source_locks"][1] = copy.deepcopy(contract["source_locks"][0])
    with pytest.raises(collector.ContractError, match="exact contract"):
        collector._verify_source_locks(contract)


def test_absolute_source_lock_escape_fails_before_hashing() -> None:
    contract = copy.deepcopy(collector._load_json(collector.CONTRACT_PATH))
    contract["source_locks"][0] = {"path": "/etc/passwd", "sha256": "0" * 64}
    with pytest.raises(collector.ContractError, match="exact contract"):
        collector._verify_source_locks(contract)


def test_source_lock_substitution_is_rejected_by_schema_and_verifier() -> None:
    contract = copy.deepcopy(collector._load_json(collector.CONTRACT_PATH))
    replacement = PACKAGE_DIR / "README.md"
    contract["source_locks"][-1] = {
        "path": str(replacement.relative_to(collector.REPO_ROOT)),
        "sha256": collector._sha256_bytes(replacement.read_bytes()),
    }
    with pytest.raises(collector.ContractError, match="schema validation failed"):
        collector._validate_schema(contract, collector.CONTRACT_SCHEMA_PATH)
    with pytest.raises(collector.ContractError, match="exact contract"):
        collector._verify_source_locks(contract)


def test_fixture_binding_digest_must_equal_actual_locked_fixture() -> None:
    contract = copy.deepcopy(collector._load_json(collector.CONTRACT_PATH))
    contract["fixture_binding"]["fixture_sha256"] = "0" * 64
    with pytest.raises(collector.ContractError, match="fixture binding digest"):
        collector._verify_source_locks(contract)


def test_json_loader_rejects_duplicate_keys(tmp_path: Path) -> None:
    source = tmp_path / "duplicate.json"
    source.write_text('{"key":1,"key":2}', encoding="utf-8")
    with pytest.raises(collector.ContractError, match="duplicate JSON object key"):
        collector._load_json(source)


def test_json_loader_rejects_symlink_fifo_and_oversize(tmp_path: Path) -> None:
    regular = tmp_path / "regular.json"
    regular.write_text("{}", encoding="utf-8")
    symlink = tmp_path / "symlink.json"
    symlink.symlink_to(regular)
    with pytest.raises(collector.ContractError, match="non-symlink"):
        collector._load_json(symlink)

    fifo = tmp_path / "fifo.json"
    os.mkfifo(fifo)
    with pytest.raises(collector.ContractError, match="non-symlink"):
        collector._load_json(fifo)

    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b" " * 33)
    with pytest.raises(collector.ContractError, match="exceeds 32 bytes"):
        collector._load_json(oversized, max_bytes=32)


def test_source_contains_no_runtime_or_write_adapter() -> None:
    source = (PACKAGE_DIR / "collector.py").read_text(encoding="utf-8")
    forbidden = [
        "import requests",
        "import socket",
        "import subprocess",
        "import urllib",
        "import httpx",
        "import docker",
        ".write_text(",
        ".write_bytes(",
        "Popen(",
        "urlopen(",
    ]
    assert not any(token in source for token in forbidden)


def test_cli_exposes_only_plan_and_validate_simulation() -> None:
    parser = collector._build_parser()
    help_text = parser.format_help()
    assert "plan" in help_text
    assert "validate-simulation" in help_text
    assert "execute" not in help_text
