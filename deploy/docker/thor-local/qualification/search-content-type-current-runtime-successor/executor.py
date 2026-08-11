#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Bounded current-runtime proof for the Search upload Content-Type contract."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from typing import Any
from urllib.parse import quote
from urllib.parse import urlsplit
import uuid


ROOT = Path(__file__).resolve().parents[5]
HERE = Path(__file__).resolve().parent
CONTRACT_PATH = HERE / "contract.json"


class QualificationError(RuntimeError):
    """A retained, non-sensitive qualification failure."""

    ALLOWED = {
        "authorization_required",
        "cleanup_failed",
        "configuration_error",
        "fixture_error",
        "http_error",
        "oracle_failed",
        "runtime_identity_error",
        "source_lock_error",
    }

    def __init__(self, code: str):
        if code not in self.ALLOWED:
            code = "oracle_failed"
        self.code = code
        super().__init__(code)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _progress(label: str) -> None:
    print(f"[search-content-type] {label}", file=sys.stderr, flush=True)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def _strict_json(raw: bytes) -> Any:
    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise QualificationError("http_error")
            result[key] = value
        return result

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError("http_error") from exc


def _load_json(path: Path) -> dict[str, Any]:
    value = _strict_json(path.read_bytes())
    if not isinstance(value, dict):
        raise QualificationError("configuration_error")
    return value


