from __future__ import annotations

from collections import Counter
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest
from jsonschema import Draft202012Validator


PACKAGE = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE.parents[4]
COMPILER_PATH = PACKAGE / "compiler.py"
SPEC = importlib.util.spec_from_file_location(
    "execution_binding_registry", COMPILER_PATH
)
assert SPEC and SPEC.loader
compiler = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compiler)


def load_package(name: str) -> dict:
    return json.loads((PACKAGE / name).read_text(encoding="utf-8"))


def load_repo(relative: str) -> dict:
    return json.loads((REPO_ROOT / relative).read_text(encoding="utf-8"))


def test_checked_registry_exact_hashes() -> None:
    assert compiler.check() == {
        "admission_grade_bindings": 0,
        "binding_count": 208,
        "binding_rows_canonical_sha256": "0d8b334e25330d8f5142a6fff91cc13fc3ebf0c013a371e1f6b41334530c0924",
        "registry_raw_sha256": "af3927c15f9e5c1efb67690ee7ca3f3e6ee9fb77e720767db2264d68a935b6b5",
        "status": "ok",
    }


def test_exact_mapping_order_and_static_gaps() -> None:
    registry = load_package("registry.json")
    mapping = load_repo(compiler.MAPPING_PATH)["mappings"]
    rows = registry["bindings"]
    assert len(rows) == 208
    assert [row["registry_position"] for row in rows] == list(range(208))
    assert [row["mapping_position"] for row in rows] == [
        index for index in range(211) if index not in {101, 195, 196}
    ]
    assert all(row["oracle_index"] == 289 + row["mapping_position"] for row in rows)
    assert [row["candidate_id"] for row in rows] == [
        row["capability_id"] for row in mapping if row["mapping_state"] == "mapped"
    ]
    assert registry["static_gaps"] == [
        {
            "candidate_id": candidate_id,
            "mapping_position": position,
            "oracle_index": oracle_index,
            "state": "static_nonactivating_not_in_registry",
        }
        for position, oracle_index, candidate_id in compiler.EXPECTED_STATIC_GAPS
    ]


def test_exact_projection_and_cross_tier_counts() -> None:
    rows = load_package("registry.json")["bindings"]
    assert Counter(row["action_projection"]["tier"] for row in rows) == {
        "oracle_only": 127,
        "protocol": 23,
        "workload": 58,
    }
    assert Counter(row["observer_projection"]["tier"] for row in rows) == {
        "absent": 138,
        "guarded_adapter": 68,
        "production_subset": 2,
    }
    assert Counter(row["lane_projection"]["tier"] for row in rows) == {
        "exact_external": 4,
        "family_multi": 28,
        "family_single": 176,
    }
    assert Counter(row["cross_tier"] for row in rows) == {
        "both": 28,
        "enriched": 53,
        "observer": 42,
        "oracle": 85,
    }


def test_action_projections_match_mapping_integrity_hashes() -> None:
    rows = load_package("registry.json")["bindings"]
    mapping = load_repo(compiler.MAPPING_PATH)["mappings"]
    for row in rows:
        mapped = mapping[row["mapping_position"]]
        tier = row["action_projection"]["tier"]
        expected = (
            mapped["workload_binding_canonical_sha256"]
            if tier == "workload"
            else mapped["protocol_binding_canonical_sha256"]
            if tier == "protocol"
            else None
        )
        assert row["action_projection"]["binding_canonical_sha256"] == expected
        assert (
            len(row["action_projection"]["source_locators"])
            == {
                "oracle_only": 0,
                "protocol": 2,
                "workload": 1,
            }[tier]
        )


def test_semantic_surfaces_have_direct_normalized_locks() -> None:
    registry = load_package("registry.json")
    locator_locks = load_package("locator-locks.json")
    adapter = load_repo(compiler.ADAPTER_PATH)["candidate_adapters_by_capability_id"]
    assert locator_locks["summary"] == {
        "active_lane_file_references": 45,
        "active_lane_unique_files": 26,
        "semantic_base_files": 235,
        "semantic_locator_occurrences": 389,
        "semantic_unique_locators": 269,
    }
    locked_base = {
        item["path"]: item["raw_sha256"]
        for item in locator_locks["semantic_base_files"]
    }
    for row in registry["bindings"]:
        surfaces = adapter[row["candidate_id"]]["implementation_surfaces"]
        semantic = row["semantic_projection"]
        assert semantic["implementation_surface_count"] == len(surfaces)
        assert semantic["implementation_surfaces_canonical_sha256"] == compiler.sha256(
            compiler.canonical_bytes(surfaces)
        )
        for locator in surfaces:
            base, _ = compiler._normalize_locator(locator)
            assert base in locked_base


