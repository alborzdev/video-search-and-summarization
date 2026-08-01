#!/usr/bin/env python3
"""Compile an inert, Warehouse-free Thor search-scale qualification plan."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import math
import stat
import sys
from pathlib import Path
from typing import Any, Sequence

from jsonschema import Draft202012Validator, FormatChecker

LANE = Path(__file__).resolve().parent
REPO_ROOT = LANE.parents[4].resolve(strict=True)
CONTRACT_PATH = LANE / "contract.json"
CONTRACT_SCHEMA_PATH = LANE / "contract.schema.json"
EVIDENCE_SCHEMA_PATH = LANE / "evidence.schema.json"

EXPECTED_CONTRACT_SHA256 = (
    "ddb66331b419dba4c7ff3470fea7c583851d5c7b6fb069ae336789f926aef37b"
)
EXPECTED_CONTRACT_SCHEMA_SHA256 = (
    "0280a4a2b9ae6185e94deaaafc713fba921f615175394a6c4bd5513d69639197"
)
EXPECTED_EVIDENCE_SCHEMA_SHA256 = (
    "90fe083eedf8d7abfcf719760b17944bdcc39d158db2f10e087dbcc573ee49c0"
)
MAX_SOURCE_BYTES = 4 * 1024 * 1024
EXPECTED_PERFORMANCE_CONTRACT = {
    "minimum_average_fps": 1.0,
    "maximum_latency_ms": {
        "agent_add": 120000,
        "deepstream_active": 40000,
        "first_embedding": 120000,
        "search_query": 5000,
    },
}


class PlanError(RuntimeError):
    """The static search-scale planning contract was not satisfied."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_sha256(value: Any) -> str:
    return _sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    )


