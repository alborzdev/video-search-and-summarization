from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest


HERE = Path(__file__).resolve()
LANE_DIR = HERE.parents[1]
REPO_ROOT = HERE.parents[6]
COMPILER_PATH = LANE_DIR / "runtime_lane_compiler.py"
SPEC = importlib.util.spec_from_file_location("runtime_lane_compiler", COMPILER_PATH)
assert SPEC is not None and SPEC.loader is not None
compiler = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = compiler
SPEC.loader.exec_module(compiler)


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
    ).hexdigest()


@pytest.fixture(scope="module")
def plan() -> dict:
    return compiler._load(compiler.PLAN)


def test_checked_plan_is_exact_deterministic_output(plan: dict) -> None:
    compiler.validate_plan(plan)
    assert plan == compiler.build_plan()
    assert compiler.PLAN.read_bytes() == compiler._encoded(plan)
    assert compiler.main(["--check"]) == 0


def test_exact_denominators_and_lane_counts(plan: dict) -> None:
    assert plan["denominators"] == compiler.EXPECTED_DENOMINATORS
    assert plan["lane_capability_counts"] == compiler.EXPECTED_LANE_COUNTS
    assert sum(plan["lane_capability_counts"].values()) == 289
    assert len(plan["lanes"]) == 8
    assert len(plan["feature_family_bindings"]) == 55
    assert len(plan["advertised_entry_bindings"]) == 500
    assert len(plan["capability_bindings"]) == 289


def test_every_capability_and_every_family_is_bound_once(plan: dict) -> None:
    capability_ids = [
        binding["capability_id"] for binding in plan["capability_bindings"]
    ]
    family_ids = [binding["feature_id"] for binding in plan["feature_family_bindings"]]
    assert len(capability_ids) == len(set(capability_ids)) == 289
    assert len(family_ids) == len(set(family_ids)) == 55
    assert (
        sum(item["capability_count"] == 0 for item in plan["feature_family_bindings"])
        == 13
    )
    assert all(item["lane_ids"] for item in plan["feature_family_bindings"])


def test_oracle_contract_and_planning_service_bindings_are_deterministic(
    plan: dict,
) -> None:
    oracle_document = compiler._load(REPO_ROOT / compiler.SOURCE_PATHS["oracles"])
    oracle_by_capability = {
        item["capability_id"]: item for item in oracle_document["oracles"]
    }
    ledger = compiler._load(REPO_ROOT / compiler.SOURCE_PATHS["ledger"])
    capability_by_id = {item["id"]: item for item in ledger["capabilities"]}
    lane_by_id = {item["id"]: item for item in plan["lanes"]}
    for binding in plan["capability_bindings"]:
        oracle = oracle_by_capability[binding["capability_id"]]
        capability = capability_by_id[binding["capability_id"]]
        lane = lane_by_id[binding["lane_id"]]
        service_binding = compiler._planned_service_binding(
            capability, binding["lane_id"]
        )
        planned_roles = service_binding["roles"]
        planned_paths = sorted(
            {
                path
                for role in planned_roles
                if (path := compiler.SERVICE_COMPOSE_PATH[role]) is not None
            }
        )
        non_compose = sorted(
            role
            for role in planned_roles
            if compiler.SERVICE_COMPOSE_PATH[role] is None
        )
        assert binding["oracle_contract_sha256"] == canonical_sha256(oracle)
        assert binding["oracle_profile"] == oracle["profile"]
        assert binding["oracle_mode"] == oracle["mode"]
        assert binding["deployment"]["profile_paths"] == lane["profile_paths"]
        assert binding["deployment"]["planned_service_roles"] == planned_roles
        assert binding["deployment"]["planned_service_compose_paths"] == planned_paths
        assert binding["deployment"]["planned_non_compose_roles"] == non_compose
        assert (
            binding["deployment"]["service_binding_state"] == service_binding["state"]
        )
        assert (
            binding["deployment"]["service_binding_basis"] == service_binding["basis"]
        )
        assert (
            binding["deployment"]["service_binding_source_claims"]
            == capability["source_claims"]
        )
        assert binding["deployment"][
            "service_binding_capability_contract_sha256"
        ] == canonical_sha256(capability["contract"])
        assert not binding["deployment"]["service_binding_is_runtime_evidence"]
        assert set(planned_paths) <= set(lane["service_compose_paths"])
        assert binding["probe"]["fixture"] == oracle["fixture"]
        assert binding["probe"]["execution_bounds"] == oracle["execution_bounds"]
        assert binding["cleanup"] == oracle["cleanup"]
        assert set(oracle["acceptance_readiness"]["blockers"]) <= set(
            binding["blockers"]
        )
        assert binding["evidence"]["current_records"] == []
        assert not binding["evidence"][
            "may_promote_runtime_state_without_current_record"
        ]