def _run(argv: list[str], *, timeout: int = 30, maximum: int = 65536) -> bytes:
    try:
        completed = subprocess.run(
            argv,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise QualificationError("runtime_identity_error") from exc
    if len(completed.stdout) > maximum:
        raise QualificationError("runtime_identity_error")
    return completed.stdout


class LocalHttp:
    """Exact loopback HTTP client with bounded observations and mutations."""

    def __init__(self, contract: dict[str, Any], deadline: float):
        self.origins = contract["targets"]
        self.deadline = deadline
        self.max_requests = contract["bounds"]["max_http_requests"]
        self.max_mutations = contract["bounds"]["max_persistent_mutations"]
        self.max_response_bytes = contract["bounds"]["max_response_bytes"]
        self.requests = 0
        self.mutations = 0
        self.observations: list[dict[str, Any]] = []

    def call(
        self,
        *,
        operation: str,
        target: str,
        method: str,
        path: str,
        body: bytes | None = None,
        content_type: str | None = None,
        expected: set[int] = {200},
        mutation: bool = False,
        timeout: float = 180.0,
    ) -> tuple[int, bytes]:
        if target not in self.origins or method not in {"DELETE", "GET", "POST", "PUT"}:
            raise QualificationError("configuration_error")
        if not path.startswith("/") or "#" in path:
            raise QualificationError("configuration_error")
        parsed = urlsplit(self.origins[target])
        if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.path:
            raise QualificationError("configuration_error")
        if self.requests >= self.max_requests:
            raise QualificationError("http_error")
        if mutation and self.mutations >= self.max_mutations:
            raise QualificationError("http_error")
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise QualificationError("http_error")
        headers: dict[str, str] = {"Accept": "application/json"}
        if content_type is not None:
            headers["Content-Type"] = content_type
        try:
            connection = http.client.HTTPConnection(
                parsed.hostname,
                parsed.port,
                timeout=max(0.1, min(timeout, remaining)),
            )
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            raw = response.read(self.max_response_bytes + 1)
            status = response.status
            connection.close()
        except (OSError, TimeoutError, http.client.HTTPException) as exc:
            raise QualificationError("http_error") from exc
        if len(raw) > self.max_response_bytes or status not in expected:
            raise QualificationError("http_error")
        self.requests += 1
        if mutation:
            self.mutations += 1
        self.observations.append(
            {
                "sequence": self.requests,
                "operation": operation,
                "target": target,
                "method": method,
                "path_sha256": _sha(path.encode()),
                "request_bytes": 0 if body is None else len(body),
                "request_sha256": None if body is None else _sha(body),
                "status": status,
                "response_bytes": len(raw),
                "response_sha256": _sha(raw),
                "mutation": mutation,
            }
        )
        return status, raw

    def json(self, **kwargs: Any) -> tuple[int, Any]:
        status, raw = self.call(**kwargs)
        return status, _strict_json(raw)


def _validate_source_locks(contract: dict[str, Any]) -> dict[str, str]:
    observed: dict[str, str] = {}
    for lock in contract["source_locks"]:
        path = ROOT / lock["path"]
        if not path.is_file():
            raise QualificationError("source_lock_error")
        digest = _sha(path.read_bytes())
        if digest != lock["sha256"]:
            raise QualificationError("source_lock_error")
        observed[lock["path"]] = digest
    return observed


def _runtime_snapshot(contract: dict[str, Any]) -> dict[str, Any]:
    names = contract["runtime"]["containers"]
    raw = _run(["docker", "inspect", *names], timeout=20, maximum=2_000_000)
    value = _strict_json(raw)
    if not isinstance(value, list) or len(value) != len(names):
        raise QualificationError("runtime_identity_error")
    rows: list[dict[str, Any]] = []
    for item in value:
        try:
            name = item["Name"].lstrip("/")
            image = item["Config"]["Image"]
            identifier = item["Id"]
            restart_count = item["RestartCount"]
            running = item["State"]["Running"]
            health = item["State"].get("Health", {}).get("Status")
        except (KeyError, TypeError, AttributeError) as exc:
            raise QualificationError("runtime_identity_error") from exc
        if name not in names or running is not True or health != "healthy":
            raise QualificationError("runtime_identity_error")
        rows.append(
            {
                "name": name,
                "image": image,
                "container_id_sha256": _sha(identifier.encode()),
                "restart_count": restart_count,
                "health": health,
            }
        )
    rows.sort(key=lambda row: row["name"])
    expected_images = contract["runtime"]["images"]
    if {row["name"]: row["image"] for row in rows} != expected_images:
        raise QualificationError("runtime_identity_error")
    return {"containers": rows}


def _fixture(path: Path, media_type: str) -> dict[str, Any]:
    common = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-fflags",
        "+bitexact",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=160x120:rate=10",
        "-t",
        "2",
        "-map_metadata",
        "-1",
        "-c:v",
        "libx264",
        "-profile:v",
        "baseline",
        "-pix_fmt",
        "yuv420p",
        "-bf",
        "0",
        "-g",
        "20",
        "-flags:v",
        "+bitexact",
    ]
    if media_type == "video/mp4":
        common.extend(["-movflags", "+faststart"])
    common.append(str(path))
    _run(common, timeout=30, maximum=100_000)
    probe = _strict_json(
        _run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=codec_name,codec_type,width,height,has_b_frames,r_frame_rate",
                "-of",
                "json",
                str(path),
            ],
            timeout=10,
            maximum=64_000,
        )
    )
    streams = probe.get("streams") if isinstance(probe, dict) else None
    if not isinstance(streams, list) or len(streams) != 1:
        raise QualificationError("fixture_error")
    stream = streams[0]
    if (
        stream.get("codec_type") != "video"
        or stream.get("codec_name") != "h264"
        or stream.get("width") != 160
        or stream.get("height") != 120
        or stream.get("has_b_frames") != 0
        or stream.get("r_frame_rate") != "10/1"
    ):
        raise QualificationError("fixture_error")
    raw = path.read_bytes()
    if not 1_000 <= len(raw) <= 1_000_000:
        raise QualificationError("fixture_error")
    return {
        "media_type": media_type,
        "bytes": len(raw),
        "sha256": _sha(raw),
        "codec": "h264",
        "width": 160,
        "height": 120,
        "frames_per_second": 10,
        "duration_seconds": 2,
    }


def _sensor_identities(value: Any) -> list[dict[str, str | None]]:
    if not isinstance(value, list):
        raise QualificationError("oracle_failed")
    rows: list[dict[str, str | None]] = []
    for item in value:
        if not isinstance(item, dict):
            raise QualificationError("oracle_failed")
        sensor_id = item.get("sensorId")
        name = item.get("name")
        kind = item.get("type")
        if (
            not isinstance(sensor_id, str)
            or not isinstance(name, str)
            or (kind is not None and not isinstance(kind, str))
        ):
            raise QualificationError("oracle_failed")
        rows.append(
            {
                "sensor_id_sha256": _sha(sensor_id.encode()),
                "name_sha256": _sha(name.encode()),
                "type": kind,
            }
        )
    return sorted(rows, key=_canonical)