def _assert_finite(value: Any, path: str = "$") -> None:
    """Reject non-finite Python floats before jsonschema comparisons."""
    if isinstance(value, float) and not math.isfinite(value):
        raise PlanError(f"future evidence contains a non-finite number at {path}")
    if isinstance(value, dict):
        for key, item in value.items():
            _assert_finite(item, f"{path}/{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_finite(item, f"{path}/{index}")


def _timestamp(value: str) -> datetime:
    try:
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        return datetime.fromisoformat(normalized)
    except (TypeError, ValueError) as exc:
        raise PlanError(
            f"future evidence contains an invalid timestamp: {value}"
        ) from exc


def _strict_json_bytes(data: bytes, label: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise PlanError(f"duplicate JSON key in {label}: {key}")
            result[key] = value
        return result

    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PlanError(f"invalid JSON in {label}") from exc


def _read_pinned_local(path: Path, expected: str, label: str) -> bytes:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise PlanError(f"cannot read {label}: {path}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise PlanError(f"{label} must be a regular non-symlink file")
    if metadata.st_size <= 0 or metadata.st_size > MAX_SOURCE_BYTES:
        raise PlanError(f"{label} is outside the bounded size contract")
    raw = path.read_bytes()
    actual = _sha256(raw)
    if actual != expected:
        raise PlanError(f"{label} raw SHA-256 mismatch: {actual}")
    return raw


def _safe_repo_source(root: Path, relative: str, expected: str) -> bytes:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise PlanError(f"unsafe source path: {relative}")
    root = root.resolve(strict=True)
    current = root
    for part in path.parts:
        current = current / part
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise PlanError(f"cannot read locked source: {relative}") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise PlanError(f"locked source path contains a symlink: {relative}")
    try:
        current.resolve(strict=True).relative_to(root)
    except (OSError, ValueError) as exc:
        raise PlanError(f"locked source escapes repository: {relative}") from exc
    return _read_pinned_local(current, expected, f"locked source {relative}")


def _load_contract() -> tuple[dict[str, Any], dict[str, Any]]:
    contract = _strict_json_bytes(
        _read_pinned_local(
            CONTRACT_PATH, EXPECTED_CONTRACT_SHA256, "search-scale contract"
        ),
        str(CONTRACT_PATH),
    )
    contract_schema = _strict_json_bytes(
        _read_pinned_local(
            CONTRACT_SCHEMA_PATH,
            EXPECTED_CONTRACT_SCHEMA_SHA256,
            "contract schema",
        ),
        str(CONTRACT_SCHEMA_PATH),
    )
    evidence_schema = _strict_json_bytes(
        _read_pinned_local(
            EVIDENCE_SCHEMA_PATH,
            EXPECTED_EVIDENCE_SCHEMA_SHA256,
            "evidence schema",
        ),
        str(EVIDENCE_SCHEMA_PATH),
    )
    Draft202012Validator.check_schema(contract_schema)
    Draft202012Validator.check_schema(evidence_schema)
    errors = sorted(
        Draft202012Validator(contract_schema).iter_errors(contract),
        key=lambda item: list(item.path),
    )
    if errors:
        first = errors[0]
        raise PlanError(f"contract schema violation: {first.message}")
    return contract, evidence_schema


def _validate_exact_contract(contract: dict[str, Any]) -> None:
    if contract["progressive_stream_counts"] != [2, 4, 8, 16]:
        raise PlanError("progressive denominator must be exactly 2/4/8/16")
    if contract["separate_configuration_stream_count"] != 100:
        raise PlanError("separate configuration denominator must be exactly 100")
    fixture = contract["fixture_contract"]
    expected_fixture = {
        "source_count": 1,
        "source_id": "future-operator-h264-loop-v1",
        "state": "future_unmaterialized",
        "ownership": "operator_supplied",
        "checked_into_repository": False,
        "warehouse_sample_allowed": False,
        "absolute_regular_nonsymlink_path_required": True,
        "sha256_required_before_execution": True,
        "ffprobe_codec_name": "h264",
        "loop_mode": "ffmpeg-stream-loop-minus-one-video-copy-no-audio",
        "reuse_policy": "one_digest_locked_source_may_feed_every_uniquely_named_publisher",
    }
    if fixture != expected_fixture:
        raise PlanError("future operator fixture contract drifted")
    abort = contract["abort_contract"]
    if abort != {
        "minimum_mem_available_kib": 3145728,
        "required_healthy_services": 9,
        "maximum_degraded_services": 0,
        "minimum_active_publishers_fraction": 1.0,
        "minimum_active_deepstream_sources_fraction": 1.0,
        "maximum_failed_streams": 0,
        "sample_interval_seconds": 1,
        "abort_is_immediate": True,
        "advance_after_abort": False,
    }:
        raise PlanError("memory/resource abort contract drifted")
    if contract["claim_gates"]["sixteen_stream_claim"] != {
        "phase_stream_count": 16,
        "codec_name": "h264",
        "width": 1920,
        "height": 1080,
        "all_stream_results_required": True,
        "all_cleanup_results_required": True,
        "reference_only_is_insufficient": True,
    }:
        raise PlanError("16-stream 1080p gate drifted")
    if contract["claim_gates"]["one_hundred_stream_claim"] != {
        "separate_from_progressive_sequence": True,
        "configured_stream_count": 100,
        "explicit_future_operator_approval_required": True,
        "all_stream_results_required": True,
        "all_cleanup_results_required": True,
        "configuration_value_alone_is_insufficient": True,
    }:
        raise PlanError("100-stream claim gate drifted")
    if contract["phase_contract"] != {
        "baseline_seconds": 8,
        "ingest_timeout_seconds_per_stream": 120,
        "source_convergence_timeout_seconds": 40,
        "hold_seconds": 65,
        "cleanup_timeout_seconds_per_stream": 90,
        "progression": "strict_2_then_4_then_8_then_16",
        "advance_requires_prior_phase_pass_and_cleanup": True,
    }:
        raise PlanError("phase timing or progression contract drifted")
    if contract["performance_contract"] != EXPECTED_PERFORMANCE_CONTRACT:
        raise PlanError("throughput or latency performance contract drifted")
    policy = contract["policy"]
    if not all(
        policy[key] is False
        for key in (
            "network_allowed",
            "docker_allowed",
            "subprocess_allowed",
            "file_writes_allowed",
            "service_lifecycle_allowed",
            "can_claim_runtime_scale",
            "can_mark_passed_current",
        )
    ):
        raise PlanError("plan-only safety boundary drifted")
    if (
        policy["runtime_evidence"] != []
        or policy["warehouse_sample_bundle"] != "excluded"
    ):
        raise PlanError("runtime or Warehouse boundary drifted")


def _resource_names(count: int) -> list[dict[str, Any]]:
    width = 3
    phase = f"{count:03d}"
    resources: list[dict[str, Any]] = []
    for ordinal in range(1, count + 1):
        suffix = f"{{run_id}}-p{phase}-s{ordinal:0{width}d}"
        resources.append(
            {
                "ordinal": ordinal,
                "source_id": "future-operator-h264-loop-v1",
                "stream_name": f"thor-search-scale-{suffix}",
                "sensor_name": f"sensor-thor-search-scale-{suffix}",
                "publisher_name": f"publisher-thor-search-scale-{suffix}",
                "document_scope": f"documents-thor-search-scale-{suffix}",
            }
        )
    return resources


def _workload(count: int, *, separate: bool) -> dict[str, Any]:
    phase_id = "separate-configuration-100" if separate else f"progressive-{count:03d}"
    return {
        "phase_id": phase_id,
        "evidence_id_template": f"phase-{{run_id}}-p{count:03d}",
        "stream_count": count,
        "sequence_scope": (
            "separate_operator_approved_run" if separate else "progressive"
        ),
        "operator_approval_required": separate,
        "automatic_execution": False,
        "input": {
            "source_count": 1,
            "source_id": "future-operator-h264-loop-v1",
            "digest_must_be_recorded_before_runtime": True,
            "publisher_loop_mode": "ffmpeg-stream-loop-minus-one-video-copy-no-audio",
        },
        "resources": _resource_names(count),
        "admission": {
            "minimum_mem_available_kib": 3145728,
            "required_healthy_services": 9,
            "required_active_publishers": count,
            "required_active_deepstream_sources": count,
            "maximum_failed_streams": 0,
            "abort_immediately_on_floor_breach": True,
            "advance_after_abort": False,
        },
        "performance_gates": EXPECTED_PERFORMANCE_CONTRACT,
        "required_per_stream_evidence": [
            "agent_add_success",
            "vios_sensor_present",
            "deepstream_source_active",
            "embedding_document_count",
            "search_hit_correlation",
            "add_deepstream_embedding_and_query_latency_ms",
            "fps_memory_temperature_power_and_publisher_samples",
            "owned_cleanup_proof",
        ],
        "cleanup": {
            "scope": "exact_phase_owned_resource_names_only",
            "reverse_order": True,
            "delete_agent_stream": True,
            "delete_exact_sensor_document_scope": True,
            "stop_exact_owned_publisher": True,
            "prove_vios_and_deepstream_absence": True,
            "prove_zero_matching_embedding_documents": True,
            "broad_index_or_stack_cleanup_forbidden": True,
        },
        "qualification_boundary": (
            "100-stream configuration value alone is insufficient; all 100 future runtime results and cleanup proofs are required"
            if separate
            else "future phase only; this compiled plan is not runtime evidence"
        ),
    }


def compile_plan(root: Path = REPO_ROOT) -> dict[str, Any]:
    contract, _evidence_schema = _load_contract()
    _validate_exact_contract(contract)
    source_checks = []
    for lock in contract["source_locks"]:
        raw = _safe_repo_source(root, lock["path"], lock["raw_sha256"])
        text = raw.decode("utf-8")
        missing = [item for item in lock["required_fragments"] if item not in text]
        if missing:
            raise PlanError(
                f"locked source semantic fragment missing in {lock['path']}: {missing[0]}"
            )
        source_checks.append(
            {
                "path": lock["path"],
                "raw_sha256": lock["raw_sha256"],
                "sha256_match": True,
                "semantic_fragments_match": True,
                "role": lock["role"],
            }
        )

    progressive = [
        _workload(count, separate=False)
        for count in contract["progressive_stream_counts"]
    ]
    separate = _workload(contract["separate_configuration_stream_count"], separate=True)
    all_resources = [
        value
        for workload in [*progressive, separate]
        for row in workload["resources"]
        for key, value in row.items()
        if key in {"stream_name", "sensor_name", "publisher_name", "document_scope"}
    ]
    if len(all_resources) != 520 or len(set(all_resources)) != 520:
        raise PlanError("planned stream/resource names are not globally unique")

    return {
        "schema_version": 1,
        "mode": "inert_plan_only",
        "package_id": contract["package_id"],
        "contract_sha256": EXPECTED_CONTRACT_SHA256,
        "evidence_schema": {
            "path": str(EVIDENCE_SCHEMA_PATH.relative_to(REPO_ROOT)),
            "raw_sha256": EXPECTED_EVIDENCE_SCHEMA_SHA256,
            "purpose": "strict future per-stream correctness, latency, resource, abort, and cleanup receipt",
        },
        "source_checks": source_checks,
        "target_gaps": contract["target_gaps"],
        "fixture_contract": contract["fixture_contract"],
        "performance_contract": contract["performance_contract"],
        "progressive_workloads": progressive,
        "separate_100_stream_workload": separate,
        "claim_gates": contract["claim_gates"],
        "summary": {
            "workloads": 5,
            "progressive_stream_counts": [2, 4, 8, 16],
            "separate_configuration_stream_count": 100,
            "planned_stream_instances": 130,
            "planned_unique_owned_resource_names": 520,
            "runtime_executed": False,
            "runtime_evidence_added": False,
            "official_gap_state": "open_unexecuted",
            "capability_effect": "none_plan_only",
        },
        "safety": contract["policy"],
        "boundary": (
            "This package compiles future work only. It does not start publishers, "
            "call APIs, inspect Docker, touch services, generate media, or prove "
            "2/4/8/16/100-stream runtime scale on Thor."
        ),
    }


def validate_future_evidence(value: dict[str, Any]) -> None:
    """Validate a future receipt in memory; this performs no collection or I/O."""
    _assert_finite(value)
    contract, schema = _load_contract()
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
        key=lambda item: list(item.path),
    )
    if errors:
        raise PlanError(f"future evidence schema violation: {errors[0].message}")
    expected_plan_sha256 = _canonical_sha256(compile_plan())
    if value["plan_sha256"] != expected_plan_sha256:
        raise PlanError("future evidence plan SHA-256 does not match this exact plan")
    run_id = value["run_id"]
    digest = value["input_source"]["sha256"]
    progressive_phases = value["progressive_phases"]
    phase100 = value["configuration_100"]
    if phase100 is not None and phase100["run_id"] == run_id:
        raise PlanError("100-stream run ID must differ from the progressive run ID")
    phases = [*progressive_phases, *([phase100] if phase100 is not None else [])]
    performance = contract["performance_contract"]
    maximum_latency_ms = performance["maximum_latency_ms"]
    seen: set[str] = set()
    previous_progressive_passed = True
    previous_progressive_finished: datetime | None = None
    progressive_intervals: list[tuple[datetime, datetime]] = []
    for phase_index, phase in enumerate(phases):
        count = phase["stream_count"]
        is_progressive = phase_index < len(progressive_phases)
        phase_run_id = run_id if is_progressive else phase["run_id"]
        expected_prefix = f"{phase_run_id}-p{count:03d}"
        if phase["evidence_id"] != f"phase-{phase_run_id}-p{count:03d}":
            raise PlanError(
                "phase evidence ID is not bound to its run and stream count"
            )
        started_at = _timestamp(phase["started_at"])
        finished_at = _timestamp(phase["finished_at"])
        if finished_at <= started_at:
            raise PlanError("phase finished_at must be after started_at")
        if is_progressive:
            if phase_index and not previous_progressive_passed:
                raise PlanError("progressive evidence continued after a failed phase")
            if (
                previous_progressive_finished is not None
                and started_at < previous_progressive_finished
            ):
                raise PlanError("progressive phases overlap or are out of order")
            previous_progressive_finished = finished_at
            progressive_intervals.append((started_at, finished_at))
        elif any(
            started_at < progressive_finished and progressive_started < finished_at
            for progressive_started, progressive_finished in progressive_intervals
        ):
            raise PlanError("separate 100-stream run overlaps the progressive run")
        if phase["abort"]["minimum_active_publishers"] != count:
            raise PlanError("phase active-publisher floor differs from stream count")
        for ordinal, row in enumerate(phase["stream_results"], start=1):
            if row["ordinal"] != ordinal or row["input_sha256"] != digest:
                raise PlanError("per-stream ordinal or input digest drifted")
            suffix = f"{expected_prefix}-s{ordinal:03d}"
            expected = {
                "stream_name": f"thor-search-scale-{suffix}",
                "sensor_name": f"sensor-thor-search-scale-{suffix}",
                "publisher_name": f"publisher-thor-search-scale-{suffix}",
                "document_scope": f"documents-thor-search-scale-{suffix}",
            }
            if any(row[key] != expected[key] for key in expected):
                raise PlanError("future evidence contains a non-owned resource name")
            if seen.intersection(expected.values()):
                raise PlanError("future evidence resource names are not unique")
            seen.update(expected.values())

        streams_pass = all(
            all(
                row["correctness"][key]
                for key in (
                    "agent_add_success",
                    "vios_sensor_present",
                    "deepstream_source_active",
                    "search_hit_correlated",
                )
            )
            and row["correctness"]["embedding_documents"] > 0
            and row["resources"]["average_fps"] >= performance["minimum_average_fps"]
            and all(
                row["latency_ms"][key] <= maximum_latency_ms[key]
                for key in (
                    "agent_add",
                    "deepstream_active",
                    "first_embedding",
                    "search_query",
                )
            )
            and row["resources"]["minimum_mem_available_kib_during_lifetime"] >= 3145728
            and row["resources"]["publisher_alive_samples"]
            == row["resources"]["publisher_total_samples"]
            and all(
                row["cleanup"][key]
                for key in (
                    "agent_delete_success",
                    "vios_stream_absent",
                    "deepstream_source_absent",
                    "publisher_stopped",
                    "only_owned_identity_targeted",
                )
            )
            and row["cleanup"]["embedding_documents_after"] == 0
            for row in phase["stream_results"]
        )
        resources_pass = (
            phase["abort"]["triggered"] is False
            and phase["abort"]["observed_minimum_mem_available_kib"] >= 3145728
            and phase["abort"]["minimum_observed_healthy_services"] == 9
            and phase["abort"]["minimum_observed_active_publishers"] == count
            and phase["aggregate_resources"]["minimum_mem_available_kib"] >= 3145728
            and phase["aggregate_resources"]["degraded_service_samples"] == 0
            and phase["cleanup_exact_owned_set"] is True
        )
        if phase["phase_passed"] is not (streams_pass and resources_pass):
            raise PlanError("phase_passed disagrees with strict evidence gates")
        if (phase["abort"]["triggered"] and phase["abort"]["reason"] is None) or (
            not phase["abort"]["triggered"] and phase["abort"]["reason"] is not None
        ):
            raise PlanError("abort reason presence disagrees with abort state")
        if is_progressive:
            previous_progressive_passed = phase["phase_passed"]

    has_phase16 = len(progressive_phases) == 4
    phase16 = progressive_phases[-1] if has_phase16 else None
    all_progressive_passed = has_phase16 and all(
        phase["phase_passed"] for phase in progressive_phases
    )
    expected16 = (
        all_progressive_passed
        and value["input_source"]["codec_name"] == "h264"
        and value["input_source"]["width"] == 1920
        and value["input_source"]["height"] == 1080
    )
    decision16 = value["claim_decisions"]["sixteen_stream_1080p"]
    expected16_fields = {
        "all_16_results_passed": bool(has_phase16 and phase16["phase_passed"]),
        "all_inputs_h264_1920x1080": (
            value["input_source"]["codec_name"] == "h264"
            and value["input_source"]["width"] == 1920
            and value["input_source"]["height"] == 1080
        ),
        "abort_never_triggered": bool(
            has_phase16
            and all(not phase["abort"]["triggered"] for phase in progressive_phases)
        ),
        "cleanup_complete": bool(
            has_phase16
            and all(phase["cleanup_exact_owned_set"] for phase in progressive_phases)
        ),
    }
    if decision16["qualified"] is not expected16 or any(
        decision16[key] is not expected for key, expected in expected16_fields.items()
    ):
        raise PlanError("16-stream claim decision disagrees with 1080p runtime gate")
    expected16_ids = (
        [phase["evidence_id"] for phase in progressive_phases] if expected16 else []
    )
    if decision16["runtime_evidence_ids"] != expected16_ids:
        raise PlanError("16-stream claim evidence IDs do not match its exact phases")

    if phase100 is not None:
        if not all_progressive_passed:
            raise PlanError(
                "any 100-stream receipt requires completed successful 2/4/8/16 phases"
            )
        if _timestamp(phase100["started_at"]) < _timestamp(phase16["finished_at"]):
            raise PlanError("100-stream run must follow completion of phase 16")
        expected100 = phase100["phase_passed"] and phase100["operator_approved"]
        expected100_fields = {
            "operator_approved": phase100["operator_approved"],
            "all_100_results_passed": phase100["phase_passed"],
            "abort_never_triggered": phase100["abort"]["triggered"] is False,
            "cleanup_complete": phase100["cleanup_exact_owned_set"] is True,
        }
    else:
        expected100 = False
        expected100_fields = {
            "operator_approved": False,
            "all_100_results_passed": False,
            "abort_never_triggered": False,
            "cleanup_complete": False,
        }
    decision100 = value["claim_decisions"]["configuration_up_to_100_streams"]
    if decision100["qualified"] is not expected100 or any(
        decision100[key] is not expected for key, expected in expected100_fields.items()
    ):
        raise PlanError("100-stream claim decision disagrees with runtime gate")
    expected100_ids = (
        [phase["evidence_id"] for phase in progressive_phases]
        + [phase100["evidence_id"]]
        if expected100
        else []
    )
    if decision100["runtime_evidence_ids"] != expected100_ids:
        raise PlanError("100-stream claim evidence IDs do not match its exact phases")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", nargs="?", choices=("plan",), default="plan", help="print plan"
    )
    parser.add_argument(
        "--check", action="store_true", help="validate and print a short result"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = compile_plan()
    except (OSError, PlanError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.check:
        print(
            "VALID: inert Warehouse-free search-scale plan; "
            "progressive=2/4/8/16, separate=100, runtime_evidence=0"
        )
    else:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