def test_every_advertised_entry_has_an_exact_pointer_and_family_lane_binding(
    plan: dict,
) -> None:
    manifest = compiler._load(REPO_ROOT / compiler.SOURCE_PATHS["manifest"])
    advertised_gap_plan = compiler._load(
        REPO_ROOT / compiler.SOURCE_PATHS["advertised_gap_plan"]
    )
    gap_by_pointer = {
        item["manifest_pointer"]: item for item in advertised_gap_plan["entries"]
    }
    family_by_id = {
        item["feature_id"]: item for item in plan["feature_family_bindings"]
    }
    expected_pointers: list[str] = []
    for feature_index, feature in enumerate(manifest["features"]):
        for advertised_index, claim in enumerate(feature["advertised"]):
            pointer = f"/features/{feature_index}/advertised/{advertised_index}"
            expected_pointers.append(pointer)
            binding = plan["advertised_entry_bindings"][len(expected_pointers) - 1]
            family = family_by_id[feature["id"]]
            assert binding["manifest_json_pointer"] == pointer
            assert binding["feature_id"] == feature["id"]
            assert binding["feature_manifest_index"] == feature_index
            assert binding["advertised_index"] == advertised_index
            assert binding["advertised_claim"] == claim
            assert binding["family_acceptance_class"] == feature["acceptance_class"]
            gap_entry = gap_by_pointer.get(pointer)
            assert binding["entry_planning_acceptance_class"] == (
                gap_entry["proposed_capability"]["acceptance_class"]
                if gap_entry is not None
                else None
            )
            is_entry_specific = bool(binding["entry_specific_capability_ids"])
            assert binding["entry_classification_source"] == (
                "advertised-entry-gap-plan"
                if gap_entry is not None
                else "canonical-entry-capability"
                if is_entry_specific
                and binding["entry_specific_capability_ids"][0].startswith(
                    "manifest-entry."
                )
                else "exact-existing-capability-title-match"
                if is_entry_specific
                else "not-applicable-family-has-capability-rows"
            )
            if is_entry_specific:
                capability_binding = next(
                    item
                    for item in plan["capability_bindings"]
                    if item["capability_id"]
                    == binding["entry_specific_capability_ids"][0]
                )
                assert binding["default_lane_id"] == capability_binding["lane_id"]
                assert binding["lane_ids"] == [capability_binding["lane_id"]]
            elif (
                gap_entry is not None
                and gap_entry["proposed_capability"]["acceptance_class"]
                == "external_optional"
            ):
                assert binding["default_lane_id"] == "external-optional"
                assert binding["lane_ids"] == ["external-optional"]
                assert binding["lane_binding_scope"] == (
                    "entry_specific_gap_acceptance_boundary"
                )
            else:
                assert binding["default_lane_id"] == family["default_lane_id"]
                assert binding["lane_ids"] == family["lane_ids"]
            assert binding["feature_capability_ids"] == sorted(
                feature.get("official_capability_ids", [])
            )
            assert binding["feature_oracle_ids"] == [
                f"oracle.{capability_id}"
                for capability_id in binding["feature_capability_ids"]
            ]
            if is_entry_specific:
                assert len(binding["entry_specific_capability_ids"]) == 1
                assert binding["entry_specific_oracle_ids"] == [
                    f"oracle.{binding['entry_specific_capability_ids'][0]}"
                ]
                assert binding["lane_binding_scope"] == (
                    "entry_specific_exact_capability"
                )
                assert binding["capability_mapping_scope"] == (
                    "canonical_entry_capability"
                    if binding["entry_specific_capability_ids"][0].startswith(
                        "manifest-entry."
                    )
                    else "exact_existing_capability"
                )
            else:
                assert binding["entry_specific_capability_ids"] == []
                assert binding["entry_specific_oracle_ids"] == []
            assert binding["manifest_entry_sha256"] == canonical_sha256(
                {"json_pointer": pointer, "value": claim}
            )
    actual_pointers = [
        item["manifest_json_pointer"] for item in plan["advertised_entry_bindings"]
    ]
    assert actual_pointers == expected_pointers
    assert len(actual_pointers) == len(set(actual_pointers)) == 500


