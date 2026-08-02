from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest
from jsonschema import Draft202012Validator


PACKAGE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "alerts_source_claim_layered_observer", PACKAGE / "compiler.py"
)
assert SPEC is not None and SPEC.loader is not None
compiler = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compiler)


def load_artifact() -> dict:
    return json.loads(
        (PACKAGE / "layered-observation.json").read_text(encoding="utf-8")
    )


def test_checked_observation_is_exact() -> None:
    assert compiler.validate() == {
        "layer_count": 3,
        "observation_raw_sha256": (
            "5014c7338ab2f003e818302015d10448a7509db4cdfc23ad5f345ad847e43ae9"
        ),
        "semantic_leaf_count": 18,
        "status": "ok",
        "writes_performed": False,
    }


def test_exact_two_stage_chain_and_leaf_denominators() -> None:
    rows = load_artifact()["layers"]
    assert [row["layer_id"] for row in rows] == [
        "source-claim-hash-repair",
        "alerts-current-contract-official",
        "alerts-current-contract-oracles",
    ]
    assert [row["semantic_leaf_count"] for row in rows] == [6, 2, 10]
    assert rows[0]["input_raw_sha256"] == compiler.CURRENT_OFFICIAL_SHA256
    assert rows[0]["rollback_raw_sha256"] == compiler.ALERTS_POST_OFFICIAL_SHA256
    assert rows[1]["input_raw_sha256"] == compiler.ALERTS_POST_OFFICIAL_SHA256
    assert rows[1]["rollback_raw_sha256"] == (
        compiler.ALERTS_PREDECESSOR_OFFICIAL_SHA256
    )
    assert rows[2]["input_raw_sha256"] == compiler.ALERTS_POST_ORACLES_SHA256
    assert rows[2]["rollback_raw_sha256"] == (
        compiler.ALERTS_PREDECESSOR_ORACLES_SHA256
    )


def test_zero_runtime_evidence_promotion_and_writes() -> None:
    artifact = load_artifact()
    assert artifact["policy"] == {
        "docker_allowed": False,
        "network_allowed": False,
        "passed_current_promotions": 0,
        "runtime_evidence_added": False,
        "services_allowed": False,
        "warehouse_sample_bundle": "excluded",
        "writes_performed": False,
    }
    assert artifact["summary"]["runtime_evidence_records"] == 0
    assert artifact["summary"]["promotions"] == 0


def test_all_eleven_source_locks_match_current_regular_files() -> None:
    locks = load_artifact()["source_locks"]
    assert len(locks) == 11
    assert locks == [
        {"path": path, "raw_sha256": digest}
        for path, digest in compiler.EXPECTED_SOURCE_HASHES.items()
    ]
    for lock in locks:
        payload = compiler._read_regular(
            compiler._repo_path(lock["path"]), lock["path"]
        )
        assert compiler.sha256(payload) == lock["raw_sha256"]


def test_source_claim_receipt_schema_and_alerts_receipt_compose() -> None:
    source = json.loads(
        (compiler.REPO_ROOT / compiler.SOURCE_RECEIPT_PATH).read_text(encoding="utf-8")
    )
    source_schema = json.loads(
        (compiler.REPO_ROOT / compiler.SOURCE_RECEIPT_SCHEMA_PATH).read_text(
            encoding="utf-8"
        )
    )
    alerts = json.loads(
        (compiler.REPO_ROOT / compiler.ALERTS_RECEIPT_PATH).read_text(encoding="utf-8")
    )
    assert not list(Draft202012Validator(source_schema).iter_errors(source))
    assert (
        source["target"]["predecessor_raw_sha256"]
        == (alerts["outputs"][compiler.OFFICIAL_PATH])
    )
    assert (
        source["preserved_aggregates"][0]["raw_sha256"]
        == (alerts["outputs"][compiler.ORACLES_PATH])
    )


def test_observation_schema_is_strict() -> None:
    schema = json.loads(
        (PACKAGE / "layered-observation.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    assert not list(Draft202012Validator(schema).iter_errors(load_artifact()))
    mutated = copy.deepcopy(load_artifact())
    mutated["unexpected"] = True
    assert list(Draft202012Validator(schema).iter_errors(mutated))


def test_source_hash_drift_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        compiler.EXPECTED_SOURCE_HASHES, compiler.OFFICIAL_PATH, "0" * 64
    )
    with pytest.raises(compiler.ObservationError, match="source drift"):
        compiler.compile_observation()


def test_duplicate_and_nonfinite_json_fail() -> None:
    with pytest.raises(compiler.ObservationError, match="duplicate key"):
        compiler.strict_json(b'{"x":1,"x":2}', "duplicate")
    with pytest.raises(compiler.ObservationError, match="non-finite"):
        compiler.strict_json(b'{"x":NaN}', "nonfinite")


@pytest.mark.parametrize("command", ["plan", "review", "validate", "rollback-plan"])
def test_all_cli_modes_are_read_only(command: str) -> None:
    watched = [
        compiler.REPO_ROOT / compiler.OFFICIAL_PATH,
        compiler.REPO_ROOT / compiler.ORACLES_PATH,
        compiler.REPO_ROOT / compiler.SOURCE_RECEIPT_PATH,
        compiler.REPO_ROOT / compiler.ALERTS_RECEIPT_PATH,
        PACKAGE / "layered-observation.json",
    ]
    before = {
        path: (path.stat().st_mtime_ns, compiler.sha256(path.read_bytes()))
        for path in watched
    }
    result = subprocess.run(
        [sys.executable, str(PACKAGE / "compiler.py"), command],
        cwd=compiler.REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env={"PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["writes_performed"] is False
    after = {
        path: (path.stat().st_mtime_ns, compiler.sha256(path.read_bytes()))
        for path in watched
    }
    assert after == before


@pytest.mark.parametrize("command", ["write", "apply", "rollback", "execute"])
def test_mutating_and_runtime_modes_are_absent(command: str) -> None:
    result = subprocess.run(
        [sys.executable, str(PACKAGE / "compiler.py"), command],
        cwd=compiler.REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env={"PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 2


def test_compiler_has_no_runtime_network_or_docker_dependencies() -> None:
    source = (PACKAGE / "compiler.py").read_text(encoding="utf-8")
    assert "import subprocess" not in source
    assert "from subprocess" not in source
    assert "import socket" not in source
    assert "docker compose" not in source
