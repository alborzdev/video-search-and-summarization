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


HERE = Path(__file__).resolve()
PACKAGE = HERE.parents[1]
REPO_ROOT = HERE.parents[6]
SPEC = importlib.util.spec_from_file_location(
    "oracle_500_successor_compiler", PACKAGE / "compiler.py"
)
assert SPEC is not None and SPEC.loader is not None
compiler = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = compiler
SPEC.loader.exec_module(compiler)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def artifact() -> dict:
    value = load(compiler.OUTPUT)
    compiler.validate_successor(value)
    return value


@pytest.fixture(scope="module")
def adapter() -> dict:
    return load(REPO_ROOT / compiler.INPUTS["candidate_adapter"]["path"])


@pytest.fixture(scope="module")
def candidate_source() -> dict:
    return load(REPO_ROOT / compiler.INPUTS["candidate_source"]["path"])


@pytest.fixture(scope="module")
def official_capabilities() -> dict:
    return load(REPO_ROOT / compiler.INPUTS["official_capabilities"]["path"])


@pytest.fixture(scope="module")
def live() -> dict:
    return load(REPO_ROOT / compiler.INPUTS["live_oracles"]["path"])


@pytest.fixture(scope="module")
def protocol() -> dict:
    return load(REPO_ROOT / compiler.INPUTS["protocol_v2"]["path"])


@pytest.fixture(scope="module")
def workloads() -> dict:
    return load(REPO_ROOT / compiler.INPUTS["workloads"]["path"])


def candidate_rows(artifact: dict) -> dict[str, dict]:
    return {
        row["capability_id"]: row
        for row in artifact["projected_oracles"]
        if row.get("successor_schema_version") == 1
    }


def test_checked_successor_is_exact_deterministic_compile(artifact: dict) -> None:
    compiled = compiler.compile_successor()
    assert compiled == artifact
    assert compiler.OUTPUT.read_bytes() == compiler._encoded(compiled)
    assert compiler.main(["--check"]) == 0


def test_exact_289_plus_211_partition_and_live_prefix(
    artifact: dict,
    adapter: dict,
    candidate_source: dict,
    official_capabilities: dict,
    live: dict,
) -> None:
    projected = artifact["projected_oracles"]
    candidates = candidate_rows(artifact)
    live_ids = {row["capability_id"] for row in live["oracles"]}
    candidate_ids = set(adapter["candidate_adapters_by_capability_id"])
    assert projected[:289] == live["oracles"]
    assert compiler._canonical_bytes(projected[:289]) == compiler._canonical_bytes(
        live["oracles"]
    )
    assert len(projected) == 500
    assert len(live_ids) == 289
    assert set(candidates) == candidate_ids
    assert len(candidates) == 211
    assert not live_ids & candidate_ids
    assert len(live_ids | candidate_ids) == 500
    live_order = [row["id"] for row in official_capabilities["capabilities"]]
    candidate_order = [
        entry["proposed_capability"]["id"] for entry in candidate_source["entries"]
    ]
    projected_order = [row["capability_id"] for row in projected]
    assert [row["capability_id"] for row in live["oracles"]] == live_order
    assert projected_order == live_order + candidate_order
    assert artifact["ordering"] == {
        "live_order": "official_capabilities_source_order",
        "candidate_order": "strict_manifest_pointer_order",
        "live_capability_id_order_sha256": compiler._sha_json(live_order),
        "candidate_capability_id_order_sha256": compiler._sha_json(candidate_order),
        "projected_capability_id_order_sha256": compiler._sha_json(projected_order),
    }


