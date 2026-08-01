import copy
import importlib.util
import json
from pathlib import Path
import pytest

PACKAGE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "workload_compiler", PACKAGE / "compiler.py"
)
compiler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compiler)


def test_checked_output_is_deterministic():
    expected = compiler.compile_workloads()
    compiler.validate(expected)
    assert json.loads((PACKAGE / "workloads.json").read_text()) == expected
    assert (PACKAGE / "workloads.json").read_bytes() == compiler.encoded(expected)


def test_exact_candidate_partition_and_counts():
    out = compiler.compile_workloads()
    rows = out["workloads"]
    assert len(rows) == len({r["candidate_id"] for r in rows}) == 60
    assert (
        out["summary"]["api_candidates"] == 41
        and out["summary"]["deployment_candidates"] == 19
    )
    assert (
        out["summary"]["api_units"] == 134
        and out["summary"]["deployment_actions"] == 58
    )


def test_api_unit_and_request_arithmetic():
    out = compiler.compile_workloads()
    for row in (r for r in out["workloads"] if r["workload_type"] == "api"):
        assert set(row["literal_facets"]) == {
            u["unit_id"] for u in row["operation_units"]
        }
        assert row["calculated_max_requests"] == row["overhead_requests"] + sum(
            u["max_requests"] for u in row["operation_units"]
        )


def test_deployment_order_and_request_arithmetic():
    out = compiler.compile_workloads()
    for row in (r for r in out["workloads"] if r["workload_type"] == "deployment"):
        assert [a["sequence"] for a in row["actions"]] == list(
            range(1, len(row["actions"]) + 1)
        )
        assert row["calculated_max_requests"] == row["overhead_requests"] + sum(
            a["max_requests"] for a in row["actions"]
        )


def test_external_workloads_are_non_activating():
    rows = [
        r
        for r in compiler.compile_workloads()["workloads"]
        if r["acceptance_class"] == "external_optional"
    ]
    assert len(rows) == 3
    assert all(
        r["activation"] == "external_non_activating"
        and r["calculated_max_requests"] == r["max_actions"] == 0
        for r in rows
    )


def test_surfaces_are_regular_repo_files():
    for row in compiler.compile_workloads()["workloads"]:
        for surface in row["source_surfaces"]:
            compiler.regular_surface(surface)


def test_regular_surface_rejects_absolute_parent_and_symlink(monkeypatch, tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    target = tmp_path / "target"
    target.write_text("data")
    (root / "linked").symlink_to(target)
    monkeypatch.setattr(compiler, "ROOT", root)

    with pytest.raises(compiler.WorkloadError):
        compiler.regular_surface(str(target))
    with pytest.raises(compiler.WorkloadError):
        compiler.regular_surface("../target")
    with pytest.raises(compiler.WorkloadError):
        compiler.regular_surface("linked")


def test_atomic_write_rejects_symlink_and_replaces_regular_file(tmp_path):
    output = tmp_path / "workloads.json"
    output.write_bytes(b"old")
    compiler.atomic_write(output, b"new")
    assert output.read_bytes() == b"new"

    target = tmp_path / "target.json"
    target.write_bytes(b"target")
    output.unlink()
    output.symlink_to(target)
    with pytest.raises(compiler.WorkloadError):
        compiler.atomic_write(output, b"unsafe")
    assert target.read_bytes() == b"target"


def test_api_arithmetic_tamper_fails():
    row = copy.deepcopy(json.load(open(PACKAGE / "api-inventory.json"))["entries"][0])
    row["calculated_max_requests"] += 1
    candidates = json.load(open(compiler.ROOT / compiler.SOURCES["candidates"][0]))
    candidate = next(
        e
        for e in candidates["entries"]
        if e["proposed_capability"]["id"] == row["candidate_id"]
    )
    with pytest.raises(compiler.WorkloadError):
        compiler.validate_api(row, candidate)


def test_deployment_sequence_tamper_fails():
    row = copy.deepcopy(
        json.load(open(PACKAGE / "deployment-inventory.json"))["entries"][0]
    )
    row["actions"][0]["sequence"] = 2
    candidates = json.load(open(compiler.ROOT / compiler.SOURCES["candidates"][0]))
    candidate = next(
        e
        for e in candidates["entries"]
        if e["proposed_capability"]["id"] == row["candidate_id"]
    )
    with pytest.raises(compiler.WorkloadError):
        compiler.validate_deployment(row, candidate)


def test_candidate_kind_partition_rejects_swapped_workload_type():
    row = copy.deepcopy(json.load(open(PACKAGE / "api-inventory.json"))["entries"][0])
    candidates = json.load(open(compiler.ROOT / compiler.SOURCES["candidates"][0]))
    candidate = next(
        entry
        for entry in candidates["entries"]
        if entry["proposed_capability"]["id"] == row["candidate_id"]
    )
    row["workload_type"] = "deployment"
    with pytest.raises(compiler.WorkloadError):
        compiler.validate_candidate_binding(row, candidate)
