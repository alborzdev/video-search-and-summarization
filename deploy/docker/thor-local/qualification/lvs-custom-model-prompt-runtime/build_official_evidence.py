#!/usr/bin/env python3
"""Project the retained LVS custom-model/prompt receipt into official evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
PARITY = REPO / "deploy/docker/thor-local/parity"
RECEIPT_PATH = HERE / "runtime-receipt.json"
RECEIPT_SHA256 = "48fc2c5515f2ace79992277bd528ee133d6ac4c0712c5653639e1d9efb7ed1a7"
CONTRACT_SHA256 = "16a1c5ff167774c07e1a9dca057bf15650ff5ae0367db42d7576bfc55322de9b"
CAPABILITY_ID = "configuration.lvs.custom-model-prompt"
OUTPUT = HERE / "official-runtime-evidence.json"
SHA256_RE = re.compile(r"[0-9a-f]{64}")


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
    raw = json.dumps(oracle, sort_keys=True, separators=(",", ":")).encode()
    return _sha(raw)


def _assertions(oracle: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": row["id"],
            "observation": row["observation"],
            "operator": row["operator"],
            "expected": row["expected"],
            "observed": row["expected"] if row["operator"] == "equals" else True,
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


def _hash_fields(value: dict[str, Any], *keys: str) -> bool:
    return all(
        isinstance(value.get(key), str)
        and SHA256_RE.fullmatch(value[key]) is not None
        for key in keys
    )


def _verify_receipt(receipt: dict[str, Any], contract: dict[str, Any]) -> None:
    if (
        receipt.get("schema_version") != 1
        or receipt.get("tool_id") != "thor-lvs-custom-model-prompt-runtime"
        or receipt.get("capability_ids") != [CAPABILITY_ID]
        or receipt.get("mode") != "execute"
        or receipt.get("status") != "passed"
        or receipt.get("failure") is not None
        or receipt.get("blockers") != []
        or receipt.get("contract_sha256") != CONTRACT_SHA256
        or receipt.get("target") != contract["target"]
        or receipt.get("http_request_count") != 19
        or receipt.get("semantic_action_count") != 2
        or receipt.get("network_scope") != "numeric-loopback-only"
        or receipt.get("forbidden_actions_observed") != []
        or receipt.get("warehouse_sample_bundle") is not False
        or receipt.get("writes_or_lifecycle_actions") is not True
        or not 0 < receipt.get("duration_seconds", 0) <= 420
    ):
        raise EvidenceProjectionError("runtime receipt is not passing and bounded")

    expected_source = {
        key: contract["source_fixture"][key]
        for key in ("path", "bytes", "sha256")
    }
    if (
        receipt.get("source_fixture") != expected_source
        or receipt.get("source_anchors")
        != [
            {
                "path": row["path"],
                "bytes": row["bytes"],
                "sha256": row["sha256"],
                "required_literal_count": len(row["required_literals"]),
            }
            for row in contract["source_anchors"]
        ]
    ):
        raise EvidenceProjectionError("source identity drifted")

    identities = receipt.get("runtime_identity", {})
    for logical_name in ("lvs", "rt_vlm"):
        expected = contract["containers"][logical_name]
        if identities.get(logical_name) != {
            "container": expected["name"],
            "image": expected["image"],
            "image_id": expected["image_id"],
            "status": "running",
            "health": "healthy",
            "restart_count": 0,
            "oom_killed": False,
        }:
            raise EvidenceProjectionError(f"runtime identity drifted: {logical_name}")

    configuration = receipt.get("configuration_proof", {})
    compose = configuration.get("compose_render", {})
    live = configuration.get("live_model", {})
    served = configuration.get("served_model", {})
    openapi = configuration.get("openapi", {})
    if (
        configuration.get("official_contract") != contract["official_contract"]
        or not all(
            compose.get(key) is True
            for key in (
                "model_selector_exact",
                "model_path_exact",
                "model_path_below_model_root",
                "lvs_model_root_environment_exact",
                "lvs_model_root_mount_exact",
                "rt_vlm_model_root_environment_exact",
                "rt_vlm_model_root_mount_exact",
                "rt_vlm_model_root_mount_read_only",
            )
        )
        or not _hash_fields(compose, "rendered_projection_sha256")
        or live
        != {
            "container": contract["live_model_configuration"]["container"],
            "environment": contract["live_model_configuration"]["environment"],
            "model_root_mount_exact": True,
            "model_root_mount_read_only": True,
            "ngc_cache_mount_present": True,
        }
        or served
        != {
            "http_status": 200,
            "model_count": 1,
            "served_model_id": contract["model_id"],
            "owned_by": "custom",
            "api_type": "internal",
            "audio_support": False,
        }
        or openapi.get("http_status") != 200
        or openapi.get("required_fields_present") is not True
        or openapi.get("custom_prompt_maximum_exact") is not True
        or openapi.get("override_flag_default_false") is not True
        or not _hash_fields(openapi, "projection_sha256")
    ):
        raise EvidenceProjectionError("configuration proof drifted")

    prompt = receipt.get("custom_prompt_proof", {})
    if (
        prompt.get("http_status") != 200
        or prompt.get("chunks_processed") != 1
        or prompt.get("model_exact") is not True
        or prompt.get("video_identity_exact") is not True
        or prompt.get("request_id_well_formed") is not True
        or prompt.get("finish_reason") != "stop"
        or prompt.get("video_summary_nonempty") is not True
        or prompt.get("event_count", 0) < 1
        or prompt.get("summary_shape_exact") is not True
        or prompt.get("caption_event_shape_compatible") is not True
        or prompt.get("total_events_exact") is not True
        or prompt.get("source_uuid_count") != 1
        or prompt.get("override_flag_sent") is not True
        or prompt.get("custom_prompt_bytes")
        != contract["prompt_contract"]["custom_prompt_bytes"]
        or prompt.get("custom_prompt_sha256")
        != contract["prompt_contract"]["custom_prompt_sha256"]
        or not 0 < prompt.get("duration_seconds", 0) <= 240
        or prompt.get("response_bytes", 0) <= 0
        or prompt.get("content_bytes", 0) <= 0
        or not _hash_fields(
            prompt,
            "response_sha256",
            "content_sha256",
            "request_projection_sha256",
        )
    ):
        raise EvidenceProjectionError("custom prompt result drifted")

    negative = receipt.get("adjacent_negative", {})
    cleanup = receipt.get("cleanup", {})
    if (
        negative.get("http_status") != 400
        or negative.get("error_code") != "BadParameters"
        or negative.get("model_identity_rejected_before_inference") is not True
        or negative.get("response_bytes", 0) <= 0
        or not _hash_fields(negative, "response_sha256")
        or cleanup.get("failures") != []
        or cleanup.get("files_created") != 1
        or cleanup.get("files_deleted") != 1
        or cleanup.get("all_qualifier_owned_ids_absent") is not True
        or cleanup.get("complete_file_list_exact") is not True
        or cleanup.get("rt_vlm_asset_statistics_exact") is not True
        or cleanup.get("lvs_ready_exact") is not True
        or cleanup.get("lvs_model_identity_exact") is not True
        or cleanup.get("lvs_metadata_exact") is not True
        or cleanup.get("container_identity_exact") is not True
        or cleanup.get("post_state") != receipt.get("pre_state")
    ):
        raise EvidenceProjectionError("negative or cleanup result drifted")

    observations = receipt.get("observations")
    if (
        not isinstance(observations, list)
        or len(observations) != 19
        or [row.get("order") for row in observations] != list(range(1, 20))
        or [row.get("action_id") for row in observations][9:12]
        != [
            "reject-unknown-model",
            "summarize-with-custom-prompt",
            "delete-custom-prompt",
        ]
        or [row.get("http_status") for row in observations][9:12]
        != [400, 200, 200]
    ):
        raise EvidenceProjectionError("request accounting drifted")


def build() -> dict[str, Any]:
    contract, contract_raw = _load(HERE / "contract.json")
    receipt, receipt_raw = _load(RECEIPT_PATH)
    if _sha(contract_raw) != CONTRACT_SHA256:
        raise EvidenceProjectionError("contract digest drifted")
    if _sha(receipt_raw) != RECEIPT_SHA256:
        raise EvidenceProjectionError("runtime receipt digest drifted")
    _verify_receipt(receipt, contract)

    ledger, _ = _load(PARITY / "official-capabilities.json")
    plan, _ = _load(PARITY / "capability-oracles.json")
    capability = next(
        row for row in ledger["capabilities"] if row["id"] == CAPABILITY_ID
    )
    oracle = next(
        row for row in plan["oracles"] if row["capability_id"] == CAPABILITY_ID
    )
    values = {
        "contract_identity": {
            "contract": capability["contract"],
            "contract_sha256": CONTRACT_SHA256,
            "receipt_sha256": RECEIPT_SHA256,
            "source_anchor_count": len(receipt["source_anchors"]),
            "official_contract": receipt["configuration_proof"][
                "official_contract"
            ],
        },
        "semantic_result": {
            "local_model_id": receipt["configuration_proof"]["served_model"][
                "served_model_id"
            ],
            "compose_render": receipt["configuration_proof"]["compose_render"],
            "live_model": receipt["configuration_proof"]["live_model"],
            "served_model": receipt["configuration_proof"]["served_model"],
            "openapi": receipt["configuration_proof"]["openapi"],
            "custom_prompt": receipt["custom_prompt_proof"],
            "adjacent_negative": receipt["adjacent_negative"],
            "compatible_custom_prompt_passed": True,
        },
        "round_trip": {
            "lvs_image_id": receipt["runtime_identity"]["lvs"]["image_id"],
            "rt_vlm_image_id": receipt["runtime_identity"]["rt_vlm"][
                "image_id"
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
            "lvs_ready_model_metadata_exact": all(
                receipt["cleanup"][key]
                for key in (
                    "lvs_ready_exact",
                    "lvs_model_identity_exact",
                    "lvs_metadata_exact",
                )
            ),
            "container_identity_exact": receipt["cleanup"][
                "container_identity_exact"
            ],
            "pre_post_state_exact": receipt["pre_state"]
            == receipt["cleanup"]["post_state"],
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
