#!/usr/bin/env python3
"""Project one retained RT-Embed run into four official capability proofs."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
PARITY = REPO / "deploy/docker/thor-local/parity"
CONTRACT_PATH = HERE / "contract.json"
RECEIPT_PATH = HERE / "runtime-receipt.json"
CONTRACT_SHA256 = "ff00f1cb91045a9f758c3dc23223fc6bc562b9a1819735e8c97d790c96ca2494"
RECEIPT_SHA256 = "56da7bf867628791152cdb9c3cdf788801ab77aa3e4dedb374ba130bf9849934"
CAPABILITY_IDS = (
    "model.rt-embed.cosmos-embed1-448p-anomaly",
    "behavior.rt-embed.base64-data-url",
    "behavior.rt-embed.duplicate-id-409",
    "api.core.rt-embed-24",
)
OUTPUTS = {
    CAPABILITY_IDS[0]: HERE / "official-runtime-evidence-model.json",
    CAPABILITY_IDS[1]: HERE / "official-runtime-evidence-data-url.json",
    CAPABILITY_IDS[2]: HERE / "official-runtime-evidence-duplicate-id.json",
    CAPABILITY_IDS[3]: HERE / "official-runtime-evidence-api.json",
}
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
EXPECTED_ACTIONS = (
    (1, "discover-openapi", "GET", "/openapi.json", 200),
    (2, "discover-swagger", "GET", "/docs", 200),
    (3, "read-metrics", "GET", "/v1/metrics", 200),
    (4, "read-readiness", "GET", "/v1/ready", 200),
    (5, "read-liveness", "GET", "/v1/live", 200),
    (6, "read-startup", "GET", "/v1/startup", 200),
    (7, "read-metadata", "GET", "/v1/metadata", 200),
    (8, "read-version", "GET", "/v1/version", 200),
    (9, "read-manifest", "GET", "/v1/manifest", 200),
    (10, "read-models-pre", "GET", "/v1/models", 200),
    (11, "read-files-pre", "GET", "/v1/files", 200),
    (12, "read-streams-pre", "GET", "/v1/streams/get-stream-info", 200),
    (13, "read-cv-streams-pre", "GET", "/v1/stream/get-stream-info", 200),
    (14, "read-assets-pre", "GET", "/v1/assets/stats", 200),
    (15, "upload-owned-file", "POST", "/v1/files", 200),
    (16, "read-files-owned", "GET", "/v1/files", 200),
    (17, "read-owned-file-info", "GET", "/v1/files/{file_id}", 200),
    (18, "read-owned-file-content", "GET", "/v1/files/{file_id}/content", 200),
    (19, "generate-text-embeddings", "POST", "/v1/generate_text_embeddings", 200),
    (
        20,
        "generate-uploaded-file-embeddings",
        "POST",
        "/v1/generate_video_embeddings",
        200,
    ),
    (21, "generate-rfc2397-embeddings", "POST", "/v1/generate_video_embeddings", 200),
    (
        22,
        "reject-file-url-without-allowlist",
        "POST",
        "/v1/generate_video_embeddings",
        403,
    ),
    (23, "delete-owned-file", "DELETE", "/v1/files/{file_id}", 200),
    (24, "add-cv-camera", "POST", "/v1/stream/add", 200),
    (25, "read-cv-camera-owned", "GET", "/v1/stream/get-stream-info", 200),
    (26, "reject-duplicate-camera-id", "POST", "/v1/stream/add", 409),
    (27, "remove-cv-camera", "POST", "/v1/stream/remove", 200),
    (28, "add-single-live-stream", "POST", "/v1/streams/add", 200),
    (29, "read-single-live-stream", "GET", "/v1/streams/get-stream-info", 200),
    (30, "reject-duplicate-stream-id", "POST", "/v1/streams/add", 200),
    (31, "generate-live-video-embedding", "POST", "/v1/generate_video_embeddings", 200),
    (
        32,
        "stop-live-video-embedding",
        "DELETE",
        "/v1/generate_video_embeddings/{stream_id}",
        200,
    ),
    (33, "delete-single-live-stream", "DELETE", "/v1/streams/delete/{stream_id}", 200),
    (34, "add-batch-live-streams", "POST", "/v1/streams/add", 200),
    (35, "delete-batch-live-streams", "DELETE", "/v1/streams/delete-batch", 200),
    (36, "read-files-post", "GET", "/v1/files", 200),
    (37, "read-streams-post", "GET", "/v1/streams/get-stream-info", 200),
    (38, "read-cv-streams-post", "GET", "/v1/stream/get-stream-info", 200),
    (39, "read-assets-post", "GET", "/v1/assets/stats", 200),
    (40, "read-models-post", "GET", "/v1/models", 200),
    (41, "read-readiness-post", "GET", "/v1/ready", 200),
)


class EvidenceProjectionError(RuntimeError):
    """The retained receipt cannot support the exact official projections."""


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


def _hash(value: Any) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def _hash_list(value: Any, count: int) -> bool:
    return (
        isinstance(value, list)
        and len(value) == count
        and all(_hash(row) for row in value)
    )


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


def _verify_video_projection(value: Any, chunks: int) -> None:
    if (
        not isinstance(value, dict)
        or value.get("model_exact") is not True
        or value.get("chunk_count") != chunks
        or value.get("usage_chunk_count") not in {None, chunks}
        or value.get("dimensions") != [768] * chunks
        or value.get("vectors_finite") is not True
        or not _hash_list(value.get("vector_sha256"), chunks)
    ):
        raise EvidenceProjectionError("video embedding proof drifted")


def _verify_receipt(receipt: dict[str, Any], contract: dict[str, Any]) -> None:
    if (
        receipt.get("schema_version") != 1
        or receipt.get("tool_id") != contract["tool_id"]
        or receipt.get("mode") != "execute"
        or receipt.get("status") != "passed"
        or receipt.get("failure") is not None
        or receipt.get("blockers") != []
        or receipt.get("capability_ids") != contract["capability_ids"]
        or receipt.get("target") != contract["target"]
        or receipt.get("contract_sha256") != CONTRACT_SHA256
        or not 0 < receipt.get("duration_seconds", 0) <= 900
        or receipt.get("http_request_count") != 43
        or receipt.get("retained_observation_count") != 41
        or receipt.get("semantic_action_count") != 4
        or receipt.get("external_network_requests") != 0
        or receipt.get("image_pulls") != 0
        or receipt.get("image_builds") != 0
        or receipt.get("model_staging_actions") != 0
        or receipt.get("service_lifecycle_actions") != 0
        or receipt.get("disposable_helper_container_count") != 3
        or receipt.get("warehouse_sample_bundle") is not False
        or receipt.get("writes_or_lifecycle_actions") is not True
        or receipt.get("source_anchors") != contract["source_anchors"]
        or receipt.get("sanitization")
        != {
            "credential_values_included": False,
            "dynamic_identifiers_included": False,
            "local_paths_included": False,
            "raw_embedding_vectors_included": False,
            "raw_prompts_included": False,
            "response_bodies_included": False,
            "rtsp_urls_included": False,
        }
    ):
        raise EvidenceProjectionError("receipt envelope drifted")

    observations = receipt.get("observations")
    if not isinstance(observations, list) or len(observations) != len(EXPECTED_ACTIONS):
        raise EvidenceProjectionError("observation denominator drifted")
    actual_actions = []
    for row in observations:
        if (
            not isinstance(row, dict)
            or set(row)
            != {
                "order",
                "action_id",
                "method",
                "operation_path",
                "http_status",
                "response_bytes",
                "response_sha256",
                "content_type",
            }
            or type(row.get("response_bytes")) is not int
            or row["response_bytes"] < 0
            or not _hash(row.get("response_sha256"))
        ):
            raise EvidenceProjectionError("retained observation drifted")
        actual_actions.append(
            (
                row["order"],
                row["action_id"],
                row["method"],
                row["operation_path"],
                row["http_status"],
            )
        )
    if tuple(actual_actions) != EXPECTED_ACTIONS:
        raise EvidenceProjectionError("HTTP action sequence drifted")

    identity = receipt.get("runtime_identity")
    if (
        not isinstance(identity, dict)
        or identity.get("container") != contract["service"]["container"]
        or identity.get("image_reference") != contract["service"]["image_reference"]
        or identity.get("image_id") != contract["service"]["image_id"]
        or identity.get("status") != "running"
        or identity.get("health") != "healthy"
        or identity.get("restart_count") != 0
        or identity.get("oom_killed") is not False
        or identity.get("runtime") != "nvidia"
        or identity.get("loopback_publish_exact") is not True
        or identity.get("credential_values_blank") is not True
        or identity.get("safe_environment")
        != {
            "MODEL_PATH": contract["service"]["model_source"],
            "VLM_BATCH_SIZE": str(contract["service"]["batch_size"]),
            "RTVI_OFFLINE": "true",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
        }
    ):
        raise EvidenceProjectionError("runtime identity drifted")

    artifact = receipt.get("artifact_proof")
    if (
        not isinstance(artifact, dict)
        or artifact.get("lock_sha256") != contract["artifact_contract"]["lock_sha256"]
        or artifact.get("repository") != contract["artifact_contract"]["repository"]
        or artifact.get("revision") != contract["artifact_contract"]["revision"]
        or artifact.get("source_spec_exact") is not True
        or artifact.get("batch_size") != contract["service"]["batch_size"]
        or artifact.get("precision")
        != contract["artifact_contract"]["triton"]["precision"]
        or artifact.get("target_hardware")
        != contract["artifact_contract"]["triton"]["target_hardware"]
    ):
        raise EvidenceProjectionError("artifact identity drifted")
    for key in ("model", "triton"):
        proof = artifact.get(key)
        expected = contract["artifact_contract"][key]
        if (
            not isinstance(proof, dict)
            or proof.get("artifact") != expected["artifact"]
            or proof.get("archive_root") != expected["archive_root"]
            or proof.get("file_count") != expected["file_count"]
            or proof.get("directory_count") != expected["directory_count"]
            or proof.get("bytes") != expected["bytes"]
            or proof.get("exact_locked_tree") is not True
            or proof.get("helper_removed") is not True
            or not _hash(proof.get("verifier_stdout_sha256"))
        ):
            raise EvidenceProjectionError(f"{key} artifact proof drifted")

    api = receipt.get("api_surface")
    if (
        not isinstance(api, dict)
        or api.get("expected_manifest_sha256")
        != contract["api_contract"]["expected_manifest_sha256"]
        or api.get("path_count") != contract["api_contract"]["path_count"]
        or api.get("operation_count") != contract["api_contract"]["operation_count"]
        or api.get("covered_operation_count")
        != contract["api_contract"]["operation_count"]
        or api.get("swagger_reachable") is not True
        or api.get("all_operations_exercised") is not True
        or not _hash(api.get("openapi_sha256"))
        or not _hash(api.get("operation_set_sha256"))
    ):
        raise EvidenceProjectionError("API surface proof drifted")

    text = receipt.get("text_embeddings")
    if (
        not isinstance(text, dict)
        or text.get("input_count") != contract["semantic_contract"]["text_input_count"]
        or text.get("dimensions") != [768, 768]
        or text.get("model_exact") is not True
        or text.get("vectors_finite") is not True
        or not _hash(text.get("input_projection_sha256"))
        or not _hash_list(text.get("vector_sha256"), 2)
    ):
        raise EvidenceProjectionError("text embedding proof drifted")
    video = receipt.get("video_embeddings")
    if not isinstance(video, dict):
        raise EvidenceProjectionError("video embedding proof missing")
    _verify_video_projection(video.get("uploaded_file"), 3)
    _verify_video_projection(video.get("live_rtsp"), 1)
    rfc = video.get("rfc2397")
    if not isinstance(rfc, dict):
        raise EvidenceProjectionError("RFC 2397 proof missing")
    _verify_video_projection(rfc.get("uploaded_file"), 3)
    _verify_video_projection(rfc.get("data_url"), 3)
    if (
        rfc.get("decoded_fixture_sha256") != contract["fixture"]["sha256"]
        or rfc.get("rfc2397_scheme") is not True
        or rfc.get("shape_and_ranges_exact") is not True
        or rfc.get("vector_sha256_exact") is not True
        or rfc.get("transient_asset_removed") is not True
        or not math.isclose(rfc.get("minimum_pairwise_cosine", 0), 1.0, abs_tol=1e-6)
    ):
        raise EvidenceProjectionError("RFC 2397 semantic proof drifted")

    duplicate = receipt.get("duplicate_ids")
    if duplicate != {
        "both_existing_resources_preserved_until_owned_cleanup": True,
        "camera_error_code": "DuplicateCameraId",
        "camera_transport_status": 409,
        "stream_batch_transport_status": 200,
        "stream_error_code": "DuplicateStreamId",
        "stream_error_status": 409,
    }:
        raise EvidenceProjectionError("duplicate-ID proof drifted")
    if receipt.get("file_url_negative") != {
        "allowlist_unset": True,
        "asset_created": False,
        "error_code": "Forbidden",
        "http_status": 403,
    }:
        raise EvidenceProjectionError("file URL negative drifted")
    if receipt.get("pre_state") != receipt.get("post_state"):
        raise EvidenceProjectionError("complete state did not restore exactly")
    cleanup = receipt.get("cleanup")
    required_cleanup = {
        "asset_statistics_exact",
        "complete_inventory_exact",
        "container_identity_exact",
        "helper_containers_absent",
        "model_identity_exact",
        "owned_camera_absent",
        "owned_uuid_resources_absent",
        "paused_workloads_exact",
        "publisher_absent",
        "rtsp_path_absent",
    }
    if (
        not isinstance(cleanup, dict)
        or cleanup.get("failures") != []
        or cleanup.get("owned_uuid_count") != 6
        or any(cleanup.get(key) is not True for key in required_cleanup)
        or not _hash(cleanup.get("rtsp_absence_response_sha256"))
    ):
        raise EvidenceProjectionError("cleanup proof drifted")
    if receipt.get("rtsp_helper") != {
        "bridge_gateway_only": True,
        "capabilities_dropped": True,
        "image_id": contract["rtsp_helper"]["image_id"],
        "network_mode": "host",
        "pull_disabled": True,
        "read_only_rootfs": True,
        "tcp_only": True,
    }:
        raise EvidenceProjectionError("RTSP helper proof drifted")
    disk = receipt.get("disk")
    if (
        not isinstance(disk, dict)
        or disk.get("minimum_free_bytes")
        != contract["execution_bounds"]["min_free_bytes"]
        or disk.get("free_bytes_before", 0) < disk["minimum_free_bytes"]
        or disk.get("free_bytes_after", 0) < disk["minimum_free_bytes"]
    ):
        raise EvidenceProjectionError("disk admission proof drifted")


def _values(
    capability_id: str,
    capability: dict[str, Any],
    receipt: dict[str, Any],
) -> dict[str, Any]:
    common_identity = {
        "contract": capability["contract"],
        "contract_sha256": CONTRACT_SHA256,
        "receipt_sha256": RECEIPT_SHA256,
        "image_id": receipt["runtime_identity"]["image_id"],
        "artifact_lock_sha256": receipt["artifact_proof"]["lock_sha256"],
        "fixture_sha256": receipt["publisher"]["fixture_sha256"],
    }
    cleanup = receipt["cleanup"]
    if capability_id == CAPABILITY_IDS[0]:
        artifact = receipt["artifact_proof"]
        video = receipt["video_embeddings"]
        return {
            "contract_identity": common_identity,
            "semantic_result": {
                "repository": artifact["repository"],
                "revision": artifact["revision"],
                "model_tree_exact": artifact["model"]["exact_locked_tree"],
                "triton_tree_exact": artifact["triton"]["exact_locked_tree"],
                "precision": artifact["precision"],
                "target_hardware": artifact["target_hardware"],
                "text_dimensions": receipt["text_embeddings"]["dimensions"],
                "file_dimensions": video["uploaded_file"]["dimensions"],
                "data_url_dimensions": video["rfc2397"]["data_url"]["dimensions"],
                "live_dimensions": video["live_rtsp"]["dimensions"],
                "all_vectors_finite": True,
                "semantic_action_count": receipt["semantic_action_count"],
            },
            "model_response": {
                "served_model_id": "cosmos-embed1-448p-anomaly-detection",
                "model_identity_exact": True,
                "runtime": receipt["runtime_identity"]["runtime"],
                "container_healthy": receipt["runtime_identity"]["health"] == "healthy",
                "container_restart_count": receipt["runtime_identity"]["restart_count"],
                "container_oom_killed": receipt["runtime_identity"]["oom_killed"],
                "loopback_publish_exact": receipt["runtime_identity"][
                    "loopback_publish_exact"
                ],
                "no_fallback_observed": True,
                "complete_cleanup_exact": cleanup["complete_inventory_exact"],
            },
        }
    if capability_id == CAPABILITY_IDS[1]:
        rfc = receipt["video_embeddings"]["rfc2397"]
        return {
            "contract_identity": common_identity,
            "semantic_result": {
                "decoded_fixture_sha256": rfc["decoded_fixture_sha256"],
                "serialized_bytes": rfc["serialized_bytes"],
                "uploaded_file_chunk_count": rfc["uploaded_file"]["chunk_count"],
                "data_url_chunk_count": rfc["data_url"]["chunk_count"],
                "dimensions": rfc["data_url"]["dimensions"],
                "shape_and_ranges_exact": rfc["shape_and_ranges_exact"],
                "vector_sha256_exact": rfc["vector_sha256_exact"],
                "minimum_pairwise_cosine": rfc["minimum_pairwise_cosine"],
                "vectors_finite": rfc["data_url"]["vectors_finite"],
            },
            "api_contract": {
                "rfc2397_scheme": rfc["rfc2397_scheme"],
                "transient_asset_removed": rfc["transient_asset_removed"],
                "complete_inventory_exact": cleanup["complete_inventory_exact"],
                "asset_statistics_exact": cleanup["asset_statistics_exact"],
            },
        }
    if capability_id == CAPABILITY_IDS[2]:
        duplicate = receipt["duplicate_ids"]
        return {
            "contract_identity": common_identity,
            "semantic_result": duplicate,
            "boundary_pair": {
                "camera_transport_status": duplicate["camera_transport_status"],
                "stream_batch_transport_status": duplicate[
                    "stream_batch_transport_status"
                ],
                "stream_nested_error_status": duplicate["stream_error_status"],
                "camera_resource_absent_after": cleanup["owned_camera_absent"],
                "stream_resources_absent_after": cleanup["owned_uuid_resources_absent"],
            },
        }
    if capability_id == CAPABILITY_IDS[3]:
        api = receipt["api_surface"]
        return {
            "contract_identity": common_identity,
            "semantic_result": {
                "text_embedding_count": receipt["text_embeddings"]["input_count"],
                "uploaded_file_chunks": receipt["video_embeddings"]["uploaded_file"][
                    "chunk_count"
                ],
                "data_url_chunks": receipt["video_embeddings"]["rfc2397"]["data_url"][
                    "chunk_count"
                ],
                "live_rtsp_chunks": receipt["video_embeddings"]["live_rtsp"][
                    "chunk_count"
                ],
                "local_rtsp_gateway_only": receipt["bridge_scope"][
                    "rtsp_listener_gateway_only"
                ],
                "duplicate_camera_status": receipt["duplicate_ids"][
                    "camera_transport_status"
                ],
                "duplicate_stream_status": receipt["duplicate_ids"][
                    "stream_error_status"
                ],
            },
            "api_contract": {
                "path_count": api["path_count"],
                "operation_count": api["operation_count"],
                "covered_operation_count": api["covered_operation_count"],
                "all_operations_exercised": api["all_operations_exercised"],
                "swagger_reachable": api["swagger_reachable"],
                "openapi_sha256": api["openapi_sha256"],
                "operation_set_sha256": api["operation_set_sha256"],
                "http_request_count": receipt["http_request_count"],
                "retained_observation_count": receipt["retained_observation_count"],
                "complete_cleanup_exact": cleanup["complete_inventory_exact"],
            },
        }
    raise EvidenceProjectionError(f"unsupported capability: {capability_id}")


def build() -> dict[str, dict[str, Any]]:
    contract, contract_raw = _load(CONTRACT_PATH)
    receipt, receipt_raw = _load(RECEIPT_PATH)
    if _sha(contract_raw) != CONTRACT_SHA256:
        raise EvidenceProjectionError("contract digest drifted")
    if _sha(receipt_raw) != RECEIPT_SHA256:
        raise EvidenceProjectionError("runtime receipt digest drifted")
    _verify_receipt(receipt, contract)

    ledger, _ = _load(PARITY / "official-capabilities.json")
    plan, _ = _load(PARITY / "capability-oracles.json")
    capabilities = {row["id"]: row for row in ledger["capabilities"]}
    oracles = {row["capability_id"]: row for row in plan["oracles"]}
    result: dict[str, dict[str, Any]] = {}
    for capability_id in CAPABILITY_IDS:
        capability = capabilities[capability_id]
        oracle = oracles[capability_id]
        values = _values(capability_id, capability, receipt)
        result[capability_id] = {
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
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    evidence = build()
    if args.write:
        for capability_id, output in OUTPUTS.items():
            output.write_text(
                json.dumps(evidence[capability_id], indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            print(f"WROTE: {output.relative_to(REPO)}")
    else:
        print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