def test_advertised_entry_semantic_and_runtime_gaps_are_explicit(plan: dict) -> None:
    bindings = plan["advertised_entry_bindings"]
    assert sum(bool(item["feature_capability_ids"]) for item in bindings) == 431
    assert sum(not item["feature_capability_ids"] for item in bindings) == 69
    assert (
        sum(
            item["entry_planning_acceptance_class"] == "required_local"
            for item in bindings
        )
        == 55
    )
    assert (
        sum(
            item["entry_planning_acceptance_class"] == "alternate_local_lane"
            for item in bindings
        )
        == 15
    )
    assert (
        sum(
            item["entry_planning_acceptance_class"] == "external_optional"
            for item in bindings
        )
        == 4
    )
    assert {
        item["capability_mapping_scope"]
        for item in bindings
        if item["feature_capability_ids"]
    } == {
        "feature_family_only",
        "feature_family_only_with_open_entry_gap",
        "canonical_entry_capability",
        "exact_existing_capability",
    }
    assert {
        item["capability_mapping_scope"]
        for item in bindings
        if not item["feature_capability_ids"]
    } == {"none_family_has_zero_capability_rows"}
    entry_specific = [
        item for item in bindings if item["entry_specific_capability_ids"]
    ]
    assert len(entry_specific) == 289
    assert {
        capability_id
        for item in entry_specific
        for capability_id in item["entry_specific_capability_ids"]
    } == {
        item["capability_id"] for item in plan["capability_bindings"]
    }
    assert sum(
        not item["entry_specific_capability_ids"] for item in bindings
    ) == 211
    assert sum(
        item["capability_mapping_scope"] == "feature_family_only"
        for item in bindings
    ) == 137
    assert all(not item["runtime_evidence_records"] for item in bindings)
    assert plan["policy"]["advertised_entry_mapping_scope"] == (
        "feature_family_with_exact_entry_overrides"
    )
    assert not plan["policy"]["advertised_entry_bindings_are_runtime_evidence"]
    assert plan["policy"]["zero_capability_family_entries_block_runtime_completeness"]
    assert plan["policy"]["family_only_entry_bindings_block_runtime_completeness"]
    assert not plan["policy"]["literal_runtime_feature_completeness_claim_allowed"]


def test_entry_specific_tooling_bindings_use_exact_capability_lane(plan: dict) -> None:
    bindings = {
        item["entry_specific_capability_ids"][0]: item
        for item in plan["advertised_entry_bindings"]
        if item["entry_specific_capability_ids"]
    }
    aws = bindings["manifest-entry.spatial-ai-utils.07-aws-gcs-validation"]
    assert aws["default_lane_id"] == "external-optional"
    assert aws["lane_ids"] == ["external-optional"]
    local_tooling_ids = {
        capability_id
        for capability_id in compiler.MIGRATED_ENTRY_CAPABILITY_IDS
        if capability_id.startswith("manifest-entry.spatial-ai-utils.")
        or capability_id.startswith("manifest-entry.synthetic-data-tools.")
    } - {"manifest-entry.spatial-ai-utils.07-aws-gcs-validation"}
    assert all(
        bindings[capability_id]["lane_ids"] != ["external-optional"]
        and "external-optional" not in bindings[capability_id]["lane_ids"]
        for capability_id in local_tooling_ids
    )


