#!/usr/bin/env python3
"""Verify retained Thor RT-VLM SSE evidence and all six official projections."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
PARITY = REPO / "deploy/docker/thor-local/parity"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(PARITY))

import build_official_evidence  # noqa: E402
import capability_oracles  # noqa: E402
import verify_official_capabilities  # noqa: E402


CAPABILITY_IDS = list(build_official_evidence.OUTPUTS)
EXPECTED = {
    "contract": "d55420ca0f3da9fc82de4ab6d189df7fd41fff4848053fce5b1963b375546748",
    "receipt": "58d02b1aad0b98fdec33824717eb9f59537a3b647b54e1d74b7536aad32fb2dc",
    "evidence": {
        "model.rt-vlm.default-cosmos3-nano-bf16": "521fc7654d534f3386226b80f434a07dbc8e5441d41eda5272ca767fcdb5ed37",
        "protocol.rt-vlm.sse": "0096ad41d24b43245e101a37b7374bed339a9034d412a09308797f2d02623e80",
        "behavior.rt-vlm.generation-token-cap": "4936c7fae8b31038fc94908b085f3f54e5d0bec7e22d36d2186808d9869164a9",
        "behavior.rt-vlm.user-prompt-cap": "b72c23be954d6f9ca835ade9ef4d23ab464885a13fffffa5c7cce35e46bc0c0d",
        "behavior.rt-vlm.system-prompt-cap": "99d4cc8b5de628309fb664d34fd33544cf86cc34de0af7a538ab9ebf20cb2fb0",
        "behavior.rt-vlm.generate-captions-endpoint-rename": "75489ca7e10002389b7d5d5f6babbcfe5df1264008964f5687c69e7b00c7b81d",
    },
    "oracle": {
        "model.rt-vlm.default-cosmos3-nano-bf16": "616f6c03305c4e7c6e4273bb7a5cdbe488b48b1b01935cd84ff9c06dcc9a8743",
        "protocol.rt-vlm.sse": "409411772cc71b7592c7b98601b1ef87f26d884c1e20716370f4fee63fa74bf9",
        "behavior.rt-vlm.generation-token-cap": "ea148cd858a23203f3a602e07cb907747be150ac9b42f6abe143632d56bbaad1",
        "behavior.rt-vlm.user-prompt-cap": "47c92fe04ac2f3bc4c92506f603b1a1ef733b2a4295e8253e7df2740a0d3e557",
        "behavior.rt-vlm.system-prompt-cap": "024f2b1120a0dbbfcb0fb28f1984d486e90cea67e38a653bbcb91f3b3d91397d",
        "behavior.rt-vlm.generate-captions-endpoint-rename": "c45f780b67fc4e3ad265ebedcce4a8ca792899a3247777a793ece11e8bb537c6",
    },
}


class RtVlmEvidenceError(RuntimeError):
    """Retained RT-VLM evidence is inconsistent."""


def _load(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise RtVlmEvidenceError(f"duplicate JSON key in {path.name}: {key}")
            value[key] = item
        return value

    value = json.loads(raw, object_pairs_hook=reject_duplicates)
    if not isinstance(value, dict):
        raise RtVlmEvidenceError(f"{path.name} is not a JSON object")
    return value, raw


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _privacy_walk(value: Any, path: str = "$") -> None:
    forbidden_keys = {
        "api_key",
        "authorization",
        "credential",
        "credentials",
        "request_id",
        "session_id",
        "access_token",
        "refresh_token",
        "sdp",
        "ice",
        "caption_content",
    }
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in forbidden_keys:
                raise RtVlmEvidenceError(f"forbidden retained field at {path}/{key}")
            _privacy_walk(item, f"{path}/{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _privacy_walk(item, f"{path}/{index}")
    elif isinstance(value, str):
        lowered = value.lower()
        if "nvapi-" in lowered or "bearer " in lowered:
            raise RtVlmEvidenceError(f"credential-like retained value at {path}")


def _verify_receipt(receipt: dict[str, Any]) -> None:
    if (
        receipt.get("status") != "passed"
        or receipt.get("failure") is not None
        or receipt.get("blockers") != []
        or receipt.get("capability_ids") != CAPABILITY_IDS
        or receipt.get("contract_sha256") != EXPECTED["contract"]
        or receipt.get("semantic_action_count") != 8
        or receipt.get("http_request_count") != 22
        or receipt.get("network_scope") != "loopback_only"
        or receipt.get("warehouse_sample_bundle") is not False
        or receipt.get("forbidden_actions_observed") != []
        or receipt.get("writes_or_lifecycle_actions") is not True
        or not 0 < receipt.get("duration_seconds", 0) <= 180
    ):
        raise RtVlmEvidenceError("runtime receipt is not passing and bounded")

    identity = receipt["runtime_identity"]
    if (
        identity["image_id"]
        != "sha256:5403e0c8fa8b149e7ad15ab1b063b78d610e7a50297dba6ca550ac5cc5ef9504"
        or identity["architecture"] != "arm64"
        or identity["loopback_binding"] != "127.0.0.1:8018->8000/tcp"
        or identity["model_selector"] != "cosmos-reason3"
        or identity["model_artifact_id"]
        != "ngc:nim/nvidia/cosmos3-nano-reasoner:bf16-final"
        or identity["served_model_id"]
        != "nim_nvidia_cosmos3-nano-reasoner_bf16-final"
        or identity["generation_token_limit"] != 16384
        or identity["user_prompt_limit"] != 10240
        or identity["system_prompt_limit_source"] != "schema_default"
        or identity["health"] != "healthy"
        or identity["restart_count"] != 0
        or identity["oom_killed"] is not False
    ):
        raise RtVlmEvidenceError("runtime/model identity drifted")
    if receipt["model_contract"] != {
        "api_type": "internal",
        "audio_support": False,
        "http_status": 200,
        "model_count": 1,
        "model_object": "model",
        "owned_by": "custom",
        "served_model_id": "nim_nvidia_cosmos3-nano-reasoner_bf16-final",
    }:
        raise RtVlmEvidenceError("served model response drifted")

    api = receipt["api_contract"]
    if (
        api["operation_count"] != 28
        or api["path_count"] != 26
        or api["current_path_present"] is not True
        or api["current_method_present"] != "POST"
        or api["removed_legacy_path_absent"] is not True
        or api["authorization_dependency_declared"] is not False
        or api["generation_token_maximum"] != 16384
        or api["user_prompt_maximum"] != 10240
        or api["system_prompt_maximum"] != 10240
    ):
        raise RtVlmEvidenceError("live OpenAPI contract drifted")

    expected_boundaries = {
        "blank_prompt": (422, "rejected", "InvalidParameters"),
        "generation_at_limit": (400, "accepted", "BadParameter"),
        "generation_above_limit": (422, "rejected", "InvalidParameters"),
        "user_prompt_at_limit": (400, "accepted", "BadParameter"),
        "user_prompt_above_limit": (422, "rejected", "InvalidParameters"),
        "system_prompt_at_limit": (400, "accepted", "BadParameter"),
        "system_prompt_above_limit": (422, "rejected", "InvalidParameters"),
    }
    if set(receipt["boundaries"]) != set(expected_boundaries):
        raise RtVlmEvidenceError("boundary vector set drifted")
    for name, (status, outcome, code) in expected_boundaries.items():
        row = receipt["boundaries"][name]
        if (
            row["http_status"] != status
            or row["schema_outcome"] != outcome
            or row["error_code"] != code
            or len(row["response_sha256"]) != 64
            or row["response_bytes"] <= 0
        ):
            raise RtVlmEvidenceError(f"boundary result drifted: {name}")

    sse = receipt["sse"]
    if (
        sse["http_status"] != 200
        or sse["content_type"] != "text/event-stream"
        or sse["positive_vector_id"] != "rt-vlm-sse-one-owned-clip"
        or sse["caption_event_count"] != 5
        or sse["caption_chunk_count"] != 5
        or sse["data_event_count"] != 7
        or sse["usage_event_count"] != 1
        or sse["terminal_event"] != "[DONE]"
        or not all(
            sse[key]
            for key in (
                "request_id_well_formed",
                "request_identity_stable",
                "response_header_identity_match",
                "model_identity_stable",
                "created_timestamp_stable",
                "chunk_ids_nondecreasing",
                "usage_after_captions",
                "terminal_event_last",
            )
        )
        or [row["chunk_id"] for row in sse["caption_chunks"]] != [0, 1, 2, 3, 4]
        or not all(row["content_nonblank"] for row in sse["caption_chunks"])
        or sse["usage_numbers"].get("total_chunks_processed") != 5
    ):
        raise RtVlmEvidenceError("SSE runtime semantics drifted")

    cleanup = receipt["cleanup"]
    if (
        cleanup["failures"] != []
        or cleanup["delete_http_status"] != 200
        or cleanup["owned_asset_absent"] is not True
        or cleanup["asset_statistics_exact"] is not True
        or cleanup["asset_count_after"] != 0
        or cleanup["asset_count_with_storage_after"] != 0
        or cleanup["readiness_after"] is not True
        or cleanup["model_identity_after"] is not True
        or cleanup["container_identity_exact"] is not True
    ):
        raise RtVlmEvidenceError("owned cleanup/restoration drifted")
    _privacy_walk(receipt)


def verify() -> dict[str, Any]:
    contract, contract_raw = _load(HERE / "contract.json")
    receipt, receipt_raw = _load(HERE / "runtime-receipt.json")
    if _sha(contract_raw) != EXPECTED["contract"]:
        raise RtVlmEvidenceError("fixture contract digest drifted")
    if _sha(receipt_raw) != EXPECTED["receipt"]:
        raise RtVlmEvidenceError("runtime receipt digest drifted")
    if contract.get("capability_ids") != CAPABILITY_IDS:
        raise RtVlmEvidenceError("contract capability set/order drifted")
    _verify_receipt(receipt)

    ledger, _ = _load(PARITY / "official-capabilities.json")
    plan, _ = _load(PARITY / "capability-oracles.json")
    capabilities = {row["id"]: row for row in ledger["capabilities"]}
    oracles = {row["capability_id"]: row for row in plan["oracles"]}
    rebuilt = build_official_evidence.build()
    for capability_id, path in build_official_evidence.OUTPUTS.items():
        evidence, evidence_raw = _load(path)
        if evidence != rebuilt[capability_id]:
            raise RtVlmEvidenceError(
                f"retained projection is not reproducible: {capability_id}"
            )
        evidence_sha = _sha(evidence_raw)
        if evidence_sha != EXPECTED["evidence"][capability_id]:
            raise RtVlmEvidenceError(f"official evidence digest drifted: {capability_id}")
        oracle = oracles[capability_id]
        oracle_sha = capability_oracles.canonical_oracle_sha256(oracle)
        if (
            oracle_sha != EXPECTED["oracle"][capability_id]
            or evidence.get("oracle_sha256") != oracle_sha
        ):
            raise RtVlmEvidenceError(f"capability oracle digest drifted: {capability_id}")
        expected_path = str(path.relative_to(REPO))
        capability = capabilities[capability_id]
        if (
            capability.get("runtime_state") != "passed_current"
            or capability.get("thor_state") != "wired"
            or capability.get("runtime_evidence")
            != [{"path": expected_path, "sha256": evidence_sha}]
            or oracle["acceptance_readiness"]
            != {"classification": "executor_ready", "blockers": []}
            or oracle["fixture"]["materialization"]
            != {
                "generator": capability_oracles.RT_VLM_SSE_RUNTIME_EXECUTOR,
                "path": capability_oracles.RT_VLM_SSE_RUNTIME_FIXTURE["path"],
                "sha256": EXPECTED["contract"],
            }
            or oracle["execution_bounds"]["max_requests"] != 22
            or oracle["execution_bounds"]["max_actions"] != 8
            or oracle["cleanup"]["targets"]
            != capability_oracles.RT_VLM_SSE_RUNTIME_NAMESPACES
        ):
            raise RtVlmEvidenceError(f"official runtime binding drifted: {capability_id}")
        _privacy_walk(evidence)

    counts = verify_official_capabilities.validate(repo_root=REPO)
    return {
        "status": "passed",
        "capability_ids": CAPABILITY_IDS,
        "capability_count": len(CAPABILITY_IDS),
        "official_capability_count": counts["capabilities"],
        "receipt_sha256": EXPECTED["receipt"],
        "evidence_sha256": EXPECTED["evidence"],
        "oracle_sha256": EXPECTED["oracle"],
    }


def main() -> int:
    try:
        result = verify()
    except (
        OSError,
        KeyError,
        StopIteration,
        json.JSONDecodeError,
        RtVlmEvidenceError,
        build_official_evidence.EvidenceProjectionError,
        verify_official_capabilities.CapabilityContractError,
    ) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
