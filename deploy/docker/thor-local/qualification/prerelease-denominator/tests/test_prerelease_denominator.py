from __future__ import annotations

import ast
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path

import jsonschema
import pytest

HERE = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location(
        "prerelease_denominator_validator", HERE / "validator.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load(name: str) -> dict:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def validated_result():
    return _module().validate_denominator()


def test_full_offline_denominator_validation(validated_result):
    assert validated_result["status"] == "static_denominator_valid"
    assert validated_result["counts"]["develop_side_commits"] == 498
    assert validated_result["counts"]["develop_side_path_status_records"] == 109052
    assert validated_result["counts"]["main_only_exceptions"] == 2


def test_evidence_ceiling_is_nonruntime_and_nonpromoting(validated_result):
    assert validated_result["evidence_ceiling"] == (
        "commit_tree_and_path_status_metadata_only"
    )
    assert validated_result["runtime_parity_claimed"] is False
    assert validated_result["runtime_evidence"] == []
    assert validated_result["official_capability_promotions"] == 0


def test_all_json_documents_have_strict_valid_schemas(validated_result):
    pairs = [
        ("classification-rules.json", "classification-rules.schema.json"),
        ("denominator.json", "denominator.schema.json"),
        ("result.schema.json", "result.schema.json"),
    ]
    for document_name, schema_name in pairs:
        schema = _load(schema_name)
        jsonschema.Draft202012Validator.check_schema(schema)
        if document_name != schema_name:
            jsonschema.Draft202012Validator(schema).validate(_load(document_name))
    jsonschema.Draft202012Validator(_load("result.schema.json")).validate(
        validated_result
    )
    jsonschema.Draft202012Validator.check_schema(
        _load("path-status-record.schema.json")
    )


def test_exact_commit_sequences_and_main_exceptions_are_unique():
    denominator = _load("denominator.json")
    develop = denominator["develop_side_commits"]
    exceptions = denominator["main_only_exceptions"]
    assert len(develop) == 498
    assert len({commit["sha"] for commit in develop}) == 498
    assert [commit["sha"] for commit in exceptions] == [
        "dc3746db57a008a0be203eaa0c130c6cb94a2661",
        "7732edf8fb38ef896b20f2a0a6a701a4db10dc57",
    ]
    assert not ({commit["sha"] for commit in develop} & {c["sha"] for c in exceptions})


def test_every_commit_has_a_replayable_classification_trace():
    denominator = _load("denominator.json")
    commits = denominator["develop_side_commits"] + denominator["main_only_exceptions"]
    assert all(commit["classifications"] for commit in commits)
    assert all(commit["classification_rule_ids"] for commit in commits)
    assert all(commit["change_count"] >= 1 for commit in commits)
    assert (
        denominator["counts"]["classification_counts"]["excluded-warehouse-sample"] == 0
    )


def test_fourteen_candidate_families_match_curated_watchlist_exactly():
    rules = _load("classification-rules.json")
    watchlist = json.loads(
        (HERE.parent / "prerelease-watchlist" / "manifest.json").read_text()
    )
    assert rules["candidate_family_ids"] == [
        family["family_id"] for family in watchlist["families"]
    ]


def test_path_sidecar_is_compact_deterministic_gzip():
    denominator = _load("denominator.json")
    compressed = (HERE / "path-status.jsonl.gz").read_bytes()
    raw = gzip.decompress(compressed)
    assert len(compressed) == 789321
    assert len(raw) == 25039231
    assert (
        hashlib.sha256(compressed).hexdigest()
        == (denominator["digests"]["path_status_gzip_sha256"])
    )
    assert (
        hashlib.sha256(raw).hexdigest()
        == (denominator["digests"]["path_status_jsonl_sha256"])
    )


def test_runtime_claim_cannot_be_injected(tmp_path, monkeypatch):
    module = _module()
    denominator = _load("denominator.json")
    denominator["runtime_parity_claimed"] = True
    path = tmp_path / "denominator.json"
    path.write_text(json.dumps(denominator), encoding="utf-8")
    monkeypatch.setattr(module, "DENOMINATOR_PATH", path)
    with pytest.raises(module.DenominatorError, match="denominator schema validation"):
        module.validate_denominator()


def test_duplicate_denominator_key_is_rejected(tmp_path, monkeypatch):
    module = _module()
    raw = (HERE / "denominator.json").read_text(encoding="utf-8")
    raw = raw.replace(
        '"schema_version": 1,',
        '"schema_version": 1,\n  "schema_version": 1,',
        1,
    )
    path = tmp_path / "denominator.json"
    path.write_text(raw, encoding="utf-8")
    monkeypatch.setattr(module, "DENOMINATOR_PATH", path)
    with pytest.raises(module.DenominatorError, match="duplicate JSON key"):
        module.validate_denominator()


def test_compressed_sidecar_drift_fails_before_decompression(tmp_path, monkeypatch):
    module = _module()
    path = tmp_path / "path-status.jsonl.gz"
    path.write_bytes((HERE / "path-status.jsonl.gz").read_bytes()[:-1])
    monkeypatch.setattr(module, "PATH_STATUS_PATH", path)
    with pytest.raises(
        module.DenominatorError, match="compressed path-status byte count"
    ):
        module.validate_denominator()


@pytest.mark.parametrize("unsafe", ["../escape", "/absolute", "a\\b", "a\nb"])
def test_unsafe_paths_are_rejected(unsafe):
    module = _module()
    with pytest.raises(module.DenominatorError, match="unsafe path"):
        module._safe_path(unsafe, 1)


def test_sidecar_schema_rejects_unknown_fields():
    schema = _load("path-status-record.schema.json")
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(
            {
                "commit": "0" * 40,
                "path": "README.md",
                "range": "develop_side",
                "status": "M",
                "runtime_passed": True,
            }
        )


def test_offline_validator_imports_no_process_or_network_modules():
    tree = ast.parse((HERE / "validator.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint(
        {"subprocess", "socket", "requests", "urllib", "httpx", "docker"}
    )


def test_generator_forbids_lazy_fetch_and_contains_no_fetch_command():
    source = (HERE / "generate.py").read_text(encoding="utf-8")
    assert 'env["GIT_NO_LAZY_FETCH"] = "1"' in source
    assert '"fetch"' not in source
    assert '"pull"' not in source
    assert '"--no-renames"' in source
