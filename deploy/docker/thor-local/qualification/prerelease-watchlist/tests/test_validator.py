from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
from pathlib import Path

import jsonschema
import pytest

HERE = Path(__file__).resolve().parents[1]
REPO_ROOT = HERE.parents[4]


def _module():
    spec = importlib.util.spec_from_file_location(
        "prerelease_watchlist_validator", HERE / "validator.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_manifest() -> dict:
    return json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))


def _write_manifest(tmp_path: Path, manifest: dict) -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_manifest_and_result_validate_against_strict_schemas():
    module = _module()
    manifest = _load_manifest()
    result = module.validate_manifest()
    manifest_schema = json.loads((HERE / "manifest.schema.json").read_text())
    result_schema = json.loads((HERE / "result.schema.json").read_text())
    jsonschema.Draft202012Validator.check_schema(manifest_schema)
    jsonschema.Draft202012Validator.check_schema(result_schema)
    jsonschema.Draft202012Validator(manifest_schema).validate(manifest)
    jsonschema.Draft202012Validator(result_schema).validate(result)


def test_exact_fourteen_family_accounting_and_zero_promotion():
    result = _module().validate_manifest()
    assert result["counts"] == {
        "families": 14,
        "candidate_static": 14,
        "runtime_watchlist": 14,
        "source_pointers": 40,
        "excluded_exceptions": 1,
        "conflict_exceptions": 1,
        "passed_current_promotions": 0,
    }
    assert len(result["family_results"]) == 14
    assert all(
        item["static_status"] == "pointer_locked_candidate"
        and item["runtime_status"] == "watchlist_not_executed"
        and item["runtime_evidence"] == []
        for item in result["family_results"]
    )
    assert result["runtime_evidence"] == []
    assert result["official_baseline_status"] == "unchanged"
    assert result["coverage_limit"] == {
        "selection_basis": "curated_prerelease_candidate_watchlist",
        "authoritative_full_diff_denominator": None,
        "exhaustive_develop_coverage_claimed": False,
        "coverage_fraction": "not_computable",
    }


def test_manifest_canonical_lock_covers_all_semantic_prose():
    module = _module()
    manifest = _load_manifest()
    assert module._canonical_sha256(manifest) == (
        module.EXPECTED_MANIFEST_CANONICAL_SHA256
    )
    assert manifest["evidence_strategy"] == {
        "mode": "locked_remote_pointer_only",
        "selection_basis": "curated_prerelease_candidate_watchlist",
        "offline_validation": True,
        "content_validation": "not_performed_without_materialized_upstream_tree",
        "qualification_ceiling": "locked_remote_pointers_only",
        "authoritative_full_diff_denominator": None,
        "exhaustive_develop_coverage_claimed": False,
        "coverage_fraction": "not_computable",
    }


def test_exact_conflict_and_exclusion_are_preserved():
    manifest = _load_manifest()
    exceptions = {
        family["family_id"]: family["exceptions"]
        for family in manifest["families"]
        if family["exceptions"]
    }
    assert exceptions["build-vision-agent"][0]["exception_id"] == (
        "deprecated-thor-edge-4b"
    )
    assert exceptions["build-vision-agent"][0]["disposition"] == "conflict"
    assert exceptions["sdrc-configurator"][0]["exception_id"] == (
        "warehouse-sample-bundle"
    )
    assert exceptions["sdrc-configurator"][0]["disposition"] == "excluded"


def test_nonadvancing_policy_is_exact():
    assert _load_manifest()["policies"] == {
        "official_baseline": False,
        "live_ledger_mutation_allowed": False,
        "runtime_evidence_allowed": False,
        "promotion_allowed": False,
        "passed_current_allowed": False,
        "network_required": False,
        "local_develop_checkout_required": False,
        "warehouse_sample_required": False,
    }


def test_validator_does_not_modify_stable_or_live_ledgers():
    paths = [
        REPO_ROOT / "deploy/docker/thor-local/qualification/acceptance_inventory.json",
        REPO_ROOT / "deploy/docker/thor-local/parity/capability-oracles.json",
        REPO_ROOT
        / "deploy/docker/thor-local/qualification/runtime-lanes/runtime-lane-plan.json",
    ]
    before = [_digest(path) for path in paths]
    _module().validate_manifest()
    assert [_digest(path) for path in paths] == before


def test_unknown_property_fails_strict_schema(tmp_path, monkeypatch):
    module = _module()
    manifest = _load_manifest()
    manifest["families"][0]["official_status"] = "candidate"
    monkeypatch.setattr(module, "MANIFEST_PATH", _write_manifest(tmp_path, manifest))
    with pytest.raises(module.WatchlistError, match="manifest schema validation"):
        module.validate_manifest()


def test_duplicate_json_key_is_rejected(tmp_path, monkeypatch):
    module = _module()
    raw = (HERE / "manifest.json").read_text(encoding="utf-8")
    duplicate = raw.replace(
        '"schema_version": 1,',
        '"schema_version": 1,\n  "schema_version": 1,',
        1,
    )
    path = tmp_path / "manifest.json"
    path.write_text(duplicate, encoding="utf-8")
    monkeypatch.setattr(module, "MANIFEST_PATH", path)
    with pytest.raises(module.WatchlistError, match="duplicate JSON key"):
        module.validate_manifest()


