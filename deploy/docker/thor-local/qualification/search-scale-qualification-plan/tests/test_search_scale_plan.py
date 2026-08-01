from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import shutil
import sys

from jsonschema import Draft202012Validator
import pytest

LANE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "search_scale_plan_test", LANE / "plan.py"
)
assert SPEC is not None and SPEC.loader is not None
PLAN = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PLAN
SPEC.loader.exec_module(PLAN)


def _copy_sources(root: Path) -> list[str]:
    contract = json.loads((LANE / "contract.json").read_text())
    paths = [row["path"] for row in contract["source_locks"]]
    for relative in paths:
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PLAN.REPO_ROOT / relative, destination)
    return paths


def _stream(run_id: str, count: int, ordinal: int, digest: str, passed: bool) -> dict:
    suffix = f"{run_id}-p{count:03d}-s{ordinal:03d}"
    return {
        "ordinal": ordinal,
        "stream_name": f"thor-search-scale-{suffix}",
        "sensor_name": f"sensor-thor-search-scale-{suffix}",
        "publisher_name": f"publisher-thor-search-scale-{suffix}",
        "document_scope": f"documents-thor-search-scale-{suffix}",
        "input_sha256": digest,
        "correctness": {
            "agent_add_success": passed,
            "vios_sensor_present": passed,
            "deepstream_source_active": passed,
            "embedding_documents": 1 if passed else 0,
            "search_hit_correlated": passed,
        },
        "latency_ms": {
            "agent_add": 100,
            "deepstream_active": 200,
            "first_embedding": 5000,
            "search_query": 50,
        },
        "resources": {
            "average_fps": 30.0,
            "minimum_mem_available_kib_during_lifetime": (
                4_000_000 if passed else 3_000_000
            ),
            "maximum_gpu_temp_c": 55.0,
            "average_gpu_power_mw": 35_000.0,
            "publisher_alive_samples": 65 if passed else 64,
            "publisher_total_samples": 65,
        },
        "cleanup": {
            "agent_delete_success": passed,
            "vios_stream_absent": passed,
            "deepstream_source_absent": passed,
            "embedding_documents_after": 0 if passed else 1,
            "publisher_stopped": passed,
            "only_owned_identity_targeted": True,
        },
    }


def _phase(run_id: str, count: int, passed: bool, separate: bool = False) -> dict:
    return {
        "phase_id": (
            "separate-configuration-100" if separate else f"progressive-{count:03d}"
        ),
        "evidence_id": f"phase-{run_id}-p{count:03d}",
        "stream_count": count,
        "operator_approved": True if separate else False,
        "started_at": "2026-08-01T12:00:00Z",
        "finished_at": "2026-08-01T12:02:00Z",
        "abort": {
            "triggered": not passed,
            "reason": None if passed else "memory floor",
            "minimum_mem_available_kib_floor": 3145728,
            "observed_minimum_mem_available_kib": 4_000_000 if passed else 3_000_000,
            "required_healthy_services": 9,
            "minimum_observed_healthy_services": 9 if passed else 8,
            "minimum_active_publishers": count,
            "minimum_observed_active_publishers": count if passed else count - 1,
            "advanced_after_abort": False,
        },
        "aggregate_resources": {
            "sample_interval_seconds": 1,
            "sample_count": 65,
            "minimum_mem_available_kib": 4_000_000 if passed else 3_000_000,
            "maximum_gpu_temp_c": 55.0,
            "average_gpu_power_mw": 35_000.0,
            "degraded_service_samples": 0 if passed else 1,
        },
        "stream_results": [
            _stream(run_id, count, ordinal, "a" * 64, passed)
            for ordinal in range(1, count + 1)
        ],
        "cleanup_exact_owned_set": passed,
        "phase_passed": passed,
    }


def _phase_100(passed: bool) -> dict:
    phase = _phase("fedcba987654", 100, passed, separate=True)
    phase.update(
        run_id="fedcba987654",
        authorization_id="approval-search-scale-100-20260801",
        started_at="2026-08-01T13:00:00Z",
        finished_at="2026-08-01T13:02:00Z",
    )
    return phase