def test_every_adapter_contract_is_exactly_preserved(
    artifact: dict, adapter: dict
) -> None:
    candidates = candidate_rows(artifact)
    fixture_ids = set()
    namespaces = set()
    additions = {
        "successor_schema_version",
        "origin",
        "profile",
        "mode",
        "protocol_v2_binding",
        "workload_binding",
        "binding_integrity",
        "successor_row_payload_sha256",
    }
    for capability_id, source in adapter["candidate_adapters_by_capability_id"].items():
        row = candidates[capability_id]
        projection = {key: value for key, value in row.items() if key not in additions}
        assert projection == source
        assert row["profile"] == source["profile_seed"]
        assert row["mode"] == source["mode_seed"]
        assert row["binding_integrity"][
            "adapter_record_canonical_sha256"
        ] == compiler._sha_json(source)
        observations = (
            row["expected_observations"] + row["adjacent_negative_observations"]
        )
        assert len({item["id"] for item in observations}) == len(observations)
        assert len({item["id"] for item in row["assertions"]}) == len(row["assertions"])
        assert {item["observation_id"] for item in row["assertions"]} == {
            item["id"] for item in observations
        }
        assert len({item["id"] for item in row["admission_gates"]}) == len(
            row["admission_gates"]
        )
        fixture_ids.add(row["fixture"]["id"])
        namespaces.add(row["fixture"]["namespace"])
        payload = dict(row)
        observed = payload.pop("successor_row_payload_sha256")
        assert observed == compiler._sha_json(payload)
    assert len(fixture_ids) == len(namespaces) == 211
    assert artifact["summary"]["authoritative_gap_requirements"] == 74


def test_exact_protocol_v2_bindings_are_consumed(
    artifact: dict, adapter: dict, protocol: dict
) -> None:
    candidates = candidate_rows(artifact)
    expected = {
        row["capability_id"]: row
        for row in protocol["bindings"]
        if row["capability_id"].startswith("manifest-entry.")
    }
    protocol_kinds = {
        capability_id
        for capability_id, row in adapter["candidate_adapters_by_capability_id"].items()
        if row["ledger_binding"]["kind"] == "protocol"
    }
    assert set(expected) == protocol_kinds
    assert len(expected) == 23
    for capability_id, binding in expected.items():
        row = candidates[capability_id]
        assert row["protocol_v2_binding"] == binding
        assert binding["vector_projection"]["contract"] == row["candidate_oracle_plan"]
        assert binding["readiness"] == "planning_only"
        assert binding["activation_supported"] is False
        assert row["binding_integrity"][
            "protocol_v2_binding_canonical_sha256"
        ] == compiler._sha_json(binding)
    assert all(
        row["protocol_v2_binding"] is None
        for capability_id, row in candidates.items()
        if capability_id not in expected
    )


def test_exact_api_and_deployment_workloads_are_consumed(
    artifact: dict, adapter: dict, workloads: dict
) -> None:
    candidates = candidate_rows(artifact)
    expected = {row["candidate_id"]: row for row in workloads["workloads"]}
    expected_ids = {
        capability_id
        for capability_id, row in adapter["candidate_adapters_by_capability_id"].items()
        if row["ledger_binding"]["kind"] in {"api", "deployment"}
    }
    assert set(expected) == expected_ids
    assert len(expected) == 60
    assert sum(row["workload_type"] == "api" for row in expected.values()) == 41
    assert sum(row["workload_type"] == "deployment" for row in expected.values()) == 19
    for capability_id, workload in expected.items():
        row = candidates[capability_id]
        assert row["workload_binding"] == workload
        assert workload["workload_type"] == row["ledger_binding"]["kind"]
        assert row["binding_integrity"][
            "workload_binding_canonical_sha256"
        ] == compiler._sha_json(workload)
    assert all(
        row["workload_binding"] is None
        for capability_id, row in candidates.items()
        if capability_id not in expected
    )


