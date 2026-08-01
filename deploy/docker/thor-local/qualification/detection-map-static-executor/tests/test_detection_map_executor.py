from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import jsonschema
import pytest


PACKAGE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "detection_map_static_executor_test", PACKAGE / "executor.py"
)
assert SPEC and SPEC.loader
executor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(executor)


def test_executor_produces_strict_candidate_receipt_twice() -> None:
    result = executor.execute()
    schema = json.loads((PACKAGE / "result.schema.json").read_text())
    jsonschema.Draft202012Validator(schema).validate(result)
    assert result["candidate_only"] is True
    assert result["official_capability_effect"] == "none_candidate_only"
    assert result["runtime_evidence"] == []
    assert result["deterministic_runs"][0] == result["deterministic_runs"][1]
    assert result["cleanup"] == {
        "owned_root_removed": True,
        "executor_owned_sentinel_unchanged": True,
    }


def test_semantic_oracle_proves_perfect_ap_and_threshold_miss() -> None:
    runs = executor.execute()["deterministic_runs"]
    perfect, miss = runs[0]["semantic"]
    assert perfect["case_id"] == "perfect-single-detection"
    assert perfect["mean_ap"] == 1.0
    assert perfect["true_positives"] == 1
    assert perfect["false_positives"] == 0
    assert perfect["per_class"]["Person"]["match_distances"] == [0.0]
    assert miss["case_id"] == "distance-threshold-miss"
    assert miss["mean_ap"] == 0.0
    assert miss["true_positives"] == 0
    assert miss["false_positives"] == 1
    assert miss["false_negatives"] == 1


def test_receipt_preserves_exact_non_runtime_claim_boundary() -> None:
    result = executor.execute()
    assert result["claim_boundary"] == {
        "semantic_oracle_executed": True,
        "checked_in_integration_test_evidence_verified": True,
        "production_evaluator_executed": False,
        "local_optional_eval_dependencies_verified": False,
        "service_runtime_proven": False,
    }
    assert result["integration_test_evidence"]["production_evaluator_executed"] is False
    assert '"passed_current"' not in json.dumps(result)


def test_contract_and_all_executable_inputs_are_digest_locked() -> None:
    contract_raw = (PACKAGE / "contract.json").read_bytes()
    assert hashlib.sha256(contract_raw).hexdigest() == executor.EXPECTED_CONTRACT_SHA256
    contract = executor._load_contract()
    expected = {item["path"]: item["sha256"] for item in contract["source_locks"]}
    expected[contract["fixture"]["path"]] = contract["fixture"]["sha256"]
    expected[contract["plan_binding"]["path"]] = contract["plan_binding"]["raw_sha256"]
    result = executor.execute()
    assert result["input_sha256"] == expected


def test_manifest_binding_is_exact_without_unrelated_whole_file_lock() -> None:
    contract = executor._load_contract()
    binding = contract["entry"]
    assert binding["manifest_pointer"] == "/features/29/advertised/3"
    assert binding["advertised"] == "detection mAP"
    assert binding["advertised_canonical_sha256"] == executor._sha256(
        executor._canonical_bytes("detection mAP")
    )
    assert "deploy/docker/thor-local/parity/manifest.json" not in {
        item["path"] for item in contract["source_locks"]
    }


def test_list_selection_unknown_and_duplicate_fail_closed(capsys) -> None:
    assert executor.main(["--list"]) == 0
    assert capsys.readouterr().out.splitlines() == [executor.ENTRY_ID]
    assert executor.execute([executor.ENTRY_ID])["entry_id"] == executor.ENTRY_ID
    with pytest.raises(executor.QualificationError, match="unknown or unsupported"):
        executor.execute(["manifest-gap.not-real"])
    with pytest.raises(executor.QualificationError, match="duplicate --case"):
        executor.execute([executor.ENTRY_ID, executor.ENTRY_ID])
    with pytest.raises(SystemExit):
        executor.main(["--list", "--case", executor.ENTRY_ID])