def _evidence(passed: bool = True) -> dict:
    run_id = "0123456789ab"
    phases = [_phase(run_id, count, passed) for count in (2, 4, 8, 16)]
    for index, phase in enumerate(phases):
        minute = index * 3
        phase["started_at"] = f"2026-08-01T12:{minute:02d}:00Z"
        phase["finished_at"] = f"2026-08-01T12:{minute + 2:02d}:00Z"
    phase100 = _phase_100(True) if passed else None
    progressive_ids = [phase["evidence_id"] for phase in phases]
    return {
        "schema_version": 1,
        "mode": "future_runtime_evidence_not_generated_by_plan_package",
        "package_id": "thor-search-scale-qualification-plan-v1",
        "plan_sha256": PLAN._canonical_sha256(PLAN.compile_plan()),
        "run_id": run_id,
        "input_source": {
            "source_id": "future-operator-h264-loop-v1",
            "operator_owned": True,
            "warehouse_sample_used": False,
            "absolute_path_recorded_separately": True,
            "sha256": "a" * 64,
            "size_bytes": 123456,
            "codec_name": "h264",
            "width": 1920,
            "height": 1080,
            "r_frame_rate": "30/1",
            "loop_mode": "ffmpeg-stream-loop-minus-one-video-copy-no-audio",
        },
        "progressive_phases": phases,
        "configuration_100": phase100,
        "claim_decisions": {
            "sixteen_stream_1080p": {
                "qualified": passed,
                "all_16_results_passed": passed,
                "all_inputs_h264_1920x1080": True,
                "abort_never_triggered": passed,
                "cleanup_complete": passed,
                "runtime_evidence_ids": progressive_ids if passed else [],
            },
            "configuration_up_to_100_streams": {
                "qualified": passed,
                "operator_approved": passed,
                "all_100_results_passed": passed,
                "abort_never_triggered": passed,
                "cleanup_complete": passed,
                "configuration_only_is_not_counted": True,
                "runtime_evidence_ids": (
                    [*progressive_ids, phase100["evidence_id"]] if passed else []
                ),
            },
        },
        "boundary": {
            "generated_by_plan_package": False,
            "warehouse_sample_used": False,
            "reference_only_treated_as_runtime_proof": False,
        },
    }


def test_default_compile_is_exact_inert_and_nonadvancing() -> None:
    result = PLAN.compile_plan()
    assert result["mode"] == "inert_plan_only"
    assert result["summary"] == {
        "workloads": 5,
        "progressive_stream_counts": [2, 4, 8, 16],
        "separate_configuration_stream_count": 100,
        "planned_stream_instances": 130,
        "planned_unique_owned_resource_names": 520,
        "runtime_executed": False,
        "runtime_evidence_added": False,
        "official_gap_state": "open_unexecuted",
        "capability_effect": "none_plan_only",
    }
    assert result["safety"]["runtime_evidence"] == []
    assert result["safety"]["can_claim_runtime_scale"] is False
    assert result["safety"]["warehouse_sample_bundle"] == "excluded"


def test_exact_progressive_order_and_separate_100_plan() -> None:
    result = PLAN.compile_plan()
    progressive = result["progressive_workloads"]
    assert [row["stream_count"] for row in progressive] == [2, 4, 8, 16]
    assert [row["phase_id"] for row in progressive] == [
        "progressive-002",
        "progressive-004",
        "progressive-008",
        "progressive-016",
    ]
    separate = result["separate_100_stream_workload"]
    assert separate["stream_count"] == 100
    assert separate["sequence_scope"] == "separate_operator_approved_run"
    assert separate["operator_approval_required"] is True
    assert all(row["automatic_execution"] is False for row in [*progressive, separate])


def test_all_520_owned_names_are_unique_and_deterministic() -> None:
    result = PLAN.compile_plan()
    names = []
    for workload in [
        *result["progressive_workloads"],
        result["separate_100_stream_workload"],
    ]:
        assert len(workload["resources"]) == workload["stream_count"]
        for row in workload["resources"]:
            names.extend(
                row[key]
                for key in (
                    "stream_name",
                    "sensor_name",
                    "publisher_name",
                    "document_scope",
                )
            )
            assert row["source_id"] == "future-operator-h264-loop-v1"
    assert len(names) == len(set(names)) == 520


def test_single_future_h264_fixture_and_claim_gates_are_exact() -> None:
    result = PLAN.compile_plan()
    fixture = result["fixture_contract"]
    assert fixture["source_count"] == 1
    assert fixture["state"] == "future_unmaterialized"
    assert fixture["sha256_required_before_execution"] is True
    assert fixture["ffprobe_codec_name"] == "h264"
    assert fixture["warehouse_sample_allowed"] is False
    gate16 = result["claim_gates"]["sixteen_stream_claim"]
    assert (gate16["phase_stream_count"], gate16["width"], gate16["height"]) == (
        16,
        1920,
        1080,
    )
    assert (
        result["claim_gates"]["one_hundred_stream_claim"][
            "configuration_value_alone_is_insufficient"
        ]
        is True
    )


