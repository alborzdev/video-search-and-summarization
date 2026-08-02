from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("prerelease_aug2_compiler", HERE / "compiler.py")
assert SPEC is not None and SPEC.loader is not None
compiler = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compiler)


def contract() -> dict:
    return compiler.load_contract()


def test_checked_in_successor_is_latest_and_non_promoting() -> None:
    result = compiler.check()
    assert result["latest_nightly_tag"] == "nightly-20260802"
    assert result["latest_develop_sha"] == "8db763b4632864ec2875cef2004447d0f8bf1086"
    assert result["develop_side_commits"] == 500
    assert result["runtime_evidence"] == []
    assert result["official_capability_promotions"] == 0
    assert result["source_port_required"] is False


def test_predecessor_tree_substitution_fails_closed() -> None:
    value = contract()
    value["predecessor_packages"][0]["tree_sha256"] = "0" * 64
    with pytest.raises(compiler.QualificationError, match="predecessor package drift"):
        compiler.verify_predecessors(value)


def test_latest_commit_or_parent_substitution_fails_closed() -> None:
    value = contract()
    value["upstream_transition"]["previous_develop_sha"] = "0" * 40
    with pytest.raises(compiler.QualificationError, match="transition drifted"):
        compiler.verify_transition(value)


def test_second_path_or_wrong_status_fails_closed() -> None:
    value = contract()
    value["commit"]["path_record"]["status"] = "A"
    with pytest.raises(compiler.QualificationError, match="one-path delta drifted"):
        compiler.verify_transition(value)


def test_projected_digest_or_count_tamper_fails_closed() -> None:
    value = contract()
    value["latest_denominator_projection"]["develop_side_commits"] = 501
    with pytest.raises(compiler.QualificationError, match="arithmetic drifted"):
        compiler.verify_projection(value)
    value = contract()
    value["latest_denominator_projection"]["path_status_gzip_sha256"] = "0" * 64
    with pytest.raises(compiler.QualificationError, match="digest/size projection drifted"):
        compiler.verify_projection(value)


def test_local_equivalence_cannot_be_relabelled_as_a_port() -> None:
    value = contract()
    value["thor_local_equivalence"]["source_port_required"] = True
    with pytest.raises(compiler.QualificationError, match="equivalence contract drifted"):
        compiler.verify_local_equivalence(value)


def test_warehouse_or_runtime_promotion_fails_closed() -> None:
    value = contract()
    value["scope"]["warehouse_sample_bundle"] = "required"
    with pytest.raises(compiler.QualificationError, match="exclusion boundary drifted"):
        compiler.verify_scope(value)
    value = contract()
    value["scope"]["runtime_evidence"] = [{"fabricated": True}]
    with pytest.raises(compiler.QualificationError, match="exclusion boundary drifted"):
        compiler.verify_scope(value)


def test_compiler_has_no_git_network_or_subprocess_dependency() -> None:
    source = (HERE / "compiler.py").read_text(encoding="utf-8")
    for forbidden in ("import subprocess", "import socket", "import requests", "git "):
        assert forbidden not in source
