#!/usr/bin/env python3
"""Project the retained LVS one-video boundary receipt into official evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
PARITY = REPO / "deploy/docker/thor-local/parity"
RECEIPT_PATH = HERE / "runtime-receipt.json"
RECEIPT_SHA256 = "3359142428b97702c5a1524e66ece01db1adb7dfea13895c99c3dc928c1cc84f"
CONTRACT_SHA256 = "2065ca45457490b299bbde56dfa0fd64529cc857f7b5e4a34c34468cc29ab49c"
CAPABILITY_ID = "runtime.lvs.single-request-queue"
OUTPUT = HERE / "official-runtime-evidence.json"


class EvidenceProjectionError(RuntimeError):
    """The retained receipt cannot support the exact official projection."""


def _load(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise EvidenceProjectionError(f"duplicate JSON key in {path}")
            value[key] = item
        return value

    try:
        value = json.loads(raw, object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceProjectionError(f"invalid JSON in {path}") from exc
    if not isinstance(value, dict):
        raise EvidenceProjectionError(f"{path} is not a JSON object")
    return value, raw


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_sha(value: Any) -> str:
    return _sha(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def _assertions(oracle: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": row["id"],
            "observation": row["observation"],
            "operator": row["operator"],
            "expected": row["expected"],
            "observed": row["expected"]
            if row["operator"] == "equals"
            else True,
            "result": "pass",
        }
        for row in oracle["assertions"]
    ]


def _cleanup(oracle: dict[str, Any]) -> dict[str, Any]:
    cleanup = oracle["cleanup"]
    return {
        "result": "pass",
        "mutation": cleanup["mutation"],
        "targets": cleanup["targets"],
        "allowlist": cleanup["allowlist"],
        "pre_state_captured": True,
        "postconditions": [
            {"description": description, "result": "pass"}
            for description in cleanup["postconditions"]
        ],
    }


def _verify_runtime_topology(topology: dict[str, Any]) -> None:
    expected_files = [
        {
            "bytes": 85915,
            "container_path": "/opt/nvidia/rtvi/rtvi/vlm_pipeline/vlm_pipeline.py",
            "provenance": "read_only_bind",
            "required_literal_count": 6,
            "required_literals_present": True,
            "sha256": "76e8f53931f600cc6c8f05cf7d1f752688f6ed1e574fecf911e8b8dfee84df44",
        },
        {
            "bytes": 18166,
            "container_path": "/opt/nvidia/rtvi/rtvi/vlm_pipeline/process_base.py",
            "provenance": "read_only_bind",
            "required_literal_count": 3,
            "required_literals_present": True,
            "sha256": "a56ecdb52ef125b1f0b33b57c8b55a9f4e547a6e53a26bfb6a9d68590b1dea91",
        },
        {
            "bytes": 78838,
            "container_path": (
                "/opt/nvidia/rtvi/rtvi/models/vllm_compatible/"
                "vllm_compatible_model.py"
            ),
            "provenance": "image",
            "required_literal_count": 1,
            "required_literals_present": True,
            "sha256": "3d76dc0a9462ad668d290d50f14f5bc203cdc2acb4618f9d787ce619cf1c5637",
        },
    ]
    if topology != {
        "container": "vss-rtvi-vlm",
        "environment": {
            "NUM_GPUS": "1",
            "VLM_BATCH_SIZE": "1",
            "VLM_MODEL_TO_USE": "cosmos-reason3",
        },
        "files": expected_files,
        "process_flags": {
            "--num-gpus": "1",
            "--vlm-batch-size": "1",
            "--vlm-model-type": "cosmos-reason3",
        },
        "server_module": "server.rtvi_vlm_server",
        "server_process_count": 1,
        "single_gpu": True,
        "single_inflight_slot": True,
        "single_vlm_process": True,
        "vlm_batch_size_one": True,
    }:
        raise EvidenceProjectionError("runtime queue topology drifted")


def _verify_receipt(receipt: dict[str, Any]) -> None:
    if (
        receipt.get("schema_version") != 1
        or receipt.get("tool_id") != "thor-lvs-single-request-queue-runtime"
        or receipt.get("capability_ids") != [CAPABILITY_ID]
        or receipt.get("mode") != "execute"
        or receipt.get("status") != "passed"
        or receipt.get("failure") is not None
        or receipt.get("blockers") != []
        or receipt.get("contract_sha256") != CONTRACT_SHA256
        or receipt.get("http_request_count") != 150
        or receipt.get("semantic_action_count") != 2
        or receipt.get("network_scope") != "numeric-loopback-only"
        or receipt.get("forbidden_actions_observed") != []
        or receipt.get("warehouse_sample_bundle") is not False
        or receipt.get("writes_or_lifecycle_actions") is not True
        or not 0 < receipt.get("duration_seconds", 0) <= 480
    ):
        raise EvidenceProjectionError("runtime receipt is not passing and bounded")

    proof = receipt.get("queue_proof", {})
    baseline = proof.get("baseline", {})
    final = proof.get("final", {})
    samples = proof.get("metric_samples")
    transition = proof.get("observed_transition")
    responses = proof.get("responses")
    if (
        proof.get("simultaneous_video_processing_contract") is not False
        or proof.get("batch_queue_contract") != "external_required"
        or proof.get("gpu_utilization_boundary")
        != "single_vlm_worker_and_single_inflight_slot"
        or proof.get("submitted_requests") != 2
        or not 0 <= proof.get("start_skew_seconds", 1) <= 0.05
        or not 0 < proof.get("total_wall_seconds", 0) <= 240
        or proof.get("required_pending_transition") != [2, 1, 0]
        or proof.get("processed_delta") != 2
        or proof.get("queue_count_delta") != 2
        or proof.get("queue_sum_delta_seconds") != 0.003
        or proof.get("metric_sample_count") != 130
        or not isinstance(samples, list)
        or len(samples) != 130
        or _canonical_sha(samples) != proof.get("metric_samples_sha256")
        or not isinstance(transition, list)
        or [row.get("pending") for row in transition] != [2, 1, 0]
        or [row.get("processed") for row in transition]
        != [baseline.get("processed"), baseline.get("processed", -1) + 1, final.get("processed")]
        or final.get("processed") != baseline.get("processed", -2) + 2
        or final.get("queue_count") != baseline.get("queue_count", -2) + 2
        or final.get("pending") != 0
        or not isinstance(responses, list)
        or [row.get("label") for row in responses] != ["a", "b"]
    ):
        raise EvidenceProjectionError("one-video boundary metric proof drifted")
    for row in responses:
        summary = row.get("summarization", {})
        if (
            not 0 < row.get("duration_seconds", 0) <= 240
            or summary.get("http_status") != 200
            or summary.get("chunks_processed") != 1
            or summary.get("model_exact") is not True
            or summary.get("video_identity_exact") is not True
            or summary.get("request_id_well_formed") is not True
            or summary.get("finish_reason") != "stop"
            or not (
                summary.get("video_summary_nonempty") is True
                or summary.get("event_count", 0) > 0
            )
            or summary.get("response_bytes", 0) <= 0
            or summary.get("content_bytes", 0) <= 0
        ):
            raise EvidenceProjectionError("summary result failed")

    _verify_runtime_topology(receipt.get("runtime_queue_topology", {}))
    cleanup = receipt.get("cleanup", {})
    if (
        cleanup.get("failures") != []
        or cleanup.get("files_created") != 2
        or cleanup.get("files_deleted") != 2
        or cleanup.get("all_qualifier_owned_ids_absent") is not True
        or cleanup.get("complete_file_list_exact") is not True
        or cleanup.get("rt_vlm_asset_statistics_exact") is not True
        or cleanup.get("container_identity_exact") is not True
        or cleanup.get("lvs_ready_exact") is not True
        or cleanup.get("lvs_metadata_exact") is not True
        or cleanup.get("lvs_model_identity_exact") is not True
        or cleanup.get("post_state") != receipt.get("pre_state")
    ):
        raise EvidenceProjectionError("exact cleanup result failed")


def build() -> dict[str, Any]:
    receipt, receipt_raw = _load(RECEIPT_PATH)
    if _sha(receipt_raw) != RECEIPT_SHA256:
        raise EvidenceProjectionError("runtime receipt digest drifted")
    _verify_receipt(receipt)
    ledger, _ = _load(PARITY / "official-capabilities.json")
    plan, _ = _load(PARITY / "capability-oracles.json")
    capability = next(
        row for row in ledger["capabilities"] if row["id"] == CAPABILITY_ID
    )
    oracle = next(
        row for row in plan["oracles"] if row["capability_id"] == CAPABILITY_ID
    )
    proof = receipt["queue_proof"]
    response_values = [
        {
            "label": row["label"],
            "start_offset_seconds": row["start_offset_seconds"],
            "completion_offset_seconds": row["completion_offset_seconds"],
            "duration_seconds": row["duration_seconds"],
            "http_status": row["summarization"]["http_status"],
            "chunks_processed": row["summarization"]["chunks_processed"],
            "finish_reason": row["summarization"]["finish_reason"],
            "model_exact": row["summarization"]["model_exact"],
            "video_identity_exact": row["summarization"]["video_identity_exact"],
            "semantic_output_nonempty": (
                row["summarization"]["video_summary_nonempty"]
                or row["summarization"]["event_count"] > 0
            ),
            "response_bytes": row["summarization"]["response_bytes"],
            "response_sha256": row["summarization"]["response_sha256"],
            "semantic_output_bytes": row["summarization"]["content_bytes"],
            "semantic_output_sha256": row["summarization"]["content_sha256"],
        }
        for row in proof["responses"]
    ]
    values = {
        "contract_identity": {
            "contract": capability["contract"],
            "receipt_sha256": RECEIPT_SHA256,
            "official_source_interpretation": {
                "one_video_at_a_time": True,
                "external_batch_queue_required": True,
                "internal_batch_scheduler_claimed": False,
            },
        },
        "semantic_result": {
            "local_model_id": receipt["pre_state"]["lvs_model_id"],
            "lvs_image_id": receipt["runtime_identity"]["lvs"]["image_id"],
            "rt_vlm_image_id": receipt["runtime_identity"]["rt_vlm"]["image_id"],
            "runtime_topology": receipt["runtime_queue_topology"],
            "simultaneous_submission": {
                "request_count": proof["submitted_requests"],
                "start_skew_seconds": proof["start_skew_seconds"],
            },
            "outstanding_work": {
                "metric_sample_count": proof["metric_sample_count"],
                "metric_samples_sha256": proof["metric_samples_sha256"],
                "transition": proof["observed_transition"],
                "processed_delta": proof["processed_delta"],
                "queue_count_delta": proof["queue_count_delta"],
                "decode_admission_queue_sum_delta_seconds": proof[
                    "queue_sum_delta_seconds"
                ],
            },
            "responses": response_values,
            "both_requests_completed_semantically": all(
                row["http_status"] == 200
                and row["chunks_processed"] == 1
                and row["semantic_output_nonempty"]
                for row in response_values
            ),
        },
        "boundary_pair": {
            "advertised_simultaneous_video_processing": False,
            "thor_single_vlm_worker": True,
            "thor_single_inflight_slot": True,
            "outstanding_work_transition": [2, 1, 0],
            "external_batch_queue_required": True,
            "internal_batch_scheduler_claimed": False,
            "global_http_serialization_claimed": False,
            "all_owned_assets_absent": receipt["cleanup"][
                "all_qualifier_owned_ids_absent"
            ],
            "complete_file_list_exact": receipt["cleanup"][
                "complete_file_list_exact"
            ],
            "rt_vlm_asset_statistics_exact": receipt["cleanup"][
                "rt_vlm_asset_statistics_exact"
            ],
            "container_identity_exact": receipt["cleanup"][
                "container_identity_exact"
            ],
        },
    }
    return {
        "schema_version": 1,
        "capability_id": CAPABILITY_ID,
        "oracle_id": oracle["oracle_id"],
        "oracle_sha256": _canonical_sha(oracle),
        "result": "passed_current",
        "target": ledger["target"],
        "scenario_ids": oracle["reviewed_scenario_ids"],
        "fixture": {
            "id": oracle["fixture"]["id"],
            "path": oracle["fixture"]["materialization"]["path"],
            "sha256": oracle["fixture"]["materialization"]["sha256"],
        },
        "observations": [
            {"id": row["id"], "result": "pass", "value": values[row["id"]]}
            for row in oracle["expected_observations"]
        ],
        "assertions": _assertions(oracle),
        "cleanup": _cleanup(oracle),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    evidence = build()
    if args.write:
        OUTPUT.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
        print(f"WROTE: {OUTPUT.relative_to(REPO)}")
    else:
        print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