def test_memory_resource_abort_and_owned_cleanup_are_exact() -> None:
    result = PLAN.compile_plan()
    for workload in [
        *result["progressive_workloads"],
        result["separate_100_stream_workload"],
    ]:
        admission = workload["admission"]
        assert admission["minimum_mem_available_kib"] == 3145728
        assert admission["required_healthy_services"] == 9
        assert admission["required_active_publishers"] == workload["stream_count"]
        assert admission["advance_after_abort"] is False
        cleanup = workload["cleanup"]
        assert cleanup["scope"] == "exact_phase_owned_resource_names_only"
        assert cleanup["broad_index_or_stack_cleanup_forbidden"] is True


def test_performance_gates_are_exact_and_exposed_on_every_workload() -> None:
    result = PLAN.compile_plan()
    expected = {
        "minimum_average_fps": 1.0,
        "maximum_latency_ms": {
            "agent_add": 120000,
            "deepstream_active": 40000,
            "first_embedding": 120000,
            "search_query": 5000,
        },
    }
    assert result["performance_contract"] == expected
    assert all(
        workload["performance_gates"] == expected
        for workload in [
            *result["progressive_workloads"],
            result["separate_100_stream_workload"],
        ]
    )


def test_all_sources_and_package_schemas_are_raw_locked() -> None:
    assert (
        hashlib.sha256((LANE / "contract.json").read_bytes()).hexdigest()
        == PLAN.EXPECTED_CONTRACT_SHA256
    )
    assert (
        hashlib.sha256((LANE / "contract.schema.json").read_bytes()).hexdigest()
        == PLAN.EXPECTED_CONTRACT_SCHEMA_SHA256
    )
    assert (
        hashlib.sha256((LANE / "evidence.schema.json").read_bytes()).hexdigest()
        == PLAN.EXPECTED_EVIDENCE_SCHEMA_SHA256
    )
    contract = json.loads((LANE / "contract.json").read_text())
    for lock in contract["source_locks"]:
        assert (
            hashlib.sha256((PLAN.REPO_ROOT / lock["path"]).read_bytes()).hexdigest()
            == lock["raw_sha256"]
        )
    Draft202012Validator.check_schema(
        json.loads((LANE / "contract.schema.json").read_text())
    )
    Draft202012Validator.check_schema(
        json.loads((LANE / "evidence.schema.json").read_text())
    )


def test_source_tamper_and_symlink_fail_closed(tmp_path: Path) -> None:
    paths = _copy_sources(tmp_path)
    target = tmp_path / paths[0]
    target.write_bytes(target.read_bytes() + b"\ntamper")
    with pytest.raises(PLAN.PlanError, match="raw SHA-256 mismatch"):
        PLAN.compile_plan(tmp_path)
    shutil.copy2(PLAN.REPO_ROOT / paths[0], target)
    target.unlink()
    target.symlink_to(PLAN.REPO_ROOT / paths[0])
    with pytest.raises(PLAN.PlanError, match="contains a symlink"):
        PLAN.compile_plan(tmp_path)


def test_contract_denominator_or_safety_drift_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original, schema = PLAN._load_contract()
    for mutate, message in [
        (
            lambda value: value.__setitem__("progressive_stream_counts", [2, 4, 16]),
            "2/4/8/16",
        ),
        (
            lambda value: value["policy"].__setitem__("docker_allowed", True),
            "safety boundary",
        ),
        (
            lambda value: value["claim_gates"]["sixteen_stream_claim"].__setitem__(
                "width", 1280
            ),
            "1080p gate",
        ),
        (
            lambda value: value["performance_contract"].__setitem__(
                "minimum_average_fps", 0.001
            ),
            "performance contract",
        ),
    ]:
        contract = copy.deepcopy(original)
        mutate(contract)
        monkeypatch.setattr(
            PLAN, "_load_contract", lambda contract=contract: (contract, schema)
        )
        with pytest.raises(PLAN.PlanError, match=message):
            PLAN.compile_plan()


