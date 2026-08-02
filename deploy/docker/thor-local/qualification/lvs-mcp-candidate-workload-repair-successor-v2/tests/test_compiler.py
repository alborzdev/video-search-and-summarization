"""Adversarial checks for the static source-rebase successor."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


PACKAGE_DIR = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("rebase_compiler", PACKAGE_DIR / "compiler.py")
compiler = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(compiler)


def _mutated(tmp_path, mutate):
    document = json.loads((PACKAGE_DIR / "rebase.json").read_text())
    mutate(document)
    path = tmp_path / "rebase.json"
    path.write_text(json.dumps(document))
    return path


def test_check_accepts_frozen_static_rebase():
    result = compiler.check(PACKAGE_DIR / "rebase.json")
    assert result["status"] == "static_rebase_contract_valid"
    assert result["runtime_evidence_created"] is False
    assert result["candidate_admitted"] is False
    assert result["candidate_promoted"] is False
    assert result["warehouse_sample_bundle"] == "excluded"


def test_rejects_source_hash_drift(tmp_path):
    path = _mutated(
        tmp_path,
        lambda document: document["source_overrides"][0].update(
            raw_sha256="0" * 64
        ),
    )
    with pytest.raises(ValueError, match="hash mismatch"):
        compiler.check(path)


def test_rejects_runtime_or_admission_claim(tmp_path):
    def mutate(document):
        document["policy"]["runtime_evidence_created"] = True
        document["policy"]["candidate_admitted"] = True

    path = _mutated(tmp_path, mutate)
    with pytest.raises(ValueError, match="must be false"):
        compiler.check(path)


def test_rejects_semantic_order_drift(tmp_path):
    path = _mutated(
        tmp_path,
        lambda document: document["order_locks"][0].update(
            ordered_identities_sha256="f" * 64
        ),
    )
    with pytest.raises(ValueError, match="semantic order drift"):
        compiler.check(path)


def test_rejects_warehouse_source_override(tmp_path):
    warehouse_path = (
        "deploy/docker/industry-profiles/warehouse-operations/compose.yml"
    )

    def mutate(document):
        source = compiler.REPO_ROOT / warehouse_path
        document["source_overrides"][0] = {
            "path": warehouse_path,
            "raw_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        }

    path = _mutated(tmp_path, mutate)
    with pytest.raises(ValueError, match="Warehouse source override"):
        compiler.check(path)


def test_rejects_implicit_cleanup_or_runtime_blockers(tmp_path):
    def mutate(document):
        document["retained_blockers"] = ["admission remains prohibited"]

    path = _mutated(tmp_path, mutate)
    with pytest.raises(ValueError, match="explicitly include runtime"):
        compiler.check(path)
