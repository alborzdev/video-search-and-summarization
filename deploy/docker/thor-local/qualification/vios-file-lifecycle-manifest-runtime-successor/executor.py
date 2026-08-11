#!/usr/bin/env python3
"""Bind a real namespaced VIOS lifecycle run to three exact manifest rows."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
CONTRACT_PATH = HERE / "contract.json"
SCHEMA_PATH = HERE / "receipt.schema.json"
RECEIPT_PATH = HERE / "runtime-receipt.json"
BASE_EXECUTOR_PATH = REPO / "deploy/docker/thor-local/qualification/vios-file-lifecycle-runtime/execute.py"
ACK = "I_ACK_NAMESPACED_VIOS_UPLOAD_CLIP_SNAPSHOT_AND_EXACT_CLEANUP"
CAPABILITY_IDS = [
    "manifest-entry.vios-core.01-file-upload-and-registration",
    "manifest-entry.vios-core.04-clip-and-raw-full-file-download",
    "manifest-entry.vios-core.05-snapshots",
]
OFFICIAL_INDICES = [412, 415, 416]
UUID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)


class QualificationError(RuntimeError):
    """The exact VIOS manifest runtime contract was not satisfied."""


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise QualificationError(f"duplicate JSON key: {key}")
            value[key] = item
        return value

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda token: (_ for _ in ()).throw(
                QualificationError(f"non-finite JSON number: {token}")
            ),
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise QualificationError(f"cannot load strict JSON: {path.name}") from exc
    if not isinstance(value, dict):
        raise QualificationError(f"expected JSON object: {path.name}")
    return value


def _source_locks(contract: dict[str, Any]) -> dict[str, str]:
    expected = {item["path"]: item["sha256"] for item in contract["source_locks"]}
    if len(expected) != len(contract["source_locks"]):
        raise QualificationError("duplicate source lock")
    for relative, digest in expected.items():
        path = REPO / relative
        if not path.is_file() or path.is_symlink() or _sha(path) != digest:
            raise QualificationError(f"source lock drifted: {relative}")
    return expected


def _base_module() -> Any:
    spec = importlib.util.spec_from_file_location("vios_file_lifecycle_base", BASE_EXECUTOR_PATH)
    if spec is None or spec.loader is None:
        raise QualificationError("cannot load the locked VIOS lifecycle executor")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _one_stream(probe: dict[str, Any], codec: str) -> dict[str, Any]:
    streams = probe.get("streams")
    matches = [
        item
        for item in streams if isinstance(item, dict) and item.get("codec_type") == "video"
    ] if isinstance(streams, list) else []
    if len(matches) != 1 or matches[0].get("codec_name") != codec:
        raise QualificationError(f"expected exactly one {codec} video stream")
    return matches[0]


def _receipt(raw: dict[str, Any], contract: dict[str, Any], locks: dict[str, str]) -> dict[str, Any]:
    if raw.get("status") != "passed" or raw.get("runtime_evidence") is not True:
        raise QualificationError("base VIOS transaction did not pass")
    bounds = raw.get("bounds", {})
    observations = raw.get("observations", {})
    cleanup = raw.get("cleanup", {})
    fixture = bounds.get("fixture", {})
    runtime_contract = contract["runtime_contract"]
    if (
        raw.get("target", {}).get("product_version") != "3.2.1"
        or bounds.get("loopback_only") is not True
        or bounds.get("agent_generate_called") is not False
        or bounds.get("warehouse_sample_bundle_used") is not False
        or bounds.get("rtsp_sensor_added") is not False
        or fixture.get("bytes") != runtime_contract["fixture_bytes"]
        or fixture.get("sha256") != runtime_contract["fixture_sha256"]
    ):
        raise QualificationError("VIOS target or fixture contract differs")
    readbacks = observations.get("registration_readbacks")
    if readbacks != runtime_contract["upload_registration_readbacks"]:
        raise QualificationError("VIOS registration readback set differs")
    if not all(
        isinstance(observations.get(key), str) and observations[key]
        for key in ("upload_file_id", "upload_sensor_id", "upload_stream_id")
    ):
        raise QualificationError("VIOS did not return stable registration identifiers")
    if observations["upload_sensor_id"] != observations["upload_stream_id"]:
        raise QualificationError("single-stream file sensor identity differs")

    clip = observations.get("clip_download", {})
    clip_stream = _one_stream(clip.get("probe", {}), "h264")
    try:
        clip_duration = float(clip["probe"]["format"]["duration"])
    except (KeyError, TypeError, ValueError) as exc:
        raise QualificationError("clip duration is unavailable") from exc
    if (
        abs(clip_duration - runtime_contract["clip"]["duration_seconds"]) > 0.001
        or clip.get("time_bounded") is not True
        or clip.get("distinct_from_full_file") is not True
        or clip.get("sha256") == observations.get("full_download_sha256")
    ):
        raise QualificationError("time-bounded clip contract differs")

    snapshot = observations.get("historical_snapshot", {})
    snapshot_stream = _one_stream(snapshot.get("probe", {}), "mjpeg")
    snapshot_mae = snapshot.get("source_rgb_mean_absolute_error")
    if (
        snapshot_stream.get("width") != runtime_contract["snapshot"]["width"]
        or snapshot_stream.get("height") != runtime_contract["snapshot"]["height"]
        or snapshot.get("timestamp_from_runtime_timeline") is not True
        or snapshot.get("visual_marker_correlated") is not True
        or not isinstance(snapshot_mae, (int, float))
        or snapshot_mae > runtime_contract["snapshot"]["maximum_source_rgb_mean_absolute_error"]
    ):
        raise QualificationError("historical snapshot contract differs")
    if not all(
        cleanup.get(key) is True
        for key in (
            "owned_file_absent",
            "owned_sensor_absent",
            "exact_file_list_restored",
            "exact_sensor_list_restored",
            "temporary_fixture_removed_by_context",
        )
    ) or cleanup.get("result") != "passed":
        raise QualificationError("VIOS exact cleanup contract differs")

    statuses = Counter(item.get("status") for item in raw.get("requests", []))
    receipt = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "capability_ids": CAPABILITY_IDS,
        "official_indices": OFFICIAL_INDICES,
        "status": "passed",
        "contract_sha256": _sha(CONTRACT_PATH),
        "source_identity": {
            "executor_sha256": locks[
                "deploy/docker/thor-local/qualification/vios-file-lifecycle-runtime/execute.py"
            ],
            "fixture_contract_sha256": locks[
                "deploy/docker/thor-local/qualification/vios-file-lifecycle-runtime/fixture-contract.json"
            ],
            "fixture_sha256": fixture["sha256"],
        },
        "runtime": {
            "captured_at": raw["captured_at"],
            "product_version": raw["target"]["product_version"],
            "endpoint_scope": "loopback-only",
            "request_count": len(raw["requests"]),
            "http_200_count": statuses[200],
            "http_409_count": statuses[409],
        },
        "upload_registration": {
            "bytes": observations["upload_response_bytes"],
            "stable_file_sensor_stream_identifiers": True,
            "duplicate_name_status": observations["duplicate_v2_upload_status"],
            "registration_readbacks": readbacks,
        },
        "downloads": {
            "full_file": {
                "bytes": observations["full_download_bytes"],
                "sha256": observations["full_download_sha256"],
                "byte_identical_to_upload": observations["full_download_sha256"] == fixture["sha256"],
            },
            "clip": {
                "bytes": clip["bytes"],
                "sha256": clip["sha256"],
                "codec": clip_stream["codec_name"],
                "duration_seconds": clip_duration,
                "time_bounded": True,
                "bounds_derived_from_runtime_timeline": True,
                "distinct_from_full_file": True,
            },
        },
        "snapshot": {
            "bytes": snapshot["bytes"],
            "sha256": snapshot["sha256"],
            "codec": snapshot_stream["codec_name"],
            "width": snapshot_stream["width"],
            "height": snapshot_stream["height"],
            "timestamp_from_runtime_timeline": True,
            "visual_marker_correlated": True,
            "source_rgb_mean_absolute_error": snapshot_mae,
        },
        "cleanup": {
            "result": cleanup["result"],
            "owned_file_absent": cleanup["owned_file_absent"],
            "owned_sensor_absent": cleanup["owned_sensor_absent"],
            "exact_file_list_restored": cleanup["exact_file_list_restored"],
            "exact_sensor_list_restored": cleanup["exact_sensor_list_restored"],
            "temporary_fixture_removed": cleanup["temporary_fixture_removed_by_context"],
        },
        "policy": contract["policy"],
    }
    schema = _load(SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    errors = sorted(Draft202012Validator(schema).iter_errors(receipt), key=lambda e: list(e.path))
    if errors:
        raise QualificationError(f"receipt schema violation: {errors[0].message}")
    if UUID_PATTERN.search(json.dumps(receipt, sort_keys=True)):
        raise QualificationError("sanitized receipt retained a raw UUID")
    return receipt


def _write(path: Path, value: dict[str, Any]) -> None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise QualificationError("unsafe receipt output")
    raw = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = stream.name
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "execute"))
    parser.add_argument("--ack")
    parser.add_argument("--write-receipt", action="store_true")
    args = parser.parse_args()
    try:
        contract = _load(CONTRACT_PATH)
        if contract.get("capability_ids") != CAPABILITY_IDS or contract.get("official_indices") != OFFICIAL_INDICES:
            raise QualificationError("contract capability binding differs")
        locks = _source_locks(contract)
        if args.mode == "plan":
            print(json.dumps({
                "status": "ready",
                "package_id": contract["package_id"],
                "official_indices": OFFICIAL_INDICES,
                "source_locks_verified": len(locks),
                "writes_or_lifecycle_actions": False,
            }, indent=2, sort_keys=True))
            return 0
        if args.ack != ACK:
            raise QualificationError(f"execute requires --ack {ACK}")
        raw = _base_module().execute()
        receipt = _receipt(raw, contract, locks)
        if args.write_receipt:
            _write(RECEIPT_PATH, receipt)
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return 0
    except (OSError, QualificationError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