def test_every_direct_locator_lock_matches_current_regular_file() -> None:
    locator_locks = load_package("locator-locks.json")
    for group in ("semantic_base_files", "active_lane_files"):
        for item in locator_locks[group]:
            path = compiler._repo_path(item["path"])
            assert (
                compiler.sha256(compiler._read_regular(path, item["path"]))
                == item["raw_sha256"]
            )


def test_dependency_closure_recomputed_from_contract_order() -> None:
    rows = load_package("registry.json")["bindings"]
    bundles = load_repo(compiler.BUNDLE_PATH)["bundles"]
    bundle_by_id = {bundle["id"]: bundle for bundle in bundles}
    for row in rows:
        assert row["complete_dependency_closure"] == compiler._bundle_closure(
            bundle_by_id, row["leaf_bundle_id"]
        )


def test_observer_precedence_preserves_both_receipt_locators() -> None:
    rows = load_package("registry.json")["bindings"]
    production = [
        row for row in rows if row["observer_projection"]["tier"] == "production_subset"
    ]
    assert [row["candidate_id"] for row in production] == [
        "manifest-entry.video-summarization-live.05-sse-mcp-server",
        "manifest-entry.agent-and-mcp-apis.06-lvs-mcp",
    ]
    for row in production:
        assert [
            locator["source_id"]
            for locator in row["observer_projection"]["source_locators"]
        ] == ["wave8", "guarded"]
    guarded = load_repo(compiler.GUARDED_PATH)
    wave8 = load_repo(compiler.WAVE8_PATH)
    assert len(wave8["entries"]) == 2
    assert {row["capability_id"] for row in wave8["entries"]} <= {
        row["proposed_capability_id"] for row in guarded["results"]
    }


def test_lane_scopes_and_active_file_denominator() -> None:
    rows = load_package("registry.json")["bindings"]
    lanes = load_repo(compiler.LANE_PATH)
    by_pointer = {
        row["manifest_json_pointer"]: row for row in lanes["advertised_entry_bindings"]
    }
    locator_locks = load_package("locator-locks.json")
    assert locator_locks["active_lane_ids"] == [
        "alerts",
        "base",
        "custom-data-warehouse",
        "external-optional",
        "lvs",
        "search",
        "standalone-services",
    ]
    assert len(locator_locks["active_lane_files"]) == 26
    assert "deploy/docker/thor-local/official-edge/compose.yml" not in {
        item["path"] for item in locator_locks["active_lane_files"]
    }
    for row in rows:
        lane = by_pointer[row["manifest_pointer"]]
        expected_scope = (
            "entry_specific_gap_acceptance_boundary"
            if row["execution_boundary"] == "external"
            else "feature_family_reviewed_not_entry_specific"
        )
        assert lane["lane_binding_scope"] == expected_scope


def test_external_four_are_separate_and_never_local() -> None:
    registry = load_package("registry.json")
    assert registry["external_candidates"] == compiler.EXPECTED_EXTERNAL_IDS
    external = [
        row for row in registry["bindings"] if row["execution_boundary"] == "external"
    ]
    assert [row["candidate_id"] for row in external] == compiler.EXPECTED_EXTERNAL_IDS
    assert all(row["lane_projection"]["tier"] == "exact_external" for row in external)
    assert all(
        row["lane_projection"]["lane_ids"] == ["external-optional"] for row in external
    )


def test_authoritative_bindings_are_exactly_empty_and_non_admission_grade() -> None:
    rows = load_package("registry.json")["bindings"]
    empty = {
        "action_contract_sha256": None,
        "cleanup_executor": None,
        "cleanup_rollback_contract_sha256": None,
        "cleanup_targets": [],
        "compose_paths": [],
        "evidence_destination": None,
        "evidence_records": [],
        "executor": None,
        "postcondition_collectors": [],
        "profile_id": None,
        "profile_paths": [],
        "service_role_profile_binding_sha256": None,
        "service_roles": [],
    }
    assert all(not row["admission_grade"] for row in rows)
    assert all(row["authoritative_executable_binding"] == empty for row in rows)


def test_rebase_preserves_historical_meaning_and_locks_every_old_file() -> None:
    registry = load_package("registry.json")
    historical = load_repo(f"{compiler.HISTORICAL_DIR}/registry.json")
    assert [
        compiler._preserved_binding_semantics(row) for row in registry["bindings"]
    ] == [compiler._preserved_binding_semantics(row) for row in historical["bindings"]]
    assert registry["rebase_provenance"]["historical_package_locks"] == [
        {"path": path, "raw_sha256": digest}
        for path, digest in compiler.EXPECTED_HISTORICAL_HASHES.items()
    ]
    assert registry["summary"]["executable_bindings"] == 0
    assert registry["summary"]["promotion_bindings"] == 0