def test_all_candidate_rows_are_planning_only_null_and_non_promoting(
    artifact: dict,
) -> None:
    candidates = candidate_rows(artifact)
    assert artifact["summary"]["candidate_evidence_records"] == 0
    assert artifact["summary"]["candidate_executor_ready"] == 0
    assert artifact["summary"]["candidate_promoted"] == 0
    for row in candidates.values():
        assert row["fixture"]["materialization"] is None
        assert row["readiness"] == {
            "classification": "planning_index_only",
            "fixture_materialized": False,
            "executor_ready": False,
            "blockers": [
                "fixture_not_materialized",
                "executor_not_implemented",
                "collectors_not_implemented",
                "operator_approval_absent",
            ],
        }
        assert all(
            row["execution_bounds"][key] is None
            for key in (
                "max_duration_seconds",
                "max_requests",
                "max_actions",
                "executor",
                "collectors",
            )
        )
        assert all(
            row["cleanup"][key] is None
            for key in (
                "targets",
                "allowlist",
                "executor",
                "postcondition_collectors",
            )
        )
        assert row["evidence"] == []
        assert row["can_promote_runtime_state"] is False


def test_external_and_local_boundaries_are_exact(artifact: dict) -> None:
    candidates = candidate_rows(artifact)
    expected = {
        "required_local": (
            "local",
            "loopback_or_compose_internal",
            "open_unexecuted",
            "not_qualified",
        ),
        "alternate_local_lane": (
            "alternate_local",
            "operator_selected_local_alternate",
            "open_unexecuted",
            "not_qualified",
        ),
        "external_optional": (
            "external",
            "operator_approved_external_only",
            "external_boundary_unexecuted",
            "not_applicable",
        ),
    }
    for row in candidates.values():
        boundary, network, state, runtime = expected[row["acceptance_class"]]
        assert row["execution_boundary"] == boundary
        assert row["execution_bounds"]["network_scope"] == network
        assert row["current_state"] == state
        assert row["runtime_state"] == runtime
    assert (
        sum(row["execution_boundary"] == "external" for row in candidates.values()) == 6
    )


def test_preservation_and_projection_hashes_are_exact(
    artifact: dict, live: dict
) -> None:
    preservation = artifact["live_preservation"]
    live_by_id = {row["capability_id"]: row for row in live["oracles"]}
    assert preservation["live_oracle_records_canonical_sha256"] == compiler._sha_json(
        live["oracles"]
    )
    assert preservation["projected_live_prefix_canonical_sha256"] == compiler._sha_json(
        artifact["projected_oracles"][:289]
    )
    assert preservation["live_record_hashes_by_capability_id"] == {
        capability_id: compiler._sha_json(row)
        for capability_id, row in sorted(live_by_id.items())
    }
    assert artifact["projected_oracle_records_canonical_sha256"] == compiler._sha_json(
        artifact["projected_oracles"]
    )


def test_successor_schema_is_strict_and_live_source_schema_remains_authoritative(
    artifact: dict, live: dict
) -> None:
    successor_schema = load(compiler.SCHEMA)
    live_schema = load(REPO_ROOT / compiler.INPUTS["live_oracles_schema"]["path"])
    Draft202012Validator.check_schema(successor_schema)
    assert not list(Draft202012Validator(successor_schema).iter_errors(artifact))
    assert not list(Draft202012Validator(live_schema).iter_errors(live))
    mutated = copy.deepcopy(artifact)
    mutated["unexpected"] = True
    assert list(Draft202012Validator(successor_schema).iter_errors(mutated))
    mutated = copy.deepcopy(artifact)
    mutated["projected_oracles"][289]["unexpected"] = True
    assert list(Draft202012Validator(successor_schema).iter_errors(mutated))