def test_ast_has_no_activation_network_subprocess_or_write_surface() -> None:
    tree = ast.parse((LANE / "plan.py").read_text())
    forbidden_imports = {
        "subprocess",
        "socket",
        "requests",
        "urllib",
        "docker",
        "httpx",
    }
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in (
            node.names
            if isinstance(node, ast.Import)
            else [ast.alias(name=node.module or "")]
        )
    }
    assert not imports & forbidden_imports
    forbidden_calls = {
        "write_text",
        "write_bytes",
        "unlink",
        "mkdir",
        "rename",
        "replace",
        "system",
        "popen",
        "run",
        "Popen",
    }
    called = {
        node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Attribute, ast.Name))
    }
    assert not called & forbidden_calls
    source = (LANE / "plan.py").read_text()
    assert "docker compose" not in source
    assert 'rtsp-streams/add"' not in source


def test_future_evidence_schema_and_semantic_validator_accept_exact_complete_receipt() -> (
    None
):
    evidence = _evidence(True)
    PLAN.validate_future_evidence(evidence)


@pytest.mark.parametrize("length", [1, 2, 3, 4])
def test_future_evidence_accepts_each_successful_contiguous_prefix(length: int) -> None:
    evidence = _evidence(True)
    evidence["progressive_phases"] = evidence["progressive_phases"][:length]
    if length < 4:
        incomplete = _evidence(False)
        evidence["configuration_100"] = incomplete["configuration_100"]
        evidence["claim_decisions"]["configuration_up_to_100_streams"] = incomplete[
            "claim_decisions"
        ]["configuration_up_to_100_streams"]
        decision = evidence["claim_decisions"]["sixteen_stream_1080p"]
        decision.update(
            qualified=False,
            all_16_results_passed=False,
            abort_never_triggered=False,
            cleanup_complete=False,
            runtime_evidence_ids=[],
        )
    PLAN.validate_future_evidence(evidence)


def test_failed_progressive_phase_must_be_final() -> None:
    evidence = _evidence(False)
    evidence["progressive_phases"] = evidence["progressive_phases"][:1]
    PLAN.validate_future_evidence(evidence)

    evidence = _evidence(False)
    with pytest.raises(PLAN.PlanError, match="continued after a failed phase"):
        PLAN.validate_future_evidence(evidence)


def test_100_stream_run_requires_distinct_identity_authorization_and_time() -> None:
    evidence = _evidence(True)
    evidence["configuration_100"]["run_id"] = evidence["run_id"]
    with pytest.raises(PLAN.PlanError, match="run ID must differ"):
        PLAN.validate_future_evidence(evidence)

    evidence = _evidence(True)
    del evidence["configuration_100"]["authorization_id"]
    with pytest.raises(PLAN.PlanError, match="schema violation"):
        PLAN.validate_future_evidence(evidence)

    evidence = _evidence(True)
    evidence["configuration_100"].update(
        started_at="2026-08-01T12:00:30Z",
        finished_at="2026-08-01T12:01:30Z",
    )
    with pytest.raises(PLAN.PlanError, match="overlaps the progressive run"):
        PLAN.validate_future_evidence(evidence)


@pytest.mark.parametrize("failed_prefix", [False, True])
def test_passing_100_requires_complete_successful_progression(
    failed_prefix: bool,
) -> None:
    evidence = _evidence(not failed_prefix)
    evidence["progressive_phases"] = evidence["progressive_phases"][:1]
    if failed_prefix:
        passing = _evidence(True)
        evidence["configuration_100"] = passing["configuration_100"]
        evidence["claim_decisions"]["configuration_up_to_100_streams"] = passing[
            "claim_decisions"
        ]["configuration_up_to_100_streams"]
    decision16 = evidence["claim_decisions"]["sixteen_stream_1080p"]
    decision16.update(
        qualified=False,
        all_16_results_passed=False,
        abort_never_triggered=False,
        cleanup_complete=False,
        runtime_evidence_ids=[],
    )
    with pytest.raises(PLAN.PlanError, match="requires completed successful"):
        PLAN.validate_future_evidence(evidence)


def test_100_stream_run_cannot_precede_successful_progression() -> None:
    evidence = _evidence(True)
    evidence["configuration_100"].update(
        started_at="2026-08-01T11:00:00Z",
        finished_at="2026-08-01T11:02:00Z",
    )
    with pytest.raises(PLAN.PlanError, match="must follow completion of phase 16"):
        PLAN.validate_future_evidence(evidence)


def test_failed_100_receipt_still_requires_successful_progression() -> None:
    evidence = _evidence(False)
    evidence["progressive_phases"] = evidence["progressive_phases"][:1]
    evidence["configuration_100"] = _phase_100(False)
    evidence["claim_decisions"]["configuration_up_to_100_streams"].update(
        operator_approved=True,
    )
    with pytest.raises(PLAN.PlanError, match="any 100-stream receipt requires"):
        PLAN.validate_future_evidence(evidence)


