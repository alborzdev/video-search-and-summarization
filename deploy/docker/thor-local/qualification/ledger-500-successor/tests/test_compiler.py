from __future__ import annotations

import ast
from collections import Counter
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
    "ledger_500_successor_compiler", PACKAGE / "compiler.py"
)
assert SPEC is not None and SPEC.loader is not None
compiler = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = compiler
SPEC.loader.exec_module(compiler)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def proof() -> dict:
    return load(compiler.PROOF_OUTPUT)


@pytest.fixture(scope="module")
def projected_manifest() -> dict:
    return load(compiler.MANIFEST_OUTPUT)


@pytest.fixture(scope="module")
def projected_ledger() -> dict:
    return load(compiler.LEDGER_OUTPUT)


@pytest.fixture(scope="module")
def current_manifest() -> dict:
    return load(REPO_ROOT / compiler.INPUTS["manifest"]["path"])


@pytest.fixture(scope="module")
def current_ledger() -> dict:
    return load(REPO_ROOT / compiler.INPUTS["official_capabilities"]["path"])


@pytest.fixture(scope="module")
def candidate() -> dict:
    return load(REPO_ROOT / compiler.INPUTS["candidate"]["path"])


@pytest.fixture(scope="module")
def adapter() -> dict:
    return load(REPO_ROOT / compiler.INPUTS["candidate_oracle_adapter"]["path"])


@pytest.fixture(scope="module")
def current_oracles() -> dict:
    return load(REPO_ROOT / compiler.INPUTS["capability_oracles"]["path"])


@pytest.fixture(scope="module")
def successor_oracles() -> dict:
    return load(REPO_ROOT / compiler.INPUTS["oracle_500_successor"]["path"])


@pytest.fixture(scope="module")
def official_schema() -> dict:
    return load(REPO_ROOT / compiler.INPUTS["official_capabilities_schema"]["path"])


@pytest.fixture(scope="module")
def manifest_schema() -> dict:
    return load(compiler.MANIFEST_SCHEMA)


def test_checked_outputs_are_exact_deterministic_projection(
    proof: dict, projected_manifest: dict, projected_ledger: dict
) -> None:
    compiled_proof, compiled_manifest, compiled_ledger = compiler.compile_projection()
    assert compiled_proof == proof
    assert compiled_manifest == projected_manifest
    assert compiled_ledger == projected_ledger
    assert compiler.PROOF_OUTPUT.read_bytes() == compiler._encoded(compiled_proof)
    assert compiler.MANIFEST_OUTPUT.read_bytes() == compiler._encoded(compiled_manifest)
    assert compiler.LEDGER_OUTPUT.read_bytes() == compiler._encoded(compiled_ledger)
    assert compiler.main(["--check"]) == 0


def test_all_schemas_are_valid_strict_and_outputs_validate(
    proof: dict,
    projected_manifest: dict,
    projected_ledger: dict,
    official_schema: dict,
    manifest_schema: dict,
) -> None:
    proof_schema = load(compiler.PROOF_SCHEMA)
    for schema in (proof_schema, manifest_schema, official_schema):
        Draft202012Validator.check_schema(schema)
    assert not list(Draft202012Validator(proof_schema).iter_errors(proof))
    assert not list(
        Draft202012Validator(manifest_schema).iter_errors(projected_manifest)
    )
    assert not list(Draft202012Validator(official_schema).iter_errors(projected_ledger))
    mutated = copy.deepcopy(proof)
    mutated["unexpected"] = True
    assert list(Draft202012Validator(proof_schema).iter_errors(mutated))
    mutated_manifest = copy.deepcopy(projected_manifest)
    mutated_manifest["features"][0].pop("official_capability_ids")
    assert list(Draft202012Validator(manifest_schema).iter_errors(mutated_manifest))