@pytest.mark.parametrize(
    "mutation",
    [
        "preserved_live_extra",
        "candidate_ledger_extra",
        "candidate_plan_extra",
        "fixture_input_extra",
        "manifest_pointer_integer",
        "observation_id_integer",
        "assertion_observation_id_integer",
        "protocol_binding_loose",
        "workload_binding_loose",
        "gap_on_wrong_class",
        "protocol_on_wrong_kind",
        "workload_on_wrong_kind",
        "source_lock_identity",
        "arbitrary_live_hash_key",
        "arbitrary_candidate_hash_key",
        "mutated_live_order_hash",
        "mutated_candidate_order_hash",
        "mutated_projected_order_hash",
    ],
)
def test_successor_schema_rejects_reported_nested_mutations(
    artifact: dict, mutation: str
) -> None:
    value = copy.deepcopy(artifact)
    rows = value["projected_oracles"][289:]
    protocol_row = next(row for row in rows if row["protocol_v2_binding"] is not None)
    workload_row = next(row for row in rows if row["workload_binding"] is not None)
    plain_row = next(
        row
        for row in rows
        if row["protocol_v2_binding"] is None
        and row["workload_binding"] is None
        and row["prior_mapping_class"] == "family_only_unreviewed"
    )
    explicit_row = next(
        row
        for row in rows
        if row["prior_mapping_class"] == "explicit_missing_entry_gap"
    )
    if mutation == "preserved_live_extra":
        value["projected_oracles"][0]["unexpected"] = True
    elif mutation == "candidate_ledger_extra":
        plain_row["ledger_binding"]["unexpected"] = True
    elif mutation == "candidate_plan_extra":
        plain_row["candidate_oracle_plan"]["unexpected"] = True
    elif mutation == "fixture_input_extra":
        plain_row["fixture"]["input_contract"]["unexpected"] = True
    elif mutation == "manifest_pointer_integer":
        plain_row["manifest_pointer"] = 7
    elif mutation == "observation_id_integer":
        plain_row["expected_observations"][0]["id"] = 7
    elif mutation == "assertion_observation_id_integer":
        plain_row["assertions"][0]["observation_id"] = 7
    elif mutation == "protocol_binding_loose":
        protocol_row["protocol_v2_binding"]["unexpected"] = True
    elif mutation == "workload_binding_loose":
        workload_row["workload_binding"]["unexpected"] = True
    elif mutation == "gap_on_wrong_class":
        plain_row["candidate_oracle_plan"]["authoritative_gap_requirement"] = (
            copy.deepcopy(
                explicit_row["candidate_oracle_plan"]["authoritative_gap_requirement"]
            )
        )
    elif mutation == "protocol_on_wrong_kind":
        plain_row["protocol_v2_binding"] = copy.deepcopy(
            protocol_row["protocol_v2_binding"]
        )
    elif mutation == "workload_on_wrong_kind":
        plain_row["workload_binding"] = copy.deepcopy(workload_row["workload_binding"])
    elif mutation == "source_lock_identity":
        value["source_locks"]["live_oracles"]["path"] = (
            "deploy/docker/thor-local/parity/manifest.json"
        )
    elif mutation == "arbitrary_live_hash_key":
        hashes = value["live_preservation"]["live_record_hashes_by_capability_id"]
        hashes["arbitrary.live.oracle"] = hashes.pop(next(iter(hashes)))
    elif mutation == "arbitrary_candidate_hash_key":
        hashes = value["candidate_integrity"][
            "candidate_record_hashes_by_capability_id"
        ]
        hashes["manifest-entry.arbitrary.999-not-a-candidate"] = hashes.pop(
            next(iter(hashes))
        )
    elif mutation == "mutated_live_order_hash":
        value["ordering"]["live_capability_id_order_sha256"] = "0" * 64
    elif mutation == "mutated_candidate_order_hash":
        value["ordering"]["candidate_capability_id_order_sha256"] = "0" * 64
    elif mutation == "mutated_projected_order_hash":
        value["ordering"]["projected_capability_id_order_sha256"] = "0" * 64
    else:  # pragma: no cover - parametrization is closed above
        raise AssertionError(mutation)
    schema = load(compiler.SCHEMA)
    assert list(Draft202012Validator(schema).iter_errors(value)), mutation


def _mutate_locked_document(
    monkeypatch: pytest.MonkeyPatch,
    source_name: str,
    value: dict,
    payload_field: str,
    mutator,
) -> None:
    mutated = copy.deepcopy(value)
    mutator(mutated)
    payload = dict(mutated)
    payload.pop(payload_field)
    mutated[payload_field] = compiler._sha_json(payload)
    original = compiler._load_locked
    source_path = compiler.INPUTS[source_name]["path"]

    def substitute(relative: str, expected_sha256: str):
        if relative == source_path:
            return mutated, "0" * 64
        return original(relative, expected_sha256)

    monkeypatch.setattr(compiler, "_load_locked", substitute)


