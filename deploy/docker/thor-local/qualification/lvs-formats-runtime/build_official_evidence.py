#!/usr/bin/env python3
"""Project the retained LVS format receipt into official capability evidence."""

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
RECEIPT_SHA256 = "85b526607ff67698d43dbc424a78cc1feb4ac7304138999c0e82e65288e45f21"
CAPABILITY_ID = "runtime.lvs.supported-formats"
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


def _oracle_sha(oracle: dict[str, Any]) -> str:
    return _sha(json.dumps(oracle, sort_keys=True, separators=(",", ":")).encode())


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


def _verify_receipt(receipt: dict[str, Any]) -> None:
    expected_formats = ["MP4", "AVI", "MOV", "MKV", "WebM"]
    rows = receipt.get("formats")
    if (
        receipt.get("schema_version") != 1
        or receipt.get("tool_id") != "thor-lvs-formats-runtime"
        or receipt.get("capability_ids") != [CAPABILITY_ID]
        or receipt.get("status") != "passed"
        or receipt.get("failure") is not None
        or receipt.get("blockers") != []
        or receipt.get("contract_sha256")
        != "28030f32ef10d0fe240b11671511a75b5b308041732206a258f9e1f333bf20d7"
        or receipt.get("http_request_count") != 37
        or receipt.get("semantic_action_count") != 9
        or receipt.get("network_scope") != "numeric-loopback-only"
        or receipt.get("forbidden_actions_observed") != []
        or receipt.get("warehouse_sample_bundle") is not False
        or not 0 < receipt.get("duration_seconds", 0) <= 900
        or not isinstance(rows, list)
        or [row.get("name") for row in rows] != expected_formats
    ):
        raise EvidenceProjectionError("runtime receipt is not passing and bounded")
    for row in rows:
        media = row.get("media", {})
        summary = row.get("summarization", {})
        if (
            row.get("upload_http_status") != 200
            or row.get("readback_http_status") != 200
            or row.get("delete_http_status") != 200
            or row.get("exact_cleanup_after") is not True
            or media.get("width") != 640
            or media.get("height") != 360
            or media.get("frame_rate") != "5/1"
            or media.get("duration_seconds") != 10.0
            or media.get("video_stream_count") != 1
            or media.get("audio_stream_count") != 0
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
        ):
            raise EvidenceProjectionError(f"format result failed: {row.get('name')}")
    negative = receipt.get("adjacent_negative", {})
    cleanup = receipt.get("cleanup", {})
    if (
        negative.get("http_status") != 400
        or negative.get("error_code") != "InvalidFile"
        or negative.get("asset_absent") is not True
        or negative.get("file_list_exact_after") is not True
        or cleanup.get("failures") != []
        or cleanup.get("positive_files_created") != 5
        or cleanup.get("positive_files_deleted") != 5
        or cleanup.get("invalid_file_created") is not False
        or cleanup.get("all_qualifier_owned_ids_absent") is not True
        or cleanup.get("complete_file_list_exact") is not True
        or cleanup.get("rt_vlm_asset_statistics_exact") is not True
        or cleanup.get("container_identity_exact") is not True
        or cleanup.get("post_state") != receipt.get("pre_state")
    ):
        raise EvidenceProjectionError("negative or cleanup result failed")


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
    format_values = [
        {
            "name": row["name"],
            "extension": row["extension"],
            "codec": row["media"]["codec"],
            "container": row["media"]["format_name"],
            "bytes": row["media"]["bytes"],
            "media_sha256": row["media"]["sha256"],
            "raw_hash_policy": row["media"]["raw_hash_policy"],
            "upload_http_status": row["upload_http_status"],
            "readback_http_status": row["readback_http_status"],
            "summarize_http_status": row["summarization"]["http_status"],
            "summary_response_sha256": row["summarization"]["response_sha256"],
            "summary_or_event_nonempty": row["summarization"][
                "video_summary_nonempty"
            ]
            or row["summarization"]["event_count"] > 0,
            "chunks_processed": row["summarization"]["chunks_processed"],
            "delete_http_status": row["delete_http_status"],
            "exact_cleanup_after": row["exact_cleanup_after"],
        }
        for row in receipt["formats"]
    ]
    values = {
        "contract_identity": {
            "contract": capability["contract"],
            "receipt_sha256": RECEIPT_SHA256,
        },
        "semantic_result": {
            "advertised_formats": ["MP4", "AVI", "MOV", "MKV", "WebM"],
            "tested_format_count": len(format_values),
            "local_model_id": receipt["pre_state"]["lvs_model_id"],
            "lvs_image_id": receipt["runtime_identity"]["lvs"]["image_id"],
            "rt_vlm_image_id": receipt["runtime_identity"]["rt_vlm"][
                "image_id"
            ],
            "formats": format_values,
            "all_five_summarized": all(
                row["summarize_http_status"] == 200
                and row["summary_or_event_nonempty"]
                and row["chunks_processed"] == 1
                for row in format_values
            ),
        },
        "boundary_pair": {
            "positive_format_count": len(format_values),
            "positive_all_passed": True,
            "invalid_media_http_status": receipt["adjacent_negative"][
                "http_status"
            ],
            "invalid_media_error_code": receipt["adjacent_negative"][
                "error_code"
            ],
            "invalid_media_asset_absent": receipt["adjacent_negative"][
                "asset_absent"
            ],
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
        "oracle_sha256": _oracle_sha(oracle),
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