@pytest.mark.parametrize(
    "mutation",
    [
        "candidate_append_duplicate",
        "source_transition_duplicate",
        "source_partition_overlap",
        "family_blocker_duplicate",
        "coverage_blocker_duplicate",
        "external_distinction_duplicate",
    ],
)
def test_proof_schema_rejects_identity_replacement_and_overlap(
    proof: dict, mutation: str
) -> None:
    mutated = copy.deepcopy(proof)
    if mutation == "candidate_append_duplicate":
        rows = mutated["candidate_append_order"]
        rows[-1] = copy.deepcopy(rows[0])
    elif mutation == "source_transition_duplicate":
        rows = mutated["source_claim_hash_projection"]["transitions"]
        rows[-1] = copy.deepcopy(rows[0])
    elif mutation == "source_partition_overlap":
        projection = mutated["source_claim_hash_projection"]
        projection["unchanged_source_ids"][0] = projection["changed_source_ids"][0]
    elif mutation == "family_blocker_duplicate":
        rows = mutated["merge_readiness"]["blockers"]["family_status_aggregate_drift"]
        rows[-1] = copy.deepcopy(rows[0])
    elif mutation == "coverage_blocker_duplicate":
        rows = mutated["merge_readiness"]["blockers"][
            "acceptance_scenario_coverage_gaps"
        ]
        rows[-1] = copy.deepcopy(rows[0])
    elif mutation == "external_distinction_duplicate":
        rows = mutated["merge_readiness"]["reviewed_nonblocking_distinctions"][
            "external_candidate_thor_states"
        ]
        rows[-1] = copy.deepcopy(rows[0])
    else:  # pragma: no cover - parametrization is closed above
        raise AssertionError(mutation)
    schema = load(compiler.PROOF_SCHEMA)
    assert list(Draft202012Validator(schema).iter_errors(mutated)), mutation


def test_current_manifest_fields_are_preserved_except_capability_suffixes(
    current_manifest: dict, projected_manifest: dict
) -> None:
    assert current_manifest.keys() == projected_manifest.keys()
    for key in current_manifest:
        if key != "features":
            assert projected_manifest[key] == current_manifest[key]
    for before, after in zip(
        current_manifest["features"], projected_manifest["features"], strict=True
    ):
        before_fields = {
            k: v for k, v in before.items() if k != "official_capability_ids"
        }
        after_fields = {
            k: v for k, v in after.items() if k != "official_capability_ids"
        }
        assert after_fields == before_fields
        current_ids = before.get("official_capability_ids", [])
        assert after["official_capability_ids"][: len(current_ids)] == current_ids


def test_current_289_capabilities_and_derived_source_transition_are_exact(
    current_ledger: dict, projected_ledger: dict, proof: dict
) -> None:
    assert projected_ledger["capabilities"][:289] == current_ledger["capabilities"]
    assert projected_ledger["target"] == current_ledger["target"]
    assert (
        projected_ledger["source_discrepancies"]
        == current_ledger["source_discrepancies"]
    )
    assert len(projected_ledger["sources"]) == len(current_ledger["sources"]) == 126
    transitions = proof["source_claim_hash_projection"]["transitions"]
    assert len(transitions) == 126
    for before, after, transition in zip(
        current_ledger["sources"],
        projected_ledger["sources"],
        transitions,
        strict=True,
    ):
        assert {k: v for k, v in after.items() if k != "claim_set_sha256"} == {
            k: v for k, v in before.items() if k != "claim_set_sha256"
        }
        assert after["claim_set_sha256"] == compiler._source_claim_set_digest(
            after["id"], projected_ledger["capabilities"]
        )
        assert transition == {
            "source_id": before["id"],
            "current_claim_set_sha256": before["claim_set_sha256"],
            "projected_claim_set_sha256": after["claim_set_sha256"],
            "changed": before["claim_set_sha256"] != after["claim_set_sha256"],
        }
    assert sum(row["changed"] for row in transitions) == 17
    assert sum(not row["changed"] for row in transitions) == 109


def test_exact_211_capabilities_are_appended_in_manifest_pointer_order(
    candidate: dict, projected_ledger: dict, proof: dict
) -> None:
    ordered_entries = sorted(candidate["entries"], key=compiler._candidate_order_key)
    expected = [entry["proposed_capability"] for entry in ordered_entries]
    assert projected_ledger["capabilities"][289:] == expected
    assert [row["capability_id"] for row in proof["candidate_append_order"]] == [
        row["id"] for row in expected
    ]
    assert [row["manifest_pointer"] for row in proof["candidate_append_order"]] == [
        row["manifest_pointer"] for row in ordered_entries
    ]


