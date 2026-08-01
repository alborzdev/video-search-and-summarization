from __future__ import annotations

import ast
import copy
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
    "advertised_entry_coverage_compiler", PACKAGE / "compiler.py"
)
assert SPEC is not None and SPEC.loader is not None
compiler = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = compiler
SPEC.loader.exec_module(compiler)


@pytest.fixture(scope="module")
def documents() -> dict[str, dict]:
    return {
        name: json.loads((REPO_ROOT / relative).read_text(encoding="utf-8"))
        for name, relative in compiler.SOURCE_PATHS.items()
    }


@pytest.fixture(scope="module")
def coverage() -> dict:
    return json.loads(compiler.COVERAGE_PATH.read_text(encoding="utf-8"))


def compile_with(documents: dict[str, dict], **overrides: dict) -> dict:
    selected = {**documents, **overrides}
    locks = {
        name: {
            "path": compiler.SOURCE_PATHS[name],
            "raw_sha256": compiler.SOURCE_RAW_SHA256[name],
            "canonical_sha256": compiler.SOURCE_CANONICAL_SHA256[name],
        }
        for name in compiler.SOURCE_PATHS
    }
    return compiler.compile_documents(
        selected["manifest"],
        selected["official_capabilities"],
        selected["capability_oracles"],
        selected["advertised_gap_plan"],
        selected["runtime_lane_plan"],
        locks,
    )


def capability(document: dict, capability_id: str) -> dict:
    return next(item for item in document["capabilities"] if item["id"] == capability_id)


def oracle(document: dict, capability_id: str) -> dict:
    return next(
        item for item in document["oracles"] if item["capability_id"] == capability_id
    )


def test_checked_coverage_is_exact_deterministic_output(coverage: dict) -> None:
    compiler.validate_coverage(coverage)
    assert coverage == compiler.build_coverage()
    assert compiler.COVERAGE_PATH.read_bytes() == compiler._encoded(coverage)
    assert compiler.main(["--check"]) == 0


