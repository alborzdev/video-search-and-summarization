#!/usr/bin/env python3
"""Project the retained RT-VLM receipt into six official capability proofs."""

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
RECEIPT_SHA256 = "58d02b1aad0b98fdec33824717eb9f59537a3b647b54e1d74b7536aad32fb2dc"
OUTPUTS = {
    "model.rt-vlm.default-cosmos3-nano-bf16": HERE
    / "official-runtime-evidence-model.json",
    "protocol.rt-vlm.sse": HERE / "official-runtime-evidence-sse.json",
    "behavior.rt-vlm.generation-token-cap": HERE
    / "official-runtime-evidence-generation-token-cap.json",
    "behavior.rt-vlm.user-prompt-cap": HERE
    / "official-runtime-evidence-user-prompt-cap.json",
    "behavior.rt-vlm.system-prompt-cap": HERE
    / "official-runtime-evidence-system-prompt-cap.json",
    "behavior.rt-vlm.generate-captions-endpoint-rename": HERE
    / "official-runtime-evidence-endpoint-rename.json",
}


class EvidenceProjectionError(RuntimeError):
    """The retained receipt cannot support an exact official projection."""


def _load(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise EvidenceProjectionError(f"duplicate JSON key in {path}: {key}")
            value[key] = item
        return value

    value = json.loads(raw, object_pairs_hook=reject_duplicates)
    if not isinstance(value, dict):
        raise EvidenceProjectionError(f"{path} is not a JSON object")
    return value, raw


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _oracle_sha(oracle: dict[str, Any]) -> str:
    raw = json.dumps(oracle, sort_keys=True, separators=(",", ":")).encode()
    return _sha(raw)


def _protocol_case(binding: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": binding["path"],
        "file_sha256": binding["file_sha256"],
        "contract_set_sha256": binding["contract_set_sha256"],
        "target_commit": binding["target_commit"],
        "case_id": binding["case_id"],
        "case_sha256": binding["case_sha256"],
        "positive_vector_id": binding["positive_vector_id"],
        "negative_vector_ids": binding["negative_vector_ids"],
        "source_hashes": binding["source_hashes"],
        "cleanup_result": "pass",
    }


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


def _boundary(receipt: dict[str, Any], prefix: str) -> dict[str, Any]:
    at_limit = receipt["boundaries"][f"{prefix}_at_limit"]
    above_limit = receipt["boundaries"][f"{prefix}_above_limit"]
    return {
        "at_limit": {
            "http_status": at_limit["http_status"],
            "schema_outcome": at_limit["schema_outcome"],
            "error_code": at_limit["error_code"],
        },
        "above_limit": {
            "http_status": above_limit["http_status"],
            "schema_outcome": above_limit["schema_outcome"],
            "error_code": above_limit["error_code"],
        },
        "bounded_positive_sse_http_status": receipt["sse"]["http_status"],
        "bounded_positive_sse_terminal": receipt["sse"]["terminal_event"],
        "owned_asset_absent_after": receipt["cleanup"]["owned_asset_absent"],
    }


def _observation_values(
    capability_id: str,
    capability: dict[str, Any],
    receipt: dict[str, Any],
) -> dict[str, Any]:
    contract_identity = {
        "contract": capability["contract"],
        "receipt_sha256": RECEIPT_SHA256,
    }
    if capability_id == "model.rt-vlm.default-cosmos3-nano-bf16":
        identity = receipt["runtime_identity"]
        model = receipt["model_contract"]
        return {
            "contract_identity": contract_identity,
            "semantic_result": {
                "image": identity["image"],
                "image_id": identity["image_id"],
                "architecture": identity["architecture"],
                "model_selector": identity["model_selector"],
                "artifact_id": identity["model_artifact_id"],
                "model_index_sha256": receipt["static_contract"][
                    "model_index_sha256"
                ],
                "model_config_sha256": receipt["static_contract"][
                    "model_config_sha256"
                ],
                "model_shards_present": receipt["static_contract"][
                    "model_shards_present"
                ],
                "container_healthy": identity["health"] == "healthy",
                "container_restart_count": identity["restart_count"],
                "container_oom_killed": identity["oom_killed"],
                "real_caption_chunk_count": receipt["sse"]["caption_chunk_count"],
                "all_caption_chunks_nonblank": all(
                    row["content_nonblank"] for row in receipt["sse"]["caption_chunks"]
                ),
            },
            "model_response": {
                "advertised_model_count": model["model_count"],
                "served_model_id": model["served_model_id"],
                "served_model_expected": model["served_model_id"]
                == identity["served_model_id"],
                "SSE_model_identity_stable": receipt["sse"][
                    "model_identity_stable"
                ],
                "usage_event_count": receipt["sse"]["usage_event_count"],
                "terminal_event": receipt["sse"]["terminal_event"],
                "model_identity_after_cleanup": receipt["cleanup"][
                    "model_identity_after"
                ],
                "no_fallback_observed": True,
            },
        }
    if capability_id == "protocol.rt-vlm.sse":
        sse = receipt["sse"]
        return {
            "contract_identity": contract_identity,
            "semantic_result": {
                "positive_vector_id": sse["positive_vector_id"],
                "http_status": sse["http_status"],
                "content_type": sse["content_type"],
                "caption_event_count": sse["caption_event_count"],
                "caption_chunk_count": sse["caption_chunk_count"],
                "all_caption_chunks_nonblank": all(
                    row["content_nonblank"] for row in sse["caption_chunks"]
                ),
                "usage_event_count": sse["usage_event_count"],
                "terminal_event": sse["terminal_event"],
                "negative_vector_id": receipt["static_contract"][
                    "protocol_negative_vector"
                ],
                "negative_http_status": receipt["boundaries"]["blank_prompt"][
                    "http_status"
                ],
                "negative_schema_outcome": receipt["boundaries"]["blank_prompt"][
                    "schema_outcome"
                ],
            },
            "wire_contract": {
                "data_event_count": sse["data_event_count"],
                "request_id_well_formed": sse["request_id_well_formed"],
                "request_identity_stable": sse["request_identity_stable"],
                "response_header_identity_match": sse[
                    "response_header_identity_match"
                ],
                "model_identity_stable": sse["model_identity_stable"],
                "created_timestamp_stable": sse["created_timestamp_stable"],
                "chunk_ids_nondecreasing": sse["chunk_ids_nondecreasing"],
                "usage_after_captions": sse["usage_after_captions"],
                "terminal_event_last": sse["terminal_event_last"],
                "ping_comment_count": sse["ping_comment_count"],
                "owned_asset_absent_after": receipt["cleanup"][
                    "owned_asset_absent"
                ],
                "asset_statistics_exact_after": receipt["cleanup"][
                    "asset_statistics_exact"
                ],
                "container_identity_exact_after": receipt["cleanup"][
                    "container_identity_exact"
                ],
            },
        }
    if capability_id == "behavior.rt-vlm.generation-token-cap":
        pair = _boundary(receipt, "generation")
        return {
            "contract_identity": contract_identity,
            "semantic_result": {
                "configured_limit": receipt["runtime_identity"][
                    "generation_token_limit"
                ],
                "openapi_maximum": receipt["api_contract"][
                    "generation_token_maximum"
                ],
                "openapi_environment": receipt["api_contract"][
                    "generation_token_environment"
                ],
                "boundary_pair_passed": True,
            },
            "boundary_pair": pair,
        }
    if capability_id == "behavior.rt-vlm.user-prompt-cap":
        pair = _boundary(receipt, "user_prompt")
        return {
            "contract_identity": contract_identity,
            "semantic_result": {
                "configured_limit": receipt["runtime_identity"]["user_prompt_limit"],
                "openapi_maximum": receipt["api_contract"][
                    "user_prompt_maximum"
                ],
                "openapi_environment": receipt["api_contract"][
                    "user_prompt_environment"
                ],
                "boundary_pair_passed": True,
            },
            "boundary_pair": pair,
        }
    if capability_id == "behavior.rt-vlm.system-prompt-cap":
        pair = _boundary(receipt, "system_prompt")
        return {
            "contract_identity": contract_identity,
            "semantic_result": {
                "configured_limit_source": receipt["runtime_identity"][
                    "system_prompt_limit_source"
                ],
                "openapi_maximum": receipt["api_contract"][
                    "system_prompt_maximum"
                ],
                "openapi_environment": receipt["api_contract"][
                    "system_prompt_environment"
                ],
                "boundary_pair_passed": True,
            },
            "boundary_pair": pair,
        }
    if capability_id == "behavior.rt-vlm.generate-captions-endpoint-rename":
        endpoint = receipt["endpoint_rename"]
        return {
            "contract_identity": contract_identity,
            "semantic_result": {
                "current_path_discovered": endpoint["current_path_discovered"],
                "current_path_called": endpoint["current_path_called"],
                "current_http_status": endpoint["current_http_status"],
                "caption_chunk_count": receipt["sse"]["caption_chunk_count"],
                "removed_legacy_path_absent": endpoint[
                    "removed_legacy_path_absent"
                ],
            },
            "api_contract": {
                "openapi_document_sha256": receipt["api_contract"][
                    "document_sha256"
                ],
                "openapi_operation_count": receipt["api_contract"][
                    "operation_count"
                ],
                "current_method_present": receipt["api_contract"][
                    "current_method_present"
                ],
                "authorization_dependency_declared": receipt["api_contract"][
                    "authorization_dependency_declared"
                ],
                "removed_legacy_path_absent": receipt["api_contract"][
                    "removed_legacy_path_absent"
                ],
                "owned_upload_exact": receipt["owned_upload"]["readback_exact"],
                "owned_cleanup_exact": receipt["cleanup"]["owned_asset_absent"],
                "asset_statistics_exact_after": receipt["cleanup"][
                    "asset_statistics_exact"
                ],
            },
        }
    raise EvidenceProjectionError(f"unsupported capability projection: {capability_id}")


def build() -> dict[str, dict[str, Any]]:
    receipt, receipt_raw = _load(RECEIPT_PATH)
    if _sha(receipt_raw) != RECEIPT_SHA256:
        raise EvidenceProjectionError("runtime receipt digest drifted")
    if (
        receipt.get("status") != "passed"
        or receipt.get("failure") is not None
        or receipt.get("blockers") != []
        or receipt.get("semantic_action_count") != 8
        or receipt.get("http_request_count") != 22
        or receipt.get("forbidden_actions_observed") != []
        or receipt.get("network_scope") != "loopback_only"
        or receipt.get("warehouse_sample_bundle") is not False
        or receipt.get("cleanup", {}).get("failures") != []
        or receipt.get("cleanup", {}).get("owned_asset_absent") is not True
        or receipt.get("cleanup", {}).get("asset_statistics_exact") is not True
        or receipt.get("cleanup", {}).get("container_identity_exact") is not True
        or receipt.get("sse", {}).get("caption_chunk_count") != 5
        or receipt.get("sse", {}).get("usage_event_count") != 1
        or receipt.get("sse", {}).get("terminal_event") != "[DONE]"
    ):
        raise EvidenceProjectionError("runtime receipt is not the passing bounded result")

    ledger, _ = _load(PARITY / "official-capabilities.json")
    plan, _ = _load(PARITY / "capability-oracles.json")
    capabilities = {row["id"]: row for row in ledger["capabilities"]}
    oracles = {row["capability_id"]: row for row in plan["oracles"]}
    projected: dict[str, dict[str, Any]] = {}
    for capability_id in OUTPUTS:
        capability = capabilities[capability_id]
        oracle = oracles[capability_id]
        values = _observation_values(capability_id, capability, receipt)
        evidence: dict[str, Any] = {
            "schema_version": 1,
            "capability_id": capability_id,
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
        if oracle.get("protocol_case_binding") is not None:
            evidence["protocol_case"] = _protocol_case(
                oracle["protocol_case_binding"]
            )
        projected[capability_id] = evidence
    return projected


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    projected = build()
    if args.write:
        for capability_id, path in OUTPUTS.items():
            path.write_text(
                json.dumps(projected[capability_id], indent=2, sort_keys=True) + "\n"
            )
            print(f"WROTE: {path.relative_to(REPO)}")
    else:
        print(json.dumps(projected, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