def test_all_500_titles_map_exactly_once_in_the_same_family(
    projected_manifest: dict, projected_ledger: dict, proof: dict
) -> None:
    capability_by_id = {
        capability["id"]: capability for capability in projected_ledger["capabilities"]
    }
    mappings = []
    seen = set()
    for feature_index, feature in enumerate(projected_manifest["features"]):
        title_to_ids = {}
        for capability_id in feature["official_capability_ids"]:
            capability = capability_by_id[capability_id]
            assert capability["feature_id"] == feature["id"]
            title_to_ids.setdefault(capability["title"], []).append(capability_id)
        for advertised_index, advertised in enumerate(feature["advertised"]):
            assert len(title_to_ids[advertised]) == 1
            capability_id = title_to_ids[advertised][0]
            seen.add(capability_id)
            mappings.append(
                {
                    "manifest_pointer": f"/features/{feature_index}/advertised/{advertised_index}",
                    "feature_id": feature["id"],
                    "advertised": advertised,
                    "capability_id": capability_id,
                }
            )
    assert len(mappings) == len(seen) == len(capability_by_id) == 500
    assert proof["summary"]["exact_mapping_rows_sha256"] == compiler._sha_json(mappings)


def test_candidate_acceptance_runtime_and_nonadvancing_boundaries(
    projected_ledger: dict, proof: dict
) -> None:
    candidates = projected_ledger["capabilities"][289:]
    assert Counter(row["acceptance_class"] for row in candidates) == {
        "required_local": 159,
        "alternate_local_lane": 46,
        "external_optional": 6,
    }
    assert Counter(row["runtime_state"] for row in candidates) == {
        "not_qualified": 205,
        "not_applicable": 6,
    }
    assert all(
        "runtime_evidence" not in row for row in projected_ledger["capabilities"]
    )
    assert not any(
        row["runtime_state"] == "passed_current"
        for row in projected_ledger["capabilities"]
    )
    assert proof["policy"]["runtime_evidence"] == []
    assert proof["policy"]["can_promote_runtime_state"] is False
    assert proof["policy"]["required_cloud_inference"] is False


def test_adapter_and_current_oracle_preservation_are_directly_bound(
    adapter: dict, current_ledger: dict, current_oracles: dict, candidate: dict
) -> None:
    result = compiler._verify_adapter_preservation(
        adapter, current_ledger, current_oracles, candidate
    )
    assert result["current_oracle_count"] == 289
    assert result["current_oracle_evidence_record_count"] == 0
    assert result["explicit_authoritative_gap_binding_count"] == 74
    assert result["family_only_without_gap_binding_count"] == 137


def test_successor_oracle_id_set_order_and_ledger_bindings_are_exact(
    projected_ledger: dict, successor_oracles: dict
) -> None:
    capabilities = projected_ledger["capabilities"]
    oracles = successor_oracles["projected_oracles"]
    capability_ids = [row["id"] for row in capabilities]
    oracle_ids = [row["capability_id"] for row in oracles]
    assert len(capability_ids) == len(set(capability_ids)) == 500
    assert oracle_ids == capability_ids
    for capability, oracle in zip(capabilities, oracles, strict=True):
        assert oracle["ledger_binding"] == {
            key: capability[key]
            for key in (
                "title",
                "feature_id",
                "kind",
                "thor_state",
                "acceptance_class",
                "runtime_state",
                "source_claims",
                "gap",
                "contract",
            )
        }