def test_schema_is_draft_2020_12_and_checked_document_conforms(coverage: dict) -> None:
    schema = json.loads(compiler.SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    Draft202012Validator.check_schema(schema)
    assert list(Draft202012Validator(schema).iter_errors(coverage)) == []


def test_exact_global_denominators_and_exclusive_classes(coverage: dict) -> None:
    summary = coverage["summary"]
    assert summary["feature_families"] == 55
    assert summary["advertised_entries"] == 500
    assert summary["mapping_class_counts"] == compiler.EXPECTED_MAPPING_COUNTS
    assert summary["semantic_exact_mappings"] == 289
    assert summary["semantic_blockers"] == 211
    assert summary["local_runtime_blockers"] == 464
    assert len(coverage["entries"]) == 500
    pointers = [item["manifest_pointer"] for item in coverage["entries"]]
    assert len(pointers) == len(set(pointers)) == 500


def test_exact_mappings_bind_title_feature_source_and_oracle(
    coverage: dict, documents: dict[str, dict]
) -> None:
    caps = {
        item["id"]: item
        for item in documents["official_capabilities"]["capabilities"]
    }
    oracles = {
        item["capability_id"]: item
        for item in documents["capability_oracles"]["oracles"]
    }
    exact = [
        item
        for item in coverage["entries"]
        if item["mapping_class"]
        in {"exact_existing_capability", "canonical_entry_capability"}
    ]
    assert len(exact) == 289
    for item in exact:
        assert len(item["capability_ids"]) == len(item["oracle_ids"]) == 1
        capability_id = item["capability_ids"][0]
        cap = caps[capability_id]
        bound_oracle = oracles[capability_id]
        assert cap["title"] == item["advertised"]
        assert cap["feature_id"] == item["feature_id"]
        assert cap["source_claims"]
        assert item["oracle_ids"] == [f"oracle.{capability_id}"]
        assert bound_oracle["ledger_binding"]["title"] == item["advertised"]
        assert bound_oracle["evidence"] == []
        assert item["semantic_match_basis"]["exact_title_match"]
        assert item["semantic_match_basis"]["exact_feature_match"]


def test_canonical_namespace_and_exact_existing_namespace_are_disjoint(
    coverage: dict,
) -> None:
    canonical = [
        item
        for item in coverage["entries"]
        if item["mapping_class"] == "canonical_entry_capability"
    ]
    existing = [
        item
        for item in coverage["entries"]
        if item["mapping_class"] == "exact_existing_capability"
    ]
    assert len(canonical) == 13
    assert len(existing) == 276
    assert all(item["capability_ids"][0].startswith("manifest-entry.") for item in canonical)
    assert all(not item["capability_ids"][0].startswith("manifest-entry.") for item in existing)


def test_open_gaps_and_family_only_rows_are_fail_closed(coverage: dict) -> None:
    gaps = [
        item
        for item in coverage["entries"]
        if item["mapping_class"] == "explicit_missing_entry_gap"
    ]
    family_only = [
        item
        for item in coverage["entries"]
        if item["mapping_class"] == "family_only_unreviewed"
    ]
    assert len(gaps) == 74
    assert len(family_only) == 137
    assert all(item["gap_reference"] is not None for item in gaps)
    assert all(item["capability_ids"] == item["oracle_ids"] == [] for item in gaps)
    assert all(item["family_capability_ids"] for item in family_only)
    assert all(item["gap_reference"] is None for item in family_only)
    assert all(item["capability_ids"] == item["oracle_ids"] == [] for item in family_only)
    assert all(item["blocks_literal_semantic_completeness"] for item in gaps + family_only)


def test_acceptance_and_local_obligation_are_orthogonal(coverage: dict) -> None:
    assert coverage["summary"]["acceptance_class_counts"] == compiler.EXPECTED_ACCEPTANCE_COUNTS
    assert coverage["summary"]["local_parity_obligation_counts"] == compiler.EXPECTED_OBLIGATION_COUNTS
    for item in coverage["entries"]:
        expected = compiler._obligation(item["acceptance_class"])
        assert item["local_parity_obligation"] == expected
        assert item["blocks_local_runtime_completeness"] == (
            expected != "external_excluded"
        )
    external = [item for item in coverage["entries"] if item["acceptance_class"] == "external_optional"]
    assert len(external) == 36
    assert all(item["local_parity_obligation"] == "external_excluded" for item in external)
    assert all(
        item["runtime_default_lane_id"] == "external-optional"
        and item["runtime_lane_ids"] == ["external-optional"]
        for item in external
    )
    assert all(
        item["runtime_default_lane_id"] != "external-optional"
        for item in coverage["entries"]
        if item["acceptance_class"] != "external_optional"
    )


def test_no_runtime_promotion_evidence_cloud_requirement_or_warehouse_sample(
    coverage: dict,
) -> None:
    assert coverage["policy"]["mapping_is_runtime_evidence"] is False
    assert coverage["policy"]["can_promote_runtime_state"] is False
    assert coverage["policy"]["required_cloud_inference"] is False
    assert coverage["policy"]["warehouse_sample_bundle"] == "excluded"
    assert coverage["policy"]["runtime_evidence"] == []
    assert coverage["summary"]["runtime_evidence_records"] == 0
    assert coverage["summary"]["warehouse_sample_bundle_entries"] == 0
    assert all(item["runtime_evidence_ids"] == [] for item in coverage["entries"])
    assert all(not item["mapping_is_runtime_evidence"] for item in coverage["entries"])
    assert all(not item["warehouse_sample_bundle_required"] for item in coverage["entries"])


def test_adversarial_exact_title_drift_fails(
    documents: dict[str, dict]
) -> None:
    official = copy.deepcopy(documents["official_capabilities"])
    capability(official, "evaluation.agent.report")["title"] += " drift"
    with pytest.raises(compiler.CoverageError):
        compile_with(documents, official_capabilities=official)


def test_adversarial_feature_binding_drift_fails(
    documents: dict[str, dict]
) -> None:
    official = copy.deepcopy(documents["official_capabilities"])
    capability(official, "evaluation.agent.report")["feature_id"] = "wrong-family"
    with pytest.raises(compiler.CoverageError, match="feature binding drift"):
        compile_with(documents, official_capabilities=official)


def test_adversarial_missing_source_claim_or_oracle_fails(
    documents: dict[str, dict]
) -> None:
    official = copy.deepcopy(documents["official_capabilities"])
    capability(official, "evaluation.agent.report")["source_claims"] = []
    with pytest.raises(compiler.CoverageError, match="no source claims"):
        compile_with(documents, official_capabilities=official)

    oracles = copy.deepcopy(documents["capability_oracles"])
    oracles["oracles"] = [
        item
        for item in oracles["oracles"]
        if item["capability_id"] != "evaluation.agent.report"
    ]
    with pytest.raises(compiler.CoverageError, match="denominator drift"):
        compile_with(documents, capability_oracles=oracles)


def test_adversarial_ambiguous_title_or_gap_overlap_fails(
    documents: dict[str, dict]
) -> None:
    official = copy.deepcopy(documents["official_capabilities"])
    capability(official, "evaluation.agent.qa")["title"] = "Agent report evaluator"
    with pytest.raises(compiler.CoverageError, match="ambiguous"):
        compile_with(documents, official_capabilities=official)

    official = copy.deepcopy(documents["official_capabilities"])
    capability(
        official, "manifest-entry.vios-codecs-audio.05-cpu-multimedia-support"
    )["title"] = "B-frame handling"
    with pytest.raises(compiler.CoverageError, match="overlaps explicit gap"):
        compile_with(documents, official_capabilities=official)


def test_adversarial_runtime_mapping_or_pointer_drift_fails(
    documents: dict[str, dict]
) -> None:
    runtime = copy.deepcopy(documents["runtime_lane_plan"])
    runtime["advertised_entry_bindings"][0]["entry_specific_capability_ids"] = [
        "invented.capability"
    ]
    with pytest.raises(compiler.CoverageError, match="runtime-lane semantic mapping drift"):
        compile_with(documents, runtime_lane_plan=runtime)

    runtime = copy.deepcopy(documents["runtime_lane_plan"])
    runtime["advertised_entry_bindings"][1]["manifest_json_pointer"] = runtime[
        "advertised_entry_bindings"
    ][0]["manifest_json_pointer"]
    with pytest.raises(compiler.CoverageError, match="duplicate manifest_json_pointer"):
        compile_with(documents, runtime_lane_plan=runtime)


def test_adversarial_external_and_local_default_lane_drift_fails(
    documents: dict[str, dict]
) -> None:
    runtime = copy.deepcopy(documents["runtime_lane_plan"])
    external = next(
        item
        for item in runtime["advertised_entry_bindings"]
        if item["manifest_json_pointer"] == "/features/39/advertised/5"
    )
    external["default_lane_id"] = "standalone-services"
    with pytest.raises(compiler.CoverageError, match="external optional entry escaped"):
        compile_with(documents, runtime_lane_plan=runtime)

    runtime = copy.deepcopy(documents["runtime_lane_plan"])
    external = next(
        item
        for item in runtime["advertised_entry_bindings"]
        if item["manifest_json_pointer"] == "/features/39/advertised/5"
    )
    external["lane_ids"] = ["external-optional", "standalone-services"]
    with pytest.raises(compiler.CoverageError, match="external optional entry escaped"):
        compile_with(documents, runtime_lane_plan=runtime)

    runtime = copy.deepcopy(documents["runtime_lane_plan"])
    local = next(
        item
        for item in runtime["advertised_entry_bindings"]
        if item["manifest_json_pointer"] == "/features/0/advertised/0"
    )
    local["default_lane_id"] = "external-optional"
    with pytest.raises(compiler.CoverageError, match="defaults to external-optional"):
        compile_with(documents, runtime_lane_plan=runtime)


def test_adversarial_runtime_evidence_or_warehouse_fixture_fails(
    documents: dict[str, dict]
) -> None:
    oracles = copy.deepcopy(documents["capability_oracles"])
    oracle(oracles, "evaluation.agent.report")["evidence"] = ["fabricated"]
    with pytest.raises(compiler.CoverageError, match="runtime evidence is forbidden"):
        compile_with(documents, capability_oracles=oracles)

    oracles = copy.deepcopy(documents["capability_oracles"])
    oracle(oracles, "evaluation.agent.report")["fixture"][
        "warehouse_sample_bundle"
    ] = True
    with pytest.raises(compiler.CoverageError, match="Warehouse sample fixture"):
        compile_with(documents, capability_oracles=oracles)


def test_schema_rejects_false_promotion_class_overlap_and_external_locality(
    coverage: dict,
) -> None:
    schema = json.loads(compiler.SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)

    promoted = copy.deepcopy(coverage)
    promoted["entries"][0]["runtime_evidence_ids"] = ["fabricated"]
    assert list(validator.iter_errors(promoted))

    gap_index = next(
        index
        for index, item in enumerate(coverage["entries"])
        if item["mapping_class"] == "explicit_missing_entry_gap"
    )
    overlap = copy.deepcopy(coverage)
    overlap["entries"][gap_index]["capability_ids"] = ["invented.capability"]
    assert list(validator.iter_errors(overlap))

    external_index = next(
        index
        for index, item in enumerate(coverage["entries"])
        if item["acceptance_class"] == "external_optional"
    )
    localized = copy.deepcopy(coverage)
    localized["entries"][external_index]["local_parity_obligation"] = "required"
    assert list(validator.iter_errors(localized))

    escaped = copy.deepcopy(coverage)
    escaped["entries"][external_index]["runtime_default_lane_id"] = (
        "standalone-services"
    )
    assert list(validator.iter_errors(escaped))

    local_index = next(
        index
        for index, item in enumerate(coverage["entries"])
        if item["acceptance_class"] != "external_optional"
    )
    externalized = copy.deepcopy(coverage)
    externalized["entries"][local_index]["runtime_default_lane_id"] = (
        "external-optional"
    )
    assert list(validator.iter_errors(externalized))


def test_source_locks_are_strict_regular_files(tmp_path: Path) -> None:
    path = tmp_path / "source.json"
    path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(compiler.CoverageError, match="raw digest drift"):
        compiler._load_locked_json(path, "0" * 64)
    symlink = tmp_path / "source-link.json"
    symlink.symlink_to(path)
    with pytest.raises(compiler.CoverageError, match="not a regular"):
        compiler._load_locked_json(symlink)


def test_compiler_has_no_network_docker_subprocess_or_product_imports() -> None:
    tree = ast.parse((PACKAGE / "compiler.py").read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not imported & {
        "docker",
        "requests",
        "httpx",
        "socket",
        "subprocess",
        "services",
        "vss",
    }
