from __future__ import annotations

import ast
import copy
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parents[1]
REPO_ROOT = HERE.parents[4]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


validator = _load_module("synthetic_data_static_validator", HERE / "validator.py")
sys.path.insert(0, str(HERE))
executor = _load_module("synthetic_data_static_executor", HERE / "executor.py")


def _contract() -> dict:
    return json.loads((HERE / "contract.json").read_text(encoding="utf-8"))


def _all_repo_paths(contract: dict) -> set[str]:
    paths = {
        validator.MANIFEST_PATH,
        validator.CAPABILITIES_PATH,
        validator.ORACLES_PATH,
        contract["arm64_environment"]["conda_lock"]["path"],
        contract["arm64_environment"]["pip_requirements"]["path"],
        contract["arm64_environment"]["wheel_lock"]["path"],
    }
    paths.update(row["path"] for row in contract["arm64_environment"]["source_controls"])
    for entry in contract["entries"]:
        paths.update(row["path"] for row in entry["source_reviews"])
        paths.update(row["path"] for row in entry["cli_contracts"])
    return paths


def _copy_repo(tmp_path: Path, contract: dict) -> Path:
    root = tmp_path / "repo"
    for relative in _all_repo_paths(contract):
        source = REPO_ROOT / relative
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    return root


def test_default_execution_passes_without_runtime_promotion() -> None:
    result = executor.execute()
    assert result["status"] == "pass"
    assert result["scope"] == "static_wiring_only"
    assert result["runtime_evidence_created"] is False
    assert result["runtime_state_promoted"] is False
    assert result["observations"]["full_semantic_execution_performed"] is False
    assert result["observations"]["runtime_evidence"] == []
    assert result["observations"]["unique_entry_source_count"] == 18


def test_execution_and_cli_output_are_deterministic() -> None:
    assert executor.execute() == executor.execute()
    command = [sys.executable, str(HERE / "executor.py"), "--check"]
    first = subprocess.run(command, check=True, capture_output=True, text=True)
    second = subprocess.run(command, check=True, capture_output=True, text=True)
    assert first.stdout == second.stdout
    assert json.loads(first.stdout)["status"] == "pass"


def test_contract_binds_exact_entry_capability_and_full_slug_oracle_ids() -> None:
    contract = _contract()
    observed = [
        (
            entry["advertised"],
            entry["entry_id"],
            entry["capability"]["id"],
            entry["oracle"]["id"],
            len(entry["source_reviews"]),
        )
        for entry in contract["entries"]
    ]
    assert observed == validator.EXPECTED_ENTRIES
    assert {entry["capability"]["kind"] for entry in contract["entries"]} == {
        "tooling"
    }
    assert {entry["capability"]["acceptance_class"] for entry in contract["entries"]} == {
        "alternate_local_lane"
    }
    assert {entry["capability"]["thor_state"] for entry in contract["entries"]} == {
        "wired"
    }
    assert {entry["capability"]["runtime_state"] for entry in contract["entries"]} == {
        "not_qualified"
    }


def test_contract_and_result_schemas_reject_overclaim_and_unknown_fields() -> None:
    contract_schema = validator.strict_json(HERE / "contract.schema.json")
    contract = _contract()
    promoted = copy.deepcopy(contract)
    promoted["entries"][0]["capability"]["runtime_state"] = "passed_current"
    assert list(Draft202012Validator(contract_schema).iter_errors(promoted))
    extra = copy.deepcopy(contract)
    extra["policy"]["network_probe"] = True
    assert list(Draft202012Validator(contract_schema).iter_errors(extra))

    result_schema = validator.strict_json(HERE / "result.schema.json")
    result = executor.execute()
    overclaim = copy.deepcopy(result)
    overclaim["runtime_state_promoted"] = True
    assert list(Draft202012Validator(result_schema).iter_errors(overclaim))
    evidence = copy.deepcopy(result)
    evidence["observations"]["runtime_evidence"] = [{"claim": "invented"}]
    assert list(Draft202012Validator(result_schema).iter_errors(evidence))


def test_ground_truth_cli_and_four_output_denominator_are_exact() -> None:
    ground = _contract()["entries"][3]
    assert ground["cli_contracts"][0]["arguments"] == [
        "input",
        "--output",
        "--calibration",
        "--max_frames",
        "--xform_info",
        "--skip-visualization",
    ]
    assert (
        ground["cli_contracts"][0]["semantics"]
        == validator.EXPECTED_GROUND_TRUTH_SEMANTICS
    )
    assert ground["deterministic_outputs"] == validator.EXPECTED_OUTPUTS
    assert ground["source_reviews"][0]["sha256"] == (
        "4d81551c3a143f52f3fa4bfdc52f1af6aa01fac864d250a9a3f2547dfdaeef9f"
    )