def test_source_tamper_fails_before_semantic_execution(monkeypatch) -> None:
    contract = executor._load_contract()
    target = contract["source_locks"][0]["path"]
    original = executor._read_repo_bytes
    called = False

    def tampered(path: str) -> bytes:
        data = original(path)
        return data + b"\n# tampered" if path == target else data

    def forbidden_run(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("semantic execution must not begin")

    monkeypatch.setattr(executor, "_read_repo_bytes", tampered)
    monkeypatch.setattr(executor, "_run_once", forbidden_run)
    with pytest.raises(executor.QualificationError, match="source lock mismatch"):
        executor.execute()
    assert called is False


def test_manifest_literal_tamper_fails_closed(monkeypatch) -> None:
    original = executor._read_repo_bytes
    manifest_path = "deploy/docker/thor-local/parity/manifest.json"

    def tampered(path: str) -> bytes:
        data = original(path)
        if path != manifest_path:
            return data
        manifest = json.loads(data)
        manifest["features"][29]["advertised"][3] = "source presence only"
        return json.dumps(manifest).encode()

    monkeypatch.setattr(executor, "_read_repo_bytes", tampered)
    with pytest.raises(executor.QualificationError, match="advertised literal drift"):
        executor.execute()


def test_plan_duplicate_entry_and_status_escalation_fail_closed(monkeypatch) -> None:
    contract = executor._load_contract()
    original = executor._read_repo_bytes
    plan_path = contract["plan_binding"]["path"]
    plan = json.loads(original(plan_path))
    entry = next(
        item for item in plan["entries"] if item["entry_id"] == executor.ENTRY_ID
    )
    plan["entries"].append(copy.deepcopy(entry))
    raw = json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()
    changed = copy.deepcopy(contract)
    changed["plan_binding"]["raw_sha256"] = executor._sha256(raw)

    monkeypatch.setattr(
        executor,
        "_read_repo_bytes",
        lambda path: raw if path == plan_path else original(path),
    )
    with pytest.raises(executor.QualificationError, match="exactly one"):
        executor._verify_bindings(changed)

    plan["entries"].pop()
    entry["required_oracle"]["status"] = "passed_current"
    raw = json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()
    changed["plan_binding"]["raw_sha256"] = executor._sha256(raw)
    changed["plan_binding"]["entry_canonical_sha256"] = executor._sha256(
        executor._canonical_bytes(entry)
    )
    with pytest.raises(executor.QualificationError, match="boundary drift"):
        executor._verify_bindings(changed)


def test_ast_evidence_rejects_removed_real_ap_assertion(monkeypatch) -> None:
    contract = executor._load_contract()
    tests_path = next(
        item["path"]
        for item in contract["source_locks"]
        if item["path"].endswith("/test_evaluate.py")
    )
    original = executor._read_repo_bytes
    raw = original(tests_path)
    tampered = raw.replace(
        b'assert summary["mean_dist_aps"]["Person"] == 1.0',
        b'assert summary["mean_dist_aps"]["Person"] >= 0.0',
        1,
    )
    assert tampered != raw
    changed = copy.deepcopy(contract)
    lock = next(item for item in changed["source_locks"] if item["path"] == tests_path)
    lock["sha256"] = executor._sha256(tampered)
    monkeypatch.setattr(
        executor,
        "_read_repo_bytes",
        lambda path: tampered if path == tests_path else original(path),
    )
    with pytest.raises(
        executor.QualificationError, match="no longer asserts Person AP=1.0"
    ):
        executor._verify_source_evidence(changed)


def test_ast_evidence_rejects_removed_production_calc_ap(monkeypatch) -> None:
    contract = executor._load_contract()
    path = next(
        item["path"]
        for item in contract["source_locks"]
        if item["path"].endswith("/evaluate.py")
    )
    original = executor._read_repo_bytes
    raw = original(path)
    tampered = raw.replace(b"ap = calc_ap(", b"ap = bypass_ap(", 1)
    assert tampered != raw
    changed = copy.deepcopy(contract)
    next(item for item in changed["source_locks"] if item["path"] == path)["sha256"] = (
        executor._sha256(tampered)
    )
    monkeypatch.setattr(
        executor,
        "_read_repo_bytes",
        lambda item: tampered if item == path else original(item),
    )
    with pytest.raises(executor.QualificationError, match="AP call graph drift"):
        executor._verify_source_evidence(changed)


def test_fixture_expected_value_and_nonfinite_values_fail_closed(
    tmp_path: Path,
) -> None:
    contract = executor._load_contract()
    fixture = json.loads(executor._read_repo_bytes(contract["fixture"]["path"]))
    wrong = copy.deepcopy(fixture)
    wrong["cases"][0]["expected"]["mean_ap"] = 0.5
    with pytest.raises(
        executor.QualificationError, match="semantic expectation failed"
    ):
        executor._run_once(wrong, tmp_path / "wrong")

    nonfinite = copy.deepcopy(fixture)
    nonfinite["cases"][0]["predictions"][0]["translation"][0] = float("nan")
    with pytest.raises(executor.QualificationError, match="three finite"):
        executor._execute_fixture_case(
            nonfinite["cases"][0], nonfinite["distance_threshold"], nonfinite["classes"]
        )


def test_output_tamper_and_claim_escalation_are_rejected(tmp_path: Path) -> None:
    contract = executor._load_contract()
    fixture = json.loads(executor._read_repo_bytes(contract["fixture"]["path"]))
    run = executor._run_once(fixture, tmp_path / "run")
    run["tree_sha256"] = "0" * 64
    with pytest.raises(executor.QualificationError, match="tree lock mismatch"):
        executor._validate_output_locks(run, contract["output_locks"])

    result = executor.execute()
    schema = json.loads((PACKAGE / "result.schema.json").read_text())
    result["claim_boundary"]["production_evaluator_executed"] = True
    assert list(jsonschema.Draft202012Validator(schema).iter_errors(result))


def test_duplicate_json_unsafe_paths_and_symlinks_are_rejected(
    tmp_path: Path, monkeypatch
) -> None:
    with pytest.raises(executor.QualificationError, match="duplicate JSON key"):
        executor._strict_json_bytes(b'{"x":1,"x":2}', "duplicate")
    for path in ("../../etc/passwd", "/etc/passwd"):
        with pytest.raises(executor.QualificationError, match="unsafe repository path"):
            executor._repo_file(path)

    root = tmp_path / "repo"
    root.mkdir()
    target = root / "target"
    target.write_text("safe")
    (root / "link").symlink_to(target)
    monkeypatch.setattr(executor, "REPO_ROOT", root)
    with pytest.raises(executor.QualificationError, match="regular non-symlink"):
        executor._repo_file("link")


def test_owned_temp_root_is_removed_when_semantic_execution_raises(
    tmp_path: Path, monkeypatch
) -> None:
    owned = tmp_path / "owned"

    def make_owned(*args, **kwargs) -> str:
        owned.mkdir()
        return str(owned)

    monkeypatch.setattr(executor.tempfile, "mkdtemp", make_owned)
    monkeypatch.setattr(
        executor,
        "_run_once",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            executor.QualificationError("boom")
        ),
    )
    with pytest.raises(executor.QualificationError, match="boom"):
        executor.execute()
    assert not owned.exists()


def test_executor_source_has_no_network_docker_subprocess_or_shell_path() -> None:
    tree = ast.parse((PACKAGE / "executor.py").read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not (imported & {"socket", "requests", "urllib", "subprocess", "docker"})
    source = (PACKAGE / "executor.py").read_text()
    assert "os.system" not in source
    assert "Popen(" not in source


def test_contract_schema_rejects_safety_and_warehouse_escalation() -> None:
    contract = json.loads((PACKAGE / "contract.json").read_text())
    schema = json.loads((PACKAGE / "contract.schema.json").read_text())
    validator = jsonschema.Draft202012Validator(schema)
    mutations = []
    for key in (
        "network_allowed",
        "docker_allowed",
        "subprocess_allowed",
        "lifecycle_allowed",
    ):
        changed = copy.deepcopy(contract)
        changed["policy"][key] = True
        mutations.append(changed)
    changed = copy.deepcopy(contract)
    changed["policy"]["can_mark_passed_current"] = True
    mutations.append(changed)
    changed = copy.deepcopy(contract)
    changed["fixture"]["warehouse_sample_bundle"] = True
    mutations.append(changed)
    for mutation in mutations:
        assert list(validator.iter_errors(mutation))