def test_family_identity_or_order_drift_fails_closed(tmp_path, monkeypatch):
    module = _module()
    manifest = _load_manifest()
    manifest["families"][0], manifest["families"][1] = (
        manifest["families"][1],
        manifest["families"][0],
    )
    monkeypatch.setattr(module, "MANIFEST_PATH", _write_manifest(tmp_path, manifest))
    with pytest.raises(module.WatchlistError, match="14-family order or identity"):
        module.validate_manifest()


def test_source_path_traversal_is_rejected(tmp_path, monkeypatch):
    module = _module()
    manifest = _load_manifest()
    pointer = manifest["families"][0]["source_pointers"][0]
    pointer["path"] = "../SKILL.md"
    pointer["source_url"] = (
        "https://github.com/NVIDIA-AI-Blueprints/video-search-and-summarization/blob/"
        "708dac2ff071c76971d5cc8cab24f3879e6aac63/../SKILL.md"
    )
    monkeypatch.setattr(module, "MANIFEST_PATH", _write_manifest(tmp_path, manifest))
    with pytest.raises(module.WatchlistError, match="unsafe upstream source path"):
        module.validate_manifest()


def test_wrong_source_ref_or_url_fails_closed(tmp_path, monkeypatch):
    module = _module()
    manifest = _load_manifest()
    manifest["families"][0]["source_pointers"][0]["source_ref"] = "0" * 40
    monkeypatch.setattr(module, "MANIFEST_PATH", _write_manifest(tmp_path, manifest))
    with pytest.raises(module.WatchlistError, match="manifest schema validation"):
        module.validate_manifest()


def test_introducing_commit_drift_fails_closed(tmp_path, monkeypatch):
    module = _module()
    manifest = _load_manifest()
    pointer = manifest["families"][0]["source_pointers"][0]
    pointer["introducing_commit"] = "0" * 40
    pointer["introducing_commit_url"] = (
        "https://github.com/NVIDIA-AI-Blueprints/video-search-and-summarization/commit/"
        + "0" * 40
    )
    monkeypatch.setattr(module, "MANIFEST_PATH", _write_manifest(tmp_path, manifest))
    with pytest.raises(module.WatchlistError, match="source pointer set drifted"):
        module.validate_manifest()


def test_passed_current_value_is_forbidden(tmp_path, monkeypatch):
    module = _module()
    manifest = _load_manifest()
    manifest["families"][0]["summary"] = "passed_current"
    monkeypatch.setattr(module, "MANIFEST_PATH", _write_manifest(tmp_path, manifest))
    with pytest.raises(module.WatchlistError, match="cannot claim passed_current"):
        module.validate_manifest()


def test_conflict_cannot_be_downgraded_to_excluded(tmp_path, monkeypatch):
    module = _module()
    manifest = _load_manifest()
    manifest["families"][0]["exceptions"][0]["disposition"] = "excluded"
    monkeypatch.setattr(module, "MANIFEST_PATH", _write_manifest(tmp_path, manifest))
    with pytest.raises(module.WatchlistError, match="exception set drifted"):
        module.validate_manifest()


@pytest.mark.parametrize("field", ["title", "summary"])
def test_family_semantic_prose_drift_fails_canonical_lock(field, tmp_path, monkeypatch):
    module = _module()
    manifest = _load_manifest()
    manifest["families"][0][field] = "Complete exhaustive develop coverage"
    monkeypatch.setattr(module, "MANIFEST_PATH", _write_manifest(tmp_path, manifest))
    with pytest.raises(module.WatchlistError, match="canonical manifest lock drifted"):
        module.validate_manifest()


def test_exception_reason_drift_fails_canonical_lock(tmp_path, monkeypatch):
    module = _module()
    manifest = _load_manifest()
    manifest["families"][0]["exceptions"][0]["reason"] = (
        "The conflict is resolved and fully supported."
    )
    monkeypatch.setattr(module, "MANIFEST_PATH", _write_manifest(tmp_path, manifest))
    with pytest.raises(module.WatchlistError, match="canonical manifest lock drifted"):
        module.validate_manifest()


def test_validator_imports_no_runtime_network_or_process_modules():
    tree = ast.parse((HERE / "validator.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint(
        {
            "aiohttp",
            "boto3",
            "docker",
            "httpx",
            "os",
            "requests",
            "socket",
            "subprocess",
            "urllib",
        }
    )


def test_validator_has_no_file_write_or_lifecycle_calls():
    tree = ast.parse((HERE / "validator.py").read_text(encoding="utf-8"))
    attributes = {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    assert attributes.isdisjoint(
        {
            "mkdir",
            "rename",
            "replace",
            "rmdir",
            "system",
            "unlink",
            "write_bytes",
            "write_text",
        }
    )