def test_cpu_multimedia_capability_is_planning_only_and_not_promoted(plan: dict) -> None:
    binding = next(
        item
        for item in plan["capability_bindings"]
        if item["capability_id"] == compiler.CPU_MULTIMEDIA_CAPABILITY_ID
    )
    assert binding["feature_id"] == "vios-codecs-audio"
    assert binding["lane_id"] == "standalone-services"
    assert binding["kind"] == "runtime_behavior"
    assert binding["runtime_state"] == "not_qualified"
    assert binding["oracle_id"] == f"oracle.{compiler.CPU_MULTIMEDIA_CAPABILITY_ID}"
    assert binding["oracle_current_state"] == "open_unexecuted"
    assert binding["deployment"]["planned_service_roles"] == ["vios"]
    assert binding["probe"]["execution_bounds"]["executor"] is None
    assert binding["cleanup"]["executor"] is None
    assert binding["evidence"]["current_records"] == []


def test_service_binding_audit_is_planning_only_and_unresolved_is_fail_closed(
    plan: dict,
) -> None:
    by_id = {
        item["capability_id"]: item["deployment"]
        for item in plan["capability_bindings"]
    }
    unresolved = {
        item["capability_id"]
        for item in plan["capability_bindings"]
        if item["deployment"]["service_binding_state"] == "unresolved"
    }
    assert unresolved == {
        "customization.embedding-reindex-validation",
        "protocol.nvschema.format-selection",
        "protocol.nvschema.json-frame",
        "protocol.nvschema.protobuf-messages",
    }
    assert all(
        not item["deployment"]["service_binding_is_runtime_evidence"]
        for item in plan["capability_bindings"]
    )
    assert all(
        "unresolved-service-binding" in item["deployment"]["planned_non_compose_roles"]
        for item in plan["capability_bindings"]
        if item["capability_id"] in unresolved
    )
    assert plan["policy"]["unresolved_service_bindings_block_runtime_completeness"]
    assert not plan["policy"]["planned_service_bindings_are_runtime_evidence"]
    assert {item["service_binding_state"] for item in by_id.values()} == {
        "planning_only",
        "unresolved",
    }
    assert {
        capability_id: by_id[capability_id]["planned_service_roles"]
        for capability_id in (
            "api.vss-configurator.sensor",
            "config.vss-configurator.profile-manager",
            "config.vss-configurator.sensor-manager",
            "customization.cosmos-embed1",
            "customization.rt-detr",
            "customization.siglip2",
            "protocol.kafka.nvschema",
            "protocol.redis.events",
            "runtime.rtvi.input-codec-boundary",
            "tool.mv3dt.cam-info-generator",
            "tool.mv3dt.pub-sub-generator",
        )
    } == {
        "api.vss-configurator.sensor": ["vss-configurator"],
        "config.vss-configurator.profile-manager": ["vss-configurator"],
        "config.vss-configurator.sensor-manager": ["vss-configurator"],
        "customization.cosmos-embed1": ["rt-embed"],
        "customization.rt-detr": ["rt-cv"],
        "customization.siglip2": ["rt-cv"],
        "protocol.kafka.nvschema": ["alerts", "infrastructure"],
        "protocol.redis.events": ["behavior-analytics", "infrastructure"],
        "runtime.rtvi.input-codec-boundary": ["rt-cv"],
        "tool.mv3dt.cam-info-generator": ["repository-tooling"],
        "tool.mv3dt.pub-sub-generator": ["repository-tooling"],
    }


def test_all_checked_profile_and_service_paths_exist(plan: dict) -> None:
    for lane in plan["lanes"]:
        for relative in lane["profile_paths"] + lane["service_compose_paths"]:
            assert (REPO_ROOT / relative).is_file(), relative


def test_warehouse_sample_is_excluded_but_custom_lane_is_present(plan: dict) -> None:
    assert plan["policy"]["warehouse_sample_bundle"] == "excluded"
    assert plan["policy"]["warehouse_custom_data"] == "in_scope"
    warehouse = next(
        lane for lane in plan["lanes"] if lane["id"] == "custom-data-warehouse"
    )
    assert "sample bundle forbidden" in warehouse["fixture_strategy"]
    assert plan["lane_capability_counts"]["custom-data-warehouse"] == 28
    assert all(
        binding["probe"]["fixture"]["warehouse_sample_bundle"] is False
        for binding in plan["capability_bindings"]
    )