def _es_count(
    client: LocalHttp, operation: str, index: str, field: str, value: str
) -> int:
    body = _canonical({"query": {"term": {field: value}}})
    status, result = client.json(
        operation=operation,
        target="elasticsearch",
        method="POST",
        path=f"/{index}/_count",
        body=body,
        content_type="application/json",
        expected={200, 404},
    )
    if status == 404:
        return 0
    count = result.get("count") if isinstance(result, dict) else None
    if type(count) is not int or count < 0:
        raise QualificationError("oracle_failed")
    return count


def _owned_sensor_rows(
    client: LocalHttp, names: set[str]
) -> tuple[Any, list[dict[str, Any]]]:
    _, sensors = client.json(
        operation="sensor_inventory",
        target="vios",
        method="GET",
        path="/vst/api/v1/sensor/list",
    )
    if not isinstance(sensors, list):
        raise QualificationError("oracle_failed")
    return sensors, [
        row for row in sensors if isinstance(row, dict) and row.get("name") in names
    ]


def _delete_owned(
    client: LocalHttp,
    names: set[str],
    owned_ids: set[str],
    deleted_ids: set[str],
) -> list[dict[str, Any]]:
    sensors, rows = _owned_sensor_rows(client, names)
    del sensors
    for row in rows:
        value = row.get("sensorId")
        if isinstance(value, str) and value:
            owned_ids.add(value)
    cleanup: list[dict[str, Any]] = []
    for sensor_id in sorted(owned_ids - deleted_ids):
        status, result = client.json(
            operation="delete_owned_video",
            target="agent",
            method="DELETE",
            path=f"/api/v1/videos/{quote(sensor_id, safe='')}",
            expected={200},
            mutation=True,
            timeout=180,
        )
        state = result.get("status") if isinstance(result, dict) else None
        if state != "success":
            raise QualificationError("cleanup_failed")
        deleted_ids.add(sensor_id)
        cleanup.append(
            {
                "sensor_id_sha256": _sha(sensor_id.encode()),
                "status": status,
                "result": state,
            }
        )
    return cleanup


def _assert_namespace_absent(
    client: LocalHttp, names: set[str], owned_ids: set[str]
) -> None:
    for attempt in range(20):
        _, rows = _owned_sensor_rows(client, names)
        counts = []
        for sensor_id in sorted(owned_ids):
            counts.append(
                _es_count(
                    client,
                    f"cleanup_embed_{attempt}",
                    "mdx-embed-filtered-2025-01-01",
                    "sensor.id.keyword",
                    sensor_id,
                )
            )
        for name in sorted(names):
            counts.append(
                _es_count(
                    client,
                    f"cleanup_behavior_{attempt}",
                    "mdx-behavior-2025-01-01",
                    "sensor.id.keyword",
                    name,
                )
            )
            counts.append(
                _es_count(
                    client,
                    f"cleanup_raw_{attempt}",
                    "mdx-raw-2025-01-01",
                    "sensorId.keyword",
                    name,
                )
            )
        if not rows and all(count == 0 for count in counts):
            return
        time.sleep(0.5)
    raise QualificationError("cleanup_failed")