def test_failed_100_receipt_after_successful_progression_is_consistent() -> None:
    evidence = _evidence(True)
    evidence["configuration_100"] = _phase_100(False)
    evidence["claim_decisions"]["configuration_up_to_100_streams"].update(
        qualified=False,
        operator_approved=True,
        all_100_results_passed=False,
        abort_never_triggered=False,
        cleanup_complete=False,
        runtime_evidence_ids=[],
    )
    PLAN.validate_future_evidence(evidence)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("agent_add", 120001),
        ("deepstream_active", 40001),
        ("first_embedding", 120001),
        ("search_query", 5001),
    ],
)
def test_passing_phase_rejects_every_latency_over_contract(
    field: str, value: int
) -> None:
    evidence = _evidence(True)
    evidence["progressive_phases"][0]["stream_results"][0]["latency_ms"][field] = value
    with pytest.raises(PLAN.PlanError, match="schema violation|phase_passed"):
        PLAN.validate_future_evidence(evidence)


def test_passing_phase_rejects_near_zero_fps() -> None:
    evidence = _evidence(True)
    evidence["progressive_phases"][0]["stream_results"][0]["resources"][
        "average_fps"
    ] = 0.001
    with pytest.raises(PLAN.PlanError, match="schema violation|phase_passed"):
        PLAN.validate_future_evidence(evidence)


def test_claim_and_phase_evidence_ids_are_exactly_correlated() -> None:
    evidence = _evidence(True)
    evidence["claim_decisions"]["sixteen_stream_1080p"]["runtime_evidence_ids"] = [
        evidence["progressive_phases"][-1]["evidence_id"]
    ]
    with pytest.raises(PLAN.PlanError, match="16-stream claim evidence IDs"):
        PLAN.validate_future_evidence(evidence)

    evidence = _evidence(True)
    evidence["claim_decisions"]["configuration_up_to_100_streams"][
        "runtime_evidence_ids"
    ] = [evidence["configuration_100"]["evidence_id"]]
    with pytest.raises(PLAN.PlanError, match="100-stream claim evidence IDs"):
        PLAN.validate_future_evidence(evidence)

    evidence = _evidence(True)
    evidence["progressive_phases"][0]["evidence_id"] = "phase-aaaaaaaaaaaa-p002"
    with pytest.raises(PLAN.PlanError, match="phase evidence ID is not bound"):
        PLAN.validate_future_evidence(evidence)


def test_future_evidence_rejects_unknown_fields_name_digest_gate_and_false_pass() -> (
    None
):
    for mutate, message in [
        (lambda value: value.__setitem__("unexpected", True), "schema violation"),
        (
            lambda value: value["progressive_phases"][0]["stream_results"][
                0
            ].__setitem__("stream_name", "not-owned"),
            "schema violation|non-owned",
        ),
        (
            lambda value: value["progressive_phases"][0]["stream_results"][
                0
            ].__setitem__("input_sha256", "c" * 64),
            "input digest",
        ),
        (
            lambda value: value["input_source"].__setitem__("width", 1280),
            "16-stream claim decision",
        ),
        (
            lambda value: value["progressive_phases"][0].__setitem__(
                "phase_passed", False
            ),
            "phase_passed",
        ),
        (
            lambda value: value.__setitem__("plan_sha256", "c" * 64),
            "plan SHA-256",
        ),
        (
            lambda value: value["progressive_phases"][0][
                "aggregate_resources"
            ].__setitem__("maximum_gpu_temp_c", math.nan),
            "non-finite",
        ),
        (
            lambda value: value["progressive_phases"][0].update(
                started_at="2026-08-01T12:03:00Z"
            ),
            "finished_at must be after",
        ),
        (
            lambda value: value["progressive_phases"][1].update(
                started_at="2026-08-01T12:01:00Z"
            ),
            "overlap|out of order",
        ),
    ]:
        evidence = _evidence(True)
        mutate(evidence)
        with pytest.raises(PLAN.PlanError, match=message):
            PLAN.validate_future_evidence(evidence)


def test_default_cli_prints_only_inert_plan(capsys: pytest.CaptureFixture[str]) -> None:
    assert PLAN.main([]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "inert_plan_only"
    assert output["summary"]["runtime_executed"] is False
    assert PLAN.main(["--check"]) == 0
    assert "runtime_evidence=0" in capsys.readouterr().out