def test_merge_blockers_are_exact_and_external_states_are_reviewed_nonblocking(
    proof: dict,
) -> None:
    readiness = proof["merge_readiness"]
    assert readiness["live_merge_ready"] is False
    assert readiness["verifier_blocker_categories"] == [
        "family_status_aggregate_drift",
        "acceptance_scenario_coverage_gaps",
    ]
    assert {
        row["feature_id"]
        for row in readiness["blockers"]["family_status_aggregate_drift"]
    } == {
        "video-summarization-live",
        "alert-notifications-slack",
        "rt-vlm-media",
        "vios-codecs-audio",
        "audio-understanding",
        "vios-ui",
        "agent-and-mcp-apis",
        "helm",
        "enterprise-rag",
    }
    assert len(readiness["blockers"]["acceptance_scenario_coverage_gaps"]) == 8
    distinctions = readiness["reviewed_nonblocking_distinctions"][
        "external_candidate_thor_states"
    ]
    assert len(distinctions) == 6
    assert all(
        row["candidate_thor_state"] in {"wired", "partial", "source_only"}
        and row["live_external_family_required_thor_state"] == "external_optional"
        for row in distinctions
    )


def test_no_excluded_warehouse_sample_marker(
    proof: dict, projected_ledger: dict
) -> None:
    serialized = json.dumps(
        {"proof": proof, "candidates": projected_ledger["capabilities"][289:]},
        sort_keys=True,
    ).lower()
    assert not any(
        marker in serialized for marker in compiler.EXCLUDED_WAREHOUSE_MARKERS
    )
    assert proof["policy"]["warehouse_sample_bundle"] == "excluded"
    assert proof["policy"]["custom_data_warehouse_capability"] == "in_scope"


def test_stale_source_claim_hash_fails_closed(
    current_manifest: dict,
    current_ledger: dict,
    projected_manifest: dict,
    projected_ledger: dict,
    proof: dict,
    official_schema: dict,
    manifest_schema: dict,
) -> None:
    mutated = copy.deepcopy(projected_ledger)
    changed_id = proof["source_claim_hash_projection"]["changed_source_ids"][0]
    current_source = next(
        row for row in current_ledger["sources"] if row["id"] == changed_id
    )
    projected_source = next(
        row for row in mutated["sources"] if row["id"] == changed_id
    )
    projected_source["claim_set_sha256"] = current_source["claim_set_sha256"]
    with pytest.raises(
        compiler.ProjectionError, match="source preservation/claim hash"
    ):
        compiler._verify_projection(
            current_manifest,
            current_ledger,
            projected_manifest,
            mutated,
            proof["candidate_append_order"],
            official_schema,
            manifest_schema,
        )


def test_non_hash_source_mutation_fails_closed(
    current_manifest: dict,
    current_ledger: dict,
    projected_manifest: dict,
    projected_ledger: dict,
    proof: dict,
    official_schema: dict,
    manifest_schema: dict,
) -> None:
    mutated = copy.deepcopy(projected_ledger)
    mutated["sources"][0]["version"] += "-drift"
    with pytest.raises(
        compiler.ProjectionError, match="source preservation/claim hash"
    ):
        compiler._verify_projection(
            current_manifest,
            current_ledger,
            projected_manifest,
            mutated,
            proof["candidate_append_order"],
            official_schema,
            manifest_schema,
        )


def test_current_capability_reorder_fails_closed(
    current_manifest: dict,
    current_ledger: dict,
    projected_manifest: dict,
    projected_ledger: dict,
    proof: dict,
    official_schema: dict,
    manifest_schema: dict,
) -> None:
    mutated = copy.deepcopy(projected_ledger)
    mutated["capabilities"][0], mutated["capabilities"][1] = (
        mutated["capabilities"][1],
        mutated["capabilities"][0],
    )
    with pytest.raises(compiler.ProjectionError, match="semantic/order preservation"):
        compiler._verify_projection(
            current_manifest,
            current_ledger,
            projected_manifest,
            mutated,
            proof["candidate_append_order"],
            official_schema,
            manifest_schema,
        )


def test_unauthorized_manifest_field_mutation_fails_closed(
    current_manifest: dict,
    current_ledger: dict,
    projected_manifest: dict,
    projected_ledger: dict,
    proof: dict,
    official_schema: dict,
    manifest_schema: dict,
) -> None:
    mutated = copy.deepcopy(projected_manifest)
    mutated["features"][0]["gap"] += " drift"
    with pytest.raises(compiler.ProjectionError, match="feature preservation"):
        compiler._verify_projection(
            current_manifest,
            current_ledger,
            mutated,
            projected_ledger,
            proof["candidate_append_order"],
            official_schema,
            manifest_schema,
        )


