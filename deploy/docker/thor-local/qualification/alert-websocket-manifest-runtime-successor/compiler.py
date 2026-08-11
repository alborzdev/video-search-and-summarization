#!/usr/bin/env python3
"""Bind one isolated Alert Bridge WebSocket run to two exact VSS rows."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
CONTRACT_PATH = HERE / "contract.json"
SCHEMA_PATH = HERE / "receipt.schema.json"
RECEIPT_PATH = HERE / "runtime-receipt.json"
CAPABILITY_IDS = ["protocol.alert.websocket", "manifest-entry.realtime-alerts.05-websocket-delivery"]
OFFICIAL_INDICES = [53, 333]


class EvidenceError(RuntimeError):
    pass


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise EvidenceError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda token: (_ for _ in ()).throw(EvidenceError(f"non-finite JSON: {token}")),
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"cannot load strict JSON: {path.name}") from exc
    if not isinstance(value, dict):
        raise EvidenceError(f"expected JSON object: {path.name}")
    return value


def _sources(contract: dict[str, Any]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for item in contract["source_locks"]:
        path = REPO / item["path"]
        if item["path"] in result or not path.is_file() or path.is_symlink() or _sha(path) != item["sha256"]:
            raise EvidenceError(f"source lock drifted: {item['path']}")
        result[item["path"]] = path
    return result


def build_receipt() -> dict[str, Any]:
    contract = _load(CONTRACT_PATH)
    if contract.get("capability_ids") != CAPABILITY_IDS or contract.get("official_indices") != OFFICIAL_INDICES:
        raise EvidenceError("contract capability binding differs")
    sources = _sources(contract)
    raw_path = sources["deploy/docker/thor-local/qualification/alert-websocket-runtime/runtime-receipt.json"]
    wrapper_path = sources["deploy/docker/thor-local/qualification/alert-websocket-runtime/official-runtime-evidence.json"]
    fixture_path = sources["deploy/docker/thor-local/qualification/alert-websocket-runtime/contract.json"]
    raw = _load(raw_path)
    wrapper = _load(wrapper_path)
    positive = raw.get("runtime", {}).get("positive", {})
    negative = raw.get("runtime", {}).get("negative", {})
    connection = raw.get("runtime", {}).get("connection_cleanup", {})
    cleanup = raw.get("cleanup", {})
    if (
        raw.get("status") != "passed"
        or raw.get("contract_sha256") != _sha(fixture_path)
        or raw.get("target_release") != "VSS 3.2.1"
        or raw.get("network_scope") != "loopback_only"
        or raw.get("semantic_action_count") != 2
        or raw.get("forbidden_actions_observed") != []
        or raw.get("warehouse_sample_bundle") is not False
        or raw.get("runtime_identity", {}).get("architecture") != "arm64"
        or raw.get("runtime_identity", {}).get("main_service_running") is not True
        or raw.get("runtime_identity", {}).get("redis_health") != "healthy"
        or positive != {
            "alert_frame_count": 1,
            "alert_type": "original",
            "frames": ["pong", "alert", "status"],
            "handshake": "HTTP Upgrade to WebSocket",
            "message_id_match": True,
            "pending_after_callback": 0,
            "pong_observed": True,
            "redis_fields_preserved": True,
            "status_connections": 1,
            "vector_id": "alert-ws-one-owned-entry",
        }
        or negative.get("frame") != "non-json"
        or negative.get("application_response_observed") is not False
        or negative.get("socket_remained_open") is not True
        or connection != {"active_connections_after_close": 0, "connection_removed": True}
    ):
        raise EvidenceError("alert WebSocket runtime semantics differ")
    required_cleanup = (
        "isolated_container_absent", "isolated_listener_absent", "normal_service_state_exact",
        "owned_enhanced_stream_absent", "owned_input_stream_absent", "redis_nonowned_key_set_exact",
    )
    if (
        cleanup.get("failures") != []
        or not all(cleanup.get(key) is True for key in required_cleanup)
        or cleanup.get("redis_health_after") != "healthy"
        or wrapper.get("result") != "passed_current"
        or wrapper.get("capability_id") != "protocol.alert.websocket"
        or wrapper.get("observations", [{}])[0].get("value", {}).get("receipt_sha256") != _sha(raw_path)
    ):
        raise EvidenceError("alert WebSocket cleanup or wrapper differs")
    receipt = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "capability_ids": CAPABILITY_IDS,
        "official_indices": OFFICIAL_INDICES,
        "status": "passed",
        "contract_sha256": _sha(CONTRACT_PATH),
        "source_identity": {
            "raw_receipt_sha256": _sha(raw_path),
            "official_wrapper_sha256": _sha(wrapper_path),
            "fixture_contract_sha256": _sha(fixture_path),
        },
        "runtime": {
            "product_version": "3.2.1",
            "captured_at": raw["captured_at"],
            "architecture": raw["runtime_identity"]["architecture"],
            "network_scope": raw["network_scope"],
            "main_service_running": raw["runtime_identity"]["main_service_running"],
            "redis_healthy": raw["runtime_identity"]["redis_health"] == "healthy",
        },
        "delivery": {
            "handshake": positive["handshake"], "frames": positive["frames"],
            "pong_observed": positive["pong_observed"], "alert_frame_count": positive["alert_frame_count"],
            "status_connections": positive["status_connections"], "redis_fields_preserved": positive["redis_fields_preserved"],
            "message_id_match": positive["message_id_match"], "pending_after_callback": positive["pending_after_callback"],
        },
        "negative": {
            "frame": negative["frame"], "application_response_observed": negative["application_response_observed"],
            "socket_remained_open": negative["socket_remained_open"],
        },
        "cleanup": {
            "connection_removed": connection["connection_removed"],
            "active_connections_after_close": connection["active_connections_after_close"],
            "isolated_container_absent": cleanup["isolated_container_absent"],
            "isolated_listener_absent": cleanup["isolated_listener_absent"],
            "owned_streams_absent": cleanup["owned_input_stream_absent"] and cleanup["owned_enhanced_stream_absent"],
            "redis_nonowned_key_set_exact": cleanup["redis_nonowned_key_set_exact"],
            "normal_service_state_exact": cleanup["normal_service_state_exact"],
            "redis_healthy_after": cleanup["redis_health_after"] == "healthy",
        },
        "policy": contract["policy"],
    }
    schema = _load(SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    errors = sorted(Draft202012Validator(schema).iter_errors(receipt), key=lambda error: list(error.path))
    if errors:
        raise EvidenceError(f"receipt schema violation: {errors[0].message}")
    return receipt


def _write(value: dict[str, Any]) -> None:
    content = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=HERE, delete=False) as stream:
            temporary = stream.name
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, RECEIPT_PATH)
        temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "write", "check"))
    args = parser.parse_args()
    try:
        value = build_receipt()
        if args.mode == "plan":
            print(json.dumps({"status": "ready", "official_indices": OFFICIAL_INDICES, "writes_or_lifecycle_actions": False}, sort_keys=True))
        elif args.mode == "write":
            _write(value)
            print(json.dumps({"status": "passed", "receipt_sha256": _sha(RECEIPT_PATH)}, sort_keys=True))
        elif not RECEIPT_PATH.is_file() or RECEIPT_PATH.read_bytes() != (json.dumps(value, indent=2, sort_keys=True) + "\n").encode():
            raise EvidenceError("checked receipt drifted")
        return 0
    except (EvidenceError, OSError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