def test_protocol_contract_drift_fails_closed(
    monkeypatch: pytest.MonkeyPatch, protocol: dict
) -> None:
    def drift(value: dict) -> None:
        row = next(
            item
            for item in value["bindings"]
            if item["capability_id"].startswith("manifest-entry.")
        )
        row["vector_projection"]["contract"]["cleanup_boundary"] += " drift"

    _mutate_locked_document(
        monkeypatch, "protocol_v2", protocol, "candidate_payload_sha256", drift
    )
    with pytest.raises(compiler.SuccessorError, match="protocol-v2 semantic drift"):
        compiler.compile_successor()


def test_workload_key_swap_fails_closed(
    monkeypatch: pytest.MonkeyPatch, workloads: dict
) -> None:
    def swap(value: dict) -> None:
        api = next(row for row in value["workloads"] if row["workload_type"] == "api")
        deployment = next(
            row for row in value["workloads"] if row["workload_type"] == "deployment"
        )
        api["candidate_id"] = deployment["candidate_id"]

    _mutate_locked_document(monkeypatch, "workloads", workloads, "payload_sha256", swap)
    with pytest.raises(compiler.SuccessorError, match="duplicate workload key"):
        compiler.compile_successor()


def test_lexical_candidate_reordering_fails_closed(
    monkeypatch: pytest.MonkeyPatch, candidate_source: dict
) -> None:
    def reorder(value: dict) -> None:
        value["entries"].sort(key=lambda row: row["proposed_capability"]["id"])

    _mutate_locked_document(
        monkeypatch,
        "candidate_source",
        candidate_source,
        "candidate_payload_sha256",
        reorder,
    )
    with pytest.raises(compiler.SuccessorError, match="manifest-pointer order drift"):
        compiler.compile_successor()


def test_duplicate_json_key_fails_closed() -> None:
    with pytest.raises(compiler.SuccessorError, match="duplicate JSON key"):
        compiler._strict_json(b'{"same":1,"same":2}', "adversarial")


@pytest.mark.parametrize("relative", ["/etc/passwd", "../escape.json", "x/../../y"])
def test_unsafe_repository_paths_fail_closed(relative: str) -> None:
    with pytest.raises(compiler.SuccessorError, match="unsafe repository path"):
        compiler._repo_file(relative)


def test_symlink_repository_input_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    real = tmp_path / "real.json"
    real.write_text("{}\n", encoding="utf-8")
    (tmp_path / "linked.json").symlink_to(real)
    monkeypatch.setattr(compiler, "REPO_ROOT", tmp_path)
    with pytest.raises(compiler.SuccessorError, match="symlink"):
        compiler._repo_file("linked.json")


def test_atomic_writer_is_safe_and_rejects_symlink(tmp_path: Path) -> None:
    output = tmp_path / "successor.json"
    output.write_bytes(b"old\n")
    compiler._atomic_write_regular(output, b"new\n")
    assert output.read_bytes() == b"new\n"
    victim = tmp_path / "victim.json"
    victim.write_bytes(b"victim\n")
    output.unlink()
    output.symlink_to(victim)
    with pytest.raises(compiler.SuccessorError, match="symlink output"):
        compiler._atomic_write_regular(output, b"replacement\n")
    assert victim.read_bytes() == b"victim\n"


def test_all_locked_hashes_match_checked_files(artifact: dict) -> None:
    for source_name, lock in artifact["source_locks"].items():
        payload = (REPO_ROOT / lock["path"]).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == lock["raw_sha256"], source_name


def test_compiler_ast_has_no_runtime_network_or_activation_primitives() -> None:
    tree = ast.parse((PACKAGE / "compiler.py").read_text(encoding="utf-8"))
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not imported & {
        "docker",
        "requests",
        "httpx",
        "socket",
        "subprocess",
        "urllib",
    }