def test_candidate_title_mapping_mutation_fails_closed(
    current_manifest: dict,
    current_ledger: dict,
    projected_manifest: dict,
    projected_ledger: dict,
    proof: dict,
    official_schema: dict,
    manifest_schema: dict,
) -> None:
    mutated = copy.deepcopy(projected_ledger)
    mutated["capabilities"][289]["title"] += " drift"
    with pytest.raises(compiler.ProjectionError, match="exact-title mapping"):
        compiler._verify_projection(
            current_manifest,
            current_ledger,
            projected_manifest,
            mutated,
            proof["candidate_append_order"],
            official_schema,
            manifest_schema,
        )


def test_adapter_candidate_binding_mutation_fails_closed(
    current_manifest: dict, current_ledger: dict, candidate: dict, adapter: dict
) -> None:
    mutated = copy.deepcopy(adapter)
    row = next(iter(mutated["candidate_adapters_by_capability_id"].values()))
    row["candidate_entry_sha256"] = "0" * 64
    with pytest.raises(compiler.ProjectionError, match="adapter binding drift"):
        compiler._project(current_manifest, current_ledger, candidate, mutated)


def test_adapter_current_oracle_evidence_mutation_fails_closed(
    adapter: dict, current_ledger: dict, current_oracles: dict, candidate: dict
) -> None:
    mutated = copy.deepcopy(adapter)
    row = next(
        iter(mutated["current_oracle_preservation"]["by_capability_id"].values())
    )
    row["evidence"] = [{"invented": True}]
    with pytest.raises(compiler.ProjectionError, match="oracle preservation"):
        compiler._verify_adapter_preservation(
            mutated, current_ledger, current_oracles, candidate
        )


def test_duplicate_and_nonfinite_json_fail_closed() -> None:
    with pytest.raises(compiler.ProjectionError, match="duplicate JSON key"):
        compiler._strict_json(b'{"same":1,"same":2}', "adversarial")
    with pytest.raises(compiler.ProjectionError, match="non-finite"):
        compiler._strict_json(b'{"value":NaN}', "adversarial")


@pytest.mark.parametrize("relative", ["/etc/passwd", "../escape", "x/../../y"])
def test_unsafe_repository_paths_fail_closed(relative: str) -> None:
    with pytest.raises(compiler.ProjectionError, match="unsafe repository path"):
        compiler._repo_file(relative)


def test_symlink_repository_input_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    real = tmp_path / "real.json"
    real.write_text("{}\n", encoding="utf-8")
    (tmp_path / "linked.json").symlink_to(real)
    monkeypatch.setattr(compiler, "REPO_ROOT", tmp_path)
    with pytest.raises(compiler.ProjectionError, match="symlink"):
        compiler._repo_file("linked.json")


def test_atomic_writer_rejects_existing_symlink(tmp_path: Path) -> None:
    victim = tmp_path / "victim.json"
    victim.write_bytes(b"original\n")
    output = tmp_path / "projection.json"
    output.symlink_to(victim)
    with pytest.raises(compiler.ProjectionError, match="unsafe output path"):
        compiler._atomic_write(output, b"replacement\n")
    assert victim.read_bytes() == b"original\n"


def test_atomic_writer_rejects_symlinked_or_non_directory_parent(
    tmp_path: Path,
) -> None:
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(compiler.ProjectionError, match="unsafe output parent"):
        compiler._atomic_write(linked_parent / "projection.json", b"payload\n")
    assert not (real_parent / "projection.json").exists()
    not_directory = tmp_path / "not-directory"
    not_directory.write_bytes(b"regular file\n")
    with pytest.raises(compiler.ProjectionError, match="unsafe output parent"):
        compiler._atomic_write(not_directory / "projection.json", b"payload\n")


def test_compiler_is_static_and_all_integrity_locks_are_pinned() -> None:
    text = (PACKAGE / "compiler.py").read_text(encoding="utf-8")
    assert "TO_BE_PINNED" not in text
    tree = ast.parse(text)
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