def test_arm64_lock_identities_and_warehouse_exclusion_are_exact() -> None:
    contract = _contract()
    environment = contract["arm64_environment"]
    assert environment["platform"] == "linux-aarch64"
    assert environment["python"] == "3.10.20"
    assert environment["openusd"] == "26.05"
    assert environment["conda_lock"]["artifact_count"] == 178
    assert environment["pip_requirements"]["requirement_count"] == 21
    assert environment["wheel_lock"]["wheel_count"] == 21
    assert contract["warehouse_scope"] == {
        "sample_bundle_required": False,
        "sample_assets_or_paths": [],
        "custom_data_runtime_oracle_remains_required": True,
    }
    assert all(entry["oracle"]["runtime_evidence"] == [] for entry in contract["entries"])


def test_exact_contract_digest_rejects_contract_mutation(tmp_path: Path) -> None:
    contract = _contract()
    contract["policy"]["can_mark_passed_current"] = True
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(contract), encoding="utf-8")
    with pytest.raises(validator.QualificationError, match="exact contract digest drift"):
        validator.validate_contract(path)


def test_duplicate_json_keys_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.json"
    path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
    with pytest.raises(validator.QualificationError, match="duplicate JSON key"):
        validator.strict_json(path)


def test_source_digest_drift_fails_before_static_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contract = _contract()
    root = _copy_repo(tmp_path, contract)
    target = root / "tools/sdg-postprocessing/data_conversion/convert_ground_truth.py"
    target.write_text(target.read_text(encoding="utf-8") + "\n# tampered\n", encoding="utf-8")
    monkeypatch.setattr(validator, "REPO_ROOT", root)
    with pytest.raises(validator.QualificationError, match="source digest drift"):
        validator.validate_contract()


def test_missing_ast_symbol_fails_even_with_updated_local_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contract = _contract()
    root = _copy_repo(tmp_path, contract)
    row = contract["entries"][0]["source_reviews"][0]
    target = root / row["path"]
    source = target.read_text(encoding="utf-8").replace(
        "def categorize_boxes(", "def categorize_boxes_removed("
    )
    target.write_text(source, encoding="utf-8")
    row["sha256"] = validator.sha256_bytes(target.read_bytes())
    monkeypatch.setattr(validator, "REPO_ROOT", root)
    with pytest.raises(validator.QualificationError, match="missing AST symbols"):
        validator._verify_source_reviews(contract)


def test_missing_cli_flag_fails_even_with_updated_local_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contract = _contract()
    root = _copy_repo(tmp_path, contract)
    row = contract["entries"][3]["source_reviews"][0]
    target = root / row["path"]
    target.write_text(
        target.read_text(encoding="utf-8").replace("--skip-visualization", "--skip-render"),
        encoding="utf-8",
    )
    row["sha256"] = validator.sha256_bytes(target.read_bytes())
    monkeypatch.setattr(validator, "REPO_ROOT", root)
    with pytest.raises(validator.QualificationError, match="CLI argument absent"):
        validator._verify_cli_contracts(contract)


def test_arm64_identity_fails_even_with_updated_local_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contract = _contract()
    root = _copy_repo(tmp_path, contract)
    descriptor = contract["arm64_environment"]["conda_lock"]
    target = root / descriptor["path"]
    target.write_text(
        target.read_text(encoding="utf-8").replace(
            "openusd-26.05-py310", "openusd-99.99-py310"
        ),
        encoding="utf-8",
    )
    descriptor["sha256"] = validator.sha256_bytes(target.read_bytes())
    monkeypatch.setattr(validator, "REPO_ROOT", root)
    with pytest.raises(validator.QualificationError, match="ARM64 conda identity absent"):
        validator._verify_arm64_environment(contract)


def test_symlinked_source_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contract = _contract()
    root = _copy_repo(tmp_path, contract)
    target = root / contract["entries"][0]["source_reviews"][0]["path"]
    replacement = target.with_suffix(".real")
    target.rename(replacement)
    target.symlink_to(replacement.name)
    monkeypatch.setattr(validator, "REPO_ROOT", root)
    with pytest.raises(validator.QualificationError, match="symlinked repository source"):
        validator.validate_contract()


def test_executor_and_validator_have_no_external_or_write_apis() -> None:
    forbidden_imports = {"requests", "socket", "subprocess", "urllib", "docker"}
    forbidden_calls = {"write_text", "write_bytes", "unlink", "mkdir", "makedirs", "remove"}
    for path in (HERE / "validator.py", HERE / "executor.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in (node.names if isinstance(node, ast.Import) else [ast.alias(name=node.module or "")])
        }
        calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert not (imports & forbidden_imports)
        assert not (calls & forbidden_calls)


def test_default_execution_does_not_change_source_mtimes() -> None:
    contract = _contract()
    paths = [REPO_ROOT / path for path in sorted(_all_repo_paths(contract))]
    before = {path: path.stat().st_mtime_ns for path in paths}
    executor.execute()
    after = {path: path.stat().st_mtime_ns for path in paths}
    assert after == before