def test_exact_rebase_input_chain_is_present() -> None:
    provenance = load_package("registry.json")["rebase_provenance"]
    assert provenance["mapping_v2_raw_sha256"] == (
        "cb9bea95b4cfeab7c44441854e331a7093667d6b379fe0555692e5105ce4507f"
    )
    assert provenance["mapping_v2_schema_raw_sha256"] == (
        "78c118cc062eee15992ad3fcd4fa2d3585e6b80dc5bea7e32806ade1f11ccaba"
    )
    assert provenance["runtime_bundles_raw_sha256"] == (
        "415931c48a231c150c62d90e134da5f60a75adb8bed653dcef45251ef6caf194"
    )
    assert provenance["runtime_bundles_schema_raw_sha256"] == (
        "2f277445317a052be2399af5f4e6b4ea8c85e3998d5acd67f03aab24b1b2eabe"
    )
    assert provenance["wave1_contract_raw_sha256"] == (
        "fae464894d7d565a1078f852776bb005e0426c4280473d551bbec3e727e2d53c"
    )
    assert provenance["wave1_receipt_raw_sha256"] == (
        "ab07eac3e5c240f55d2480fe34aa5128be0cd62b3a64027e3ae689cb27bd0396"
    )
    assert provenance["wave1_successor_raw_sha256"] == (
        "1a066029a04bc67bcefd4571f24fce1cda1df275ab48aed48f99ea7e274f10b5"
    )


def test_warehouse_cloud_and_runtime_evidence_are_excluded() -> None:
    registry = load_package("registry.json")
    mapping = load_repo(compiler.MAPPING_PATH)["mappings"]
    assert registry["policy"]["warehouse_sample_bundle"] == "excluded"
    assert registry["policy"]["required_cloud_inference"] is False
    assert all(
        row["warehouse_sample_bundle"] == "excluded" for row in registry["bindings"]
    )
    assert all(
        not row["warehouse_sample_bundle"] and not row["required_cloud_inference"]
        for row in mapping
        if row["mapping_state"] == "mapped"
    )


def test_schemas_are_strict_and_cross_projection_tiers_fail() -> None:
    schema = load_package("registry.schema.json")
    locator_schema = load_package("locator-locks.schema.json")
    Draft202012Validator.check_schema(schema)
    Draft202012Validator.check_schema(locator_schema)
    artifact = load_package("registry.json")
    mutated = copy.deepcopy(artifact)
    mutated["unexpected"] = True
    assert list(Draft202012Validator(schema).iter_errors(mutated))
    action_schema = {"$defs": schema["$defs"], "$ref": "#/$defs/action_projection"}
    assert list(
        Draft202012Validator(action_schema).iter_errors(
            {
                "binding_canonical_sha256": None,
                "source_locators": [],
                "tier": "guarded_adapter",
            }
        )
    )


def test_duplicate_json_nonfinite_unsafe_path_and_symlink_fail(tmp_path: Path) -> None:
    with pytest.raises(compiler.RegistryError, match="duplicate JSON key"):
        compiler.strict_json(b'{"a":1,"a":2}', "duplicate")
    with pytest.raises(compiler.RegistryError, match="non-finite"):
        compiler.strict_json(b'{"a":Infinity}', "infinity")
    with pytest.raises(compiler.RegistryError, match="unsafe repository path"):
        compiler._repo_path("../outside")
    target = tmp_path / "target"
    target.write_text("safe", encoding="utf-8")
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(compiler.RegistryError, match="regular non-symlink"):
        compiler._read_regular(link, "link")


@pytest.mark.parametrize(
    "argument", ["--emit", "--execute", "--write", "--run", "--action"]
)
def test_cli_rejects_every_non_check_mode(argument: str) -> None:
    result = subprocess.run(
        [sys.executable, str(COMPILER_PATH), argument],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env={"PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 2


def test_cli_check_is_read_only_and_does_not_invoke_historical_executors() -> None:
    before = {
        path.relative_to(PACKAGE).as_posix(): path.stat().st_mtime_ns
        for path in PACKAGE.rglob("*")
        if path.is_file()
    }
    result = subprocess.run(
        [sys.executable, str(COMPILER_PATH), "--check"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env={"PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 0, result.stderr
    after = {
        path.relative_to(PACKAGE).as_posix(): path.stat().st_mtime_ns
        for path in PACKAGE.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert (
        load_package("registry.json")["policy"]["historical_executors_invoked"] is False
    )