def test_external_optional_is_fail_closed_and_cannot_count_local(plan: dict) -> None:
    external = [
        item
        for item in plan["capability_bindings"]
        if item["acceptance_class"] == "external_optional"
    ]
    assert len(external) == 30
    assert {item["lane_id"] for item in external} == {"external-optional"}
    assert plan["policy"]["external_optional_cannot_satisfy_local"] is True
    assert plan["policy"]["required_cloud_inference"] is False

    external_gaps = [
        item
        for item in plan["advertised_entry_bindings"]
        if item["entry_planning_acceptance_class"] == "external_optional"
    ]
    assert len(external_gaps) == 4
    assert all(
        item["default_lane_id"] == "external-optional"
        and item["lane_ids"] == ["external-optional"]
        and item["lane_binding_scope"]
        == "entry_specific_gap_acceptance_boundary"
        for item in external_gaps
    )
    assert all(
        item["default_lane_id"] != "external-optional"
        for item in plan["advertised_entry_bindings"]
        if item["entry_planning_acceptance_class"]
        in {"required_local", "alternate_local_lane"}
    )


def test_official_edge_identity_boundary_has_only_reviewed_five(plan: dict) -> None:
    capability_ids = {
        item["capability_id"]
        for item in plan["capability_bindings"]
        if item["lane_id"] == "official-edge-model-boundary"
    }
    assert capability_ids == {
        "boundary.thor.official-profiles",
        "boundary.thor.fully-local-future",
        "boundary.thor.custom-all-local-extension",
        "model.edge.nemotron-3-nano-4b-fp8",
        "model.edge.cosmos3-nano-served-id",
    }


def _copy_locked_sources(destination: Path) -> None:
    for relative in compiler.SOURCE_PATHS.values():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / relative, target)


def test_source_byte_drift_fails_closed(tmp_path: Path) -> None:
    _copy_locked_sources(tmp_path)
    manifest = tmp_path / compiler.SOURCE_PATHS["manifest"]
    manifest.write_bytes(manifest.read_bytes() + b"\n")
    with pytest.raises(compiler.RuntimeLaneError, match="manifest source drift"):
        compiler.build_plan(tmp_path)


def test_advertised_gap_classification_source_byte_drift_fails_closed(
    tmp_path: Path,
) -> None:
    _copy_locked_sources(tmp_path)
    gap_plan = tmp_path / compiler.SOURCE_PATHS["advertised_gap_plan"]
    gap_plan.write_bytes(gap_plan.read_bytes() + b"\n")
    with pytest.raises(
        compiler.RuntimeLaneError, match="advertised_gap_plan source drift"
    ):
        compiler.build_plan(tmp_path)


def test_plan_tamper_and_evidence_injection_fail_closed(plan: dict) -> None:
    tampered = copy.deepcopy(plan)
    tampered["capability_bindings"][0]["lane_id"] = "external-optional"
    with pytest.raises(
        compiler.RuntimeLaneError, match="deterministic compiler output"
    ):
        compiler.validate_plan(tampered)

    evidence = copy.deepcopy(plan)
    evidence["capability_bindings"][0]["evidence"]["current_records"] = [
        {"claim": "unearned"}
    ]
    with pytest.raises(compiler.RuntimeLaneError, match="schema validation failed"):
        compiler.validate_plan(evidence)

    advertised_evidence = copy.deepcopy(plan)
    advertised_evidence["advertised_entry_bindings"][0]["runtime_evidence_records"] = [
        {"claim": "unearned"}
    ]
    with pytest.raises(compiler.RuntimeLaneError, match="schema validation failed"):
        compiler.validate_plan(advertised_evidence)


def test_unknown_family_classification_fails_closed() -> None:
    capability = {
        "id": "runtime.unreviewed.example",
        "feature_id": "unreviewed-family",
        "acceptance_class": "required_local",
    }
    with pytest.raises(compiler.RuntimeLaneError, match="unreviewed feature family"):
        compiler._capability_lane(capability)


def test_compiler_has_no_runtime_side_effect_imports() -> None:
    tree = ast.parse(COMPILER_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".", 1)[0])
    assert imported.isdisjoint(
        {"docker", "httpx", "requests", "socket", "subprocess", "urllib"}
    )