def _execute(contract: dict[str, Any], acknowledgement: str) -> dict[str, Any]:
    if acknowledgement != contract["authorization"]["acknowledgement"]:
        raise QualificationError("authorization_required")
    commit = (
        _run(["git", "rev-parse", "HEAD"], timeout=10, maximum=256).decode().strip()
    )
    if commit != contract["target_commit"] or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise QualificationError("configuration_error")
    source_hashes = _validate_source_locks(contract)
    pre_runtime = _runtime_snapshot(contract)
    _progress("admission-passed")
    deadline = time.monotonic() + contract["bounds"]["max_duration_seconds"]
    client = LocalHttp(contract, deadline)
    token = uuid.uuid4().hex[:12]
    prefix = f"vss-oracle-search-content-type-{token}"
    cases = [
        ("video/mp4", "mp4", f"{prefix}-mp4"),
        ("video/x-matroska", "mkv", f"{prefix}-mkv"),
    ]
    names = {name for _, _, name in cases}
    owned_ids: set[str] = set()
    deleted_ids: set[str] = set()
    cleanup: list[dict[str, Any]] = []
    positives: list[dict[str, Any]] = []
    failure: QualificationError | None = None

    _, pre_sensors = client.json(
        operation="pre_sensor_inventory",
        target="vios",
        method="GET",
        path="/vst/api/v1/sensor/list",
    )
    _, pre_files = client.json(
        operation="pre_file_inventory",
        target="vios",
        method="GET",
        path="/vst/api/v1/storage/file/list",
    )
    if any(row.get("name") in names for row in pre_sensors if isinstance(row, dict)):
        raise QualificationError("fixture_error")
    _progress("prestate-passed")

    try:
        negative_body = b"content-type-boundary"
        _, missing = client.json(
            operation="missing_content_type",
            target="agent",
            method="PUT",
            path=f"/api/v1/videos-for-search/{prefix}-missing.mp4",
            body=negative_body,
            expected={400},
        )
        _, unsupported = client.json(
            operation="unsupported_content_type",
            target="agent",
            method="PUT",
            path=f"/api/v1/videos-for-search/{prefix}-unsupported.avi",
            body=negative_body,
            content_type="application/octet-stream",
            expected={400},
        )
        if "Content-Type header is required" not in missing.get("detail", ""):
            raise QualificationError("oracle_failed")
        if "Unsupported video format" not in unsupported.get("detail", ""):
            raise QualificationError("oracle_failed")
        _progress("negative-cases-passed")

        with tempfile.TemporaryDirectory(
            prefix="vss-search-content-type-"
        ) as directory:
            for media_type, extension, name in cases:
                fixture_path = Path(directory) / f"{name}.{extension}"
                fixture = _fixture(fixture_path, media_type)
                _progress(f"fixture-{extension}-passed")
                raw = fixture_path.read_bytes()
                status, result = client.json(
                    operation=f"positive_{extension}_upload",
                    target="agent",
                    method="PUT",
                    path=f"/api/v1/videos-for-search/{name}.{extension}",
                    body=raw,
                    content_type=media_type,
                    expected={200},
                    mutation=True,
                    timeout=300,
                )
                if not isinstance(result, dict):
                    raise QualificationError("oracle_failed")
                sensor_id = result.get("sensor_id")
                chunks = result.get("chunks_processed")
                if (
                    not isinstance(sensor_id, str)
                    or not sensor_id
                    or type(chunks) is not int
                    or chunks < 1
                ):
                    raise QualificationError("oracle_failed")
                owned_ids.add(sensor_id)
                _progress(f"upload-{extension}-passed")
                _, sensors = client.json(
                    operation=f"positive_{extension}_sensor",
                    target="vios",
                    method="GET",
                    path="/vst/api/v1/sensor/list",
                )
                matching = [
                    row
                    for row in sensors
                    if isinstance(row, dict)
                    and row.get("name") == name
                    and row.get("sensorId") == sensor_id
                ]
                if len(matching) != 1:
                    raise QualificationError("oracle_failed")
                _progress(f"sensor-{extension}-passed")
                embed_count = 0
                for retry in range(10):
                    embed_count = _es_count(
                        client,
                        f"positive_{extension}_embed_{retry}",
                        "mdx-embed-filtered-2025-01-01",
                        "sensor.id.keyword",
                        sensor_id,
                    )
                    if embed_count >= 1:
                        break
                    time.sleep(0.25)
                if embed_count < 1:
                    raise QualificationError("oracle_failed")
                _progress(f"embedding-{extension}-passed")
                positives.append(
                    {
                        **fixture,
                        "extension": extension,
                        "status": status,
                        "chunks_processed": chunks,
                        "embed_document_count": embed_count,
                        "sensor_name_sha256": _sha(name.encode()),
                        "sensor_id_sha256": _sha(sensor_id.encode()),
                    }
                )
                cleanup.extend(_delete_owned(client, names, owned_ids, deleted_ids))
                _assert_namespace_absent(client, names, owned_ids)
                _progress(f"cleanup-{extension}-passed")
    except QualificationError as exc:
        failure = exc
    finally:
        try:
            cleanup.extend(_delete_owned(client, names, owned_ids, deleted_ids))
            _assert_namespace_absent(client, names, owned_ids)
        except QualificationError:
            failure = QualificationError("cleanup_failed")

    _, post_sensors = client.json(
        operation="post_sensor_inventory",
        target="vios",
        method="GET",
        path="/vst/api/v1/sensor/list",
    )
    _, post_files = client.json(
        operation="post_file_inventory",
        target="vios",
        method="GET",
        path="/vst/api/v1/storage/file/list",
    )
    post_runtime = _runtime_snapshot(contract)
    exact_inventory_restored = _sensor_identities(pre_sensors) == _sensor_identities(
        post_sensors
    ) and _canonical(pre_files) == _canonical(post_files)
    if not exact_inventory_restored or pre_runtime != post_runtime:
        failure = QualificationError("cleanup_failed")
    _progress("poststate-collected")
    if failure is not None:
        raise failure
    if [row["media_type"] for row in positives] != ["video/mp4", "video/x-matroska"]:
        raise QualificationError("oracle_failed")

    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "capability_id": contract["capability_id"],
        "oracle_id": contract["oracle_id"],
        "target_commit": commit,
        "contract_sha256": _sha(CONTRACT_PATH.read_bytes()),
        "result": "passed",
        "promotion_eligible": True,
        "warehouse_sample_bundle": "excluded",
        "source_hashes": source_hashes,
        "runtime": {"pre": pre_runtime, "post": post_runtime, "unchanged": True},
        "fixture": {
            "generator": "ffmpeg-lavfi-testsrc2",
            "namespace_sha256": _sha(prefix.encode()),
            "cases": positives,
        },
        "negative_cases": [
            {"case": "missing", "status": 400},
            {
                "case": "unsupported",
                "media_type": "application/octet-stream",
                "status": 400,
            },
        ],
        "observations": client.observations,
        "cleanup": {
            "exact_owned_resources_only": True,
            "delete_results": cleanup,
            "namespace_absent": True,
            "exact_sensor_and_file_inventory_restored": True,
            "service_lifecycle_mutations": 0,
        },
        "counts": {
            "http_requests": client.requests,
            "persistent_mutations": client.mutations,
            "positive_cases": len(positives),
            "negative_cases": 2,
        },
        "tooling": {
            "ffmpeg_version_sha256": _sha(
                _run(["ffmpeg", "-version"], maximum=100_000).splitlines()[0]
            ),
            "ffprobe_version_sha256": _sha(
                _run(["ffprobe", "-version"], maximum=100_000).splitlines()[0]
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ack", required=True)
    parser.add_argument("--output", type=Path, default=HERE / "runtime-receipt.json")
    args = parser.parse_args()
    contract = _load_json(CONTRACT_PATH)
    try:
        receipt = _execute(contract, args.ack)
    except QualificationError as exc:
        receipt = {
            "schema_version": 1,
            "package_id": contract.get("package_id"),
            "capability_id": contract.get("capability_id"),
            "oracle_id": contract.get("oracle_id"),
            "result": "failed",
            "failure": exc.code,
            "promotion_eligible": False,
            "warehouse_sample_bundle": "excluded",
        }
        args.output.write_bytes(_canonical(receipt) + b"\n")
        print(json.dumps(receipt, sort_keys=True))
        return 1
    args.output.write_bytes(_canonical(receipt) + b"\n")
    print(
        json.dumps(
            {
                "package_id": receipt["package_id"],
                "result": receipt["result"],
                "http_requests": receipt["counts"]["http_requests"],
                "persistent_mutations": receipt["counts"]["persistent_mutations"],
                "promotion_eligible": receipt["promotion_eligible"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
