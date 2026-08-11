#!/usr/bin/env python3
"""Exercise the complete current 18-operation LVS REST surface on Thor."""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.client
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import time
from typing import Any
from urllib.parse import quote, urlsplit
import uuid


ROOT = Path(__file__).resolve().parents[5]
HERE = Path(__file__).resolve().parent
CONTRACT_PATH = HERE / "contract.json"
RECEIPT_PATH = HERE / "runtime-receipt.json"


def _progress(stage: str) -> None:
    print(f"[lvs-rest-qualification] {stage}", flush=True)


class QualificationError(RuntimeError):
    ALLOWED = {
        "authorization_required",
        "cleanup_failed",
        "configuration_error",
        "fixture_error",
        "graph_error",
        "oracle_failed",
        "request_budget_exhausted",
        "runtime_identity_error",
        "source_lock_error",
        "transport_error",
    }

    def __init__(self, code: str):
        self.code = code if code in self.ALLOWED else "oracle_failed"
        super().__init__(self.code)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def _strict(raw: bytes, code: str = "configuration_error") -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise QualificationError(code)
            result[key] = value
        return result

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError(code) from exc


def _contract() -> dict[str, Any]:
    value = _strict(CONTRACT_PATH.read_bytes())
    if not isinstance(value, dict):
        raise QualificationError("configuration_error")
    return value


def _run(
    argv: list[str],
    *,
    timeout: int = 30,
    maximum: int = 1_048_576,
    allowed_statuses: set[int] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    try:
        completed = subprocess.run(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            env={
                "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
            },
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise QualificationError("runtime_identity_error") from exc
    if len(completed.stdout) > maximum or len(completed.stderr) > maximum:
        raise QualificationError("runtime_identity_error")
    statuses = allowed_statuses if allowed_statuses is not None else {0}
    if completed.returncode not in statuses:
        raise QualificationError("runtime_identity_error")
    return completed


def _source_hashes(contract: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in contract["source_locks"]:
        path = ROOT / row["path"]
        if path.is_symlink() or not path.is_file():
            raise QualificationError("source_lock_error")
        digest = _sha(path.read_bytes())
        if digest != row["sha256"]:
            raise QualificationError("source_lock_error")
        result[row["path"]] = digest
    manifest = ROOT / contract["expected_manifest"]
    if _sha(manifest.read_bytes()) != contract["expected_manifest_sha256"]:
        raise QualificationError("source_lock_error")
    return result


def _runtime_snapshot(contract: dict[str, Any]) -> dict[str, Any]:
    observed: dict[str, Any] = {}
    for required in contract["runtime"]["services"]:
        completed = _run(
            ["docker", "inspect", required["container"]],
            timeout=20,
            maximum=2_000_000,
        )
        value = _strict(completed.stdout, "runtime_identity_error")
        if not isinstance(value, list) or len(value) != 1:
            raise QualificationError("runtime_identity_error")
        item = value[0]
        try:
            state = item["State"]
            row = {
                "container_id_sha256": _sha(item["Id"].encode()),
                "image": item["Config"]["Image"],
                "image_id_sha256": _sha(item["Image"].encode()),
                "started_at_sha256": _sha(state["StartedAt"].encode()),
                "restart_count": item["RestartCount"],
                "health": state["Health"]["Status"],
                "network_mode": item["HostConfig"]["NetworkMode"],
            }
        except (AttributeError, KeyError, TypeError) as exc:
            raise QualificationError("runtime_identity_error") from exc
        if (
            row["image"] != required["image"]
            or row["health"] != required["health"]
            or row["network_mode"] != required["network_mode"]
            or row["restart_count"] != 0
        ):
            raise QualificationError("runtime_identity_error")
        observed[required["container"]] = row
    return observed


class Transport:
    def __init__(self, contract: dict[str, Any], deadline: float):
        self.contract = contract
        self.deadline = deadline
        self.requests = 0
        self.actions = 0
        self.maximum = contract["bounds"]["max_response_bytes"]
        self.origins: dict[str, tuple[str, int]] = {}
        for name, origin in contract["runtime"]["origins"].items():
            parsed = urlsplit(origin)
            if (
                parsed.scheme != "http"
                or parsed.hostname != "127.0.0.1"
                or parsed.port is None
                or parsed.path
                or parsed.query
                or parsed.fragment
                or parsed.username is not None
                or parsed.password is not None
            ):
                raise QualificationError("configuration_error")
            self.origins[name] = (parsed.hostname, parsed.port)

    def action(self) -> None:
        self.actions += 1
        if self.actions > self.contract["bounds"]["max_actions"]:
            raise QualificationError("request_budget_exhausted")

    def call(
        self,
        service: str,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 30,
        cleanup: bool = False,
    ) -> tuple[int, bytes, dict[str, str]]:
        if service not in self.origins or not path.startswith("/"):
            raise QualificationError("configuration_error")
        if self.requests >= self.contract["bounds"]["max_requests"]:
            raise QualificationError("request_budget_exhausted")
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise QualificationError("transport_error")
        host, port = self.origins[service]
        connection = http.client.HTTPConnection(
            host, port, timeout=max(0.1, min(timeout, remaining))
        )
        request_headers = {"Accept": "application/json"}
        if headers:
            request_headers.update(headers)
        try:
            connection.request(method, path, body=body, headers=request_headers)
            response = connection.getresponse()
            raw = response.read(self.maximum + 1)
            response_headers = {key.lower(): value for key, value in response.getheaders()}
            status_code = response.status
        except (OSError, TimeoutError, http.client.HTTPException) as exc:
            raise QualificationError("cleanup_failed" if cleanup else "transport_error") from exc
        finally:
            connection.close()
        self.requests += 1
        if len(raw) > self.maximum:
            raise QualificationError("cleanup_failed" if cleanup else "transport_error")
        return status_code, raw, response_headers

    def json_call(
        self,
        service: str,
        method: str,
        path: str,
        value: Any | None = None,
        *,
        headers: dict[str, str] | None = None,
        timeout: float = 30,
        cleanup: bool = False,
    ) -> tuple[int, Any, int]:
        body = None if value is None else _canonical(value)
        request_headers = dict(headers or {})
        if body is not None:
            request_headers["Content-Type"] = "application/json"
        status, raw, _ = self.call(
            service,
            method,
            path,
            body=body,
            headers=request_headers,
            timeout=timeout,
            cleanup=cleanup,
        )
        decoded = None if not raw else _strict(raw, "cleanup_failed" if cleanup else "oracle_failed")
        return status, decoded, len(raw)


def _projection(rows: list[dict[str, Any]]) -> dict[str, Any]:
    encoded = sorted(_canonical(row) for row in rows)
    return {"count": len(rows), "sha256": _sha(b"\n".join(encoded))}


def _files(transport: Transport, *, cleanup: bool = False) -> list[dict[str, Any]]:
    status, value, _ = transport.json_call(
        "lvs", "GET", "/files?purpose=vision", cleanup=cleanup
    )
    rows = value.get("data") if isinstance(value, dict) else None
    if (
        status != 200
        or value.get("object") != "list"
        or not isinstance(rows, list)
        or len(rows) > transport.contract["bounds"]["max_catalog_items"]
        or not all(isinstance(row, dict) for row in rows)
    ):
        raise QualificationError("cleanup_failed" if cleanup else "oracle_failed")
    return rows


def _owned_rows(rows: list[dict[str, Any]], prefix: str) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if str(row.get("filename", "")).startswith(prefix)
        or str(row.get("sensor_name", "")).startswith(prefix)
    ]


def _multipart(
    *, boundary: str, file_id: str, filename: str, sensor_name: str, media: bytes
) -> bytes:
    fields = {
        "purpose": "vision",
        "media_type": "video",
        "id": file_id,
        "sensor_name": sensor_name,
    }
    pieces: list[bytes] = []
    for name, value in fields.items():
        pieces.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode(),
                b"\r\n",
            ]
        )
    pieces.extend(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(),
            b"Content-Type: video/mp4\r\n\r\n",
            media,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return b"".join(pieces)


def _generate_fixture(path: Path, contract: dict[str, Any]) -> dict[str, Any]:
    fixture = contract["fixture"]
    _run(
        [
            "/usr/bin/ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-fflags",
            "+bitexact",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size={fixture['width']}x{fixture['height']}:rate={fixture['fps']}",
            "-t",
            str(fixture["duration_seconds"]),
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
            str(fixture["fps"]),
            "-flags:v",
            "+bitexact",
            str(path),
        ],
        timeout=30,
        maximum=65536,
    )
    raw = path.read_bytes()
    if not 1000 <= len(raw) <= fixture["maximum_bytes"]:
        raise QualificationError("fixture_error")
    return {"bytes": len(raw), "sha256": _sha(raw)}


def _load_graph_password(contract: dict[str, Any]) -> str:
    path = ROOT / contract["runtime"]["graph_env"]
    if path.is_symlink() or not path.is_file():
        raise QualificationError("configuration_error")
    mode = stat.S_IMODE(path.stat(follow_symlinks=False).st_mode)
    if mode & 0o077:
        raise QualificationError("configuration_error")
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in values:
            raise QualificationError("configuration_error")
        values[key] = value
    password = values.get("GRAPH_DB_PASSWORD", "")
    if len(password) < 16 or "/" in password or "\n" in password or "\r" in password:
        raise QualificationError("configuration_error")
    return password


def _graph_query(
    transport: Transport, password: str, statement: str, parameters: dict[str, Any]
) -> list[list[Any]]:
    user = transport.contract["runtime"]["graph_user"]
    auth = base64.b64encode(f"{user}:{password}".encode()).decode()
    status, value, _ = transport.json_call(
        "neo4j",
        "POST",
        "/db/neo4j/tx/commit",
        {"statements": [{"statement": statement, "parameters": parameters}]},
        headers={"Authorization": f"Basic {auth}"},
    )
    try:
        errors = value["errors"]
        data = value["results"][0]["data"]
        rows = [item["row"] for item in data]
    except (KeyError, IndexError, TypeError) as exc:
        raise QualificationError("graph_error") from exc
    if status != 200 or errors or not all(isinstance(row, list) for row in rows):
        raise QualificationError("graph_error")
    return rows


def _graph_snapshot(transport: Transport, password: str) -> dict[str, int]:
    rows = _graph_query(
        transport,
        password,
        "MATCH (n) WITH count(n) AS nodes OPTIONAL MATCH ()-[r]->() RETURN nodes, count(r)",
        {},
    )
    if len(rows) != 1 or len(rows[0]) != 2 or not all(type(x) is int for x in rows[0]):
        raise QualificationError("graph_error")
    return {"nodes": rows[0][0], "relationships": rows[0][1]}


def _graph_asset_count(transport: Transport, password: str, asset_id: str) -> int:
    rows = _graph_query(
        transport,
        password,
        "MATCH (n) WHERE n.uuid = $asset_id RETURN count(n)",
        {"asset_id": asset_id},
    )
    if len(rows) != 1 or len(rows[0]) != 1 or type(rows[0][0]) is not int:
        raise QualificationError("graph_error")
    return rows[0][0]


def _completion(value: Any, source_id: str, model: str) -> bool:
    try:
        choices = value["choices"]
        content = choices[0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return False
    return (
        isinstance(value, dict)
        and value.get("video_id") == source_id
        and value.get("model") == model
        and isinstance(choices, list)
        and bool(choices)
        and isinstance(content, str)
        and bool(content.strip())
    )


def _captions(value: Any, model: str) -> bool:
    try:
        chunks = value["chunk_responses"]
    except (KeyError, TypeError):
        return False
    return (
        isinstance(value, dict)
        and value.get("model") == model
        and isinstance(chunks, list)
        and bool(chunks)
        and all(
            isinstance(row, dict)
            and isinstance(row.get("content"), str)
            and bool(row["content"].strip())
            for row in chunks
        )
    )


def _es_count(transport: Transport, index: str, *, cleanup: bool = False) -> tuple[int, bool]:
    status, value, _ = transport.json_call(
        "elasticsearch", "GET", f"/{quote(index, safe='')}/_count", cleanup=cleanup
    )
    if status == 404:
        return 0, False
    if status != 200 or not isinstance(value, dict) or type(value.get("count")) is not int:
        raise QualificationError("cleanup_failed" if cleanup else "oracle_failed")
    return value["count"], True


def _record(
    rows: list[dict[str, Any]], method: str, path: str, status: int, passed: bool, size: int
) -> None:
    if not passed:
        raise QualificationError("oracle_failed")
    rows.append(
        {
            "method": method,
            "path": path,
            "status": status,
            "response_bytes": size,
            "semantic_pass": True,
        }
    )


def execute(acknowledgement: str) -> dict[str, Any]:
    contract = _contract()
    if acknowledgement != contract["acknowledgement"]:
        raise QualificationError("authorization_required")
    started = time.monotonic()
    deadline = started + contract["bounds"]["max_duration_seconds"]
    sources = _source_hashes(contract)
    runtime_pre = _runtime_snapshot(contract)
    transport = Transport(contract, deadline)
    password = _load_graph_password(contract)
    prefix = contract["fixture"]["owned_prefix"]
    relay = contract["runtime"]["relay"]
    relay_name = relay["container"]
    if _run(
        ["docker", "inspect", relay_name],
        allowed_statuses={0, 1},
        maximum=65536,
    ).returncode == 0:
        raise QualificationError("fixture_error")

    file_rows_before = _files(transport)
    if _owned_rows(file_rows_before, prefix):
        raise QualificationError("fixture_error")
    catalog_before = _projection(file_rows_before)
    graph_before = _graph_snapshot(transport, password)
    _progress("preflight passed")

    run_uuid = uuid.uuid4()
    file_id = str(uuid.uuid4())
    camera_id = str(uuid.uuid4())
    filename = f"{prefix}{run_uuid.hex[:16]}.mp4"
    sensor_name = f"{prefix}{run_uuid.hex[16:]}"
    boundary = f"lvs-{run_uuid.hex}"
    temporary = Path(tempfile.mkdtemp(prefix="vss-lvs-rest-runtime-", dir="/tmp"))
    fixture_path = temporary / "fixture.mp4"
    publisher: subprocess.Popen[bytes] | None = None
    asset_id: str | None = None
    live_index: str | None = None
    file_added = False
    camera_added = False
    caption_attempted = False
    operations: list[dict[str, Any]] = []
    negatives: list[dict[str, Any]] = []
    cleanup = {
        "file_deleted": False,
        "camera_removed": False,
        "caption_stopped": False,
        "live_index_absent": False,
        "relay_absent": False,
        "fixture_absent": False,
        "catalog_restored": False,
        "graph_restored": False,
        "owned_graph_absent": False,
    }
    fixture_evidence: dict[str, Any] = {}
    graph_mid = {"nodes": -1, "relationships": -1}
    graph_asset_mid = -1
    live_documents = 0
    stream_ready = False
    try:
        fixture_evidence = _generate_fixture(fixture_path, contract)
        media = fixture_path.read_bytes()

        status, openapi, _ = transport.json_call("lvs", "GET", "/openapi.json")
        if status != 200 or not isinstance(openapi, dict):
            raise QualificationError("oracle_failed")
        discovered = sorted(
            [
                {"method": method.upper(), "path": path}
                for path, item in openapi.get("paths", {}).items()
                if isinstance(item, dict)
                for method in item
                if method.upper() in {"GET", "POST", "DELETE"}
            ],
            key=lambda row: (row["method"], row["path"]),
        )
        expected = sorted(contract["expected_operations"], key=lambda row: (row["method"], row["path"]))
        if discovered != expected:
            raise QualificationError("oracle_failed")
        _progress("operation discovery passed")

        for path in ("/v1/live", "/v1/ready", "/v1/startup"):
            status, value, size = transport.json_call("lvs", "GET", path)
            _record(
                operations,
                "GET",
                path,
                status,
                status == 200 and value is None and size == 0,
                size,
            )

        status, value, size = transport.json_call("lvs", "GET", "/v1/healthz")
        _record(
            operations,
            "GET",
            "/v1/healthz",
            status,
            status == 200
            and isinstance(value, dict)
            and value.get("status") == "ok"
            and isinstance(value.get("version"), str),
            size,
        )

        status, value, size = transport.json_call("lvs", "GET", "/v1/metadata")
        _record(operations, "GET", "/v1/metadata", status, status == 200 and isinstance(value, dict), size)

        status, value, size = transport.json_call("lvs", "GET", "/models")
        models = value.get("data") if isinstance(value, dict) else None
        if status != 200 or not isinstance(models, list) or len(models) != 1 or not isinstance(models[0].get("id"), str):
            raise QualificationError("oracle_failed")
        model = models[0]["id"]
        _record(operations, "GET", "/models", status, True, size)

        status, raw, _ = transport.call("lvs", "GET", "/metrics")
        _record(operations, "GET", "/metrics", status, status == 200 and len(raw) > 0, len(raw))
        _progress("read-only operations passed")

        status, _, _ = transport.json_call(
            "lvs", "GET", "/v1/live", headers={"Authorization": "Bearer qualification-nonsecret"}
        )
        if status != 200:
            raise QualificationError("oracle_failed")

        status, value, size = transport.json_call(
            "lvs", "POST", "/recommended_config",
            {"video_length": 2, "target_response_time": 5, "usecase_event_duration": 1},
        )
        _record(
            operations, "POST", "/recommended_config", status,
            status == 200 and isinstance(value, dict) and type(value.get("chunk_size")) is int,
            size,
        )
        negative_status, _, _ = transport.json_call(
            "lvs", "POST", "/recommended_config",
            {"video_length": 0, "target_response_time": 0, "usecase_event_duration": 0},
        )
        negatives.append({"case": "recommended_config_schema", "status": negative_status, "passed": negative_status == 422})
        if negative_status != 422:
            raise QualificationError("oracle_failed")
        _progress("recommended-config operation passed")

        multipart = _multipart(
            boundary=boundary, file_id=file_id, filename=filename,
            sensor_name=sensor_name, media=media,
        )
        transport.action()
        status, raw, _ = transport.call(
            "lvs", "POST", "/files", body=multipart,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            timeout=60,
        )
        value = _strict(raw, "oracle_failed")
        if (
            status != 200 or not isinstance(value, dict) or value.get("id") != file_id
            or value.get("filename") != filename or value.get("sensor_name") != sensor_name
        ):
            raise QualificationError("oracle_failed")
        file_added = True
        _record(operations, "POST", "/files", status, True, len(raw))
        _progress("file upload passed")

        rows_after_add = _files(transport)
        matches = _owned_rows(rows_after_add, prefix)
        if len(matches) != 1 or matches[0].get("id") != file_id:
            raise QualificationError("oracle_failed")
        _record(operations, "GET", "/files", 200, True, len(_canonical(rows_after_add)))

        status, value, size = transport.json_call("lvs", "GET", f"/files/{quote(file_id, safe='')}")
        _record(
            operations, "GET", "/files/{file_id}", status,
            status == 200 and isinstance(value, dict) and value.get("id") == file_id,
            size,
        )
        status, _, _ = transport.json_call("lvs", "GET", "/files/not-a-uuid")
        negatives.append({"case": "file_info_uuid_schema", "status": status, "passed": status == 422})
        if status != 422:
            raise QualificationError("oracle_failed")

        common = {
            "id": file_id,
            "model": model,
            "prompt": "Describe the visible synthetic motion concisely.",
            "chunk_duration": 0,
            "max_tokens": 96,
            "temperature": 0.0,
            "top_p": 1.0,
            "seed": 1,
        }
        status, value, size = transport.json_call(
            "lvs", "POST", "/generate_vlm_captions", common, timeout=180
        )
        _record(operations, "POST", "/generate_vlm_captions", status, status == 200 and _captions(value, model), size)

        bad_model = dict(common)
        bad_model["model"] = "qualification-model-does-not-exist"
        status, _, _ = transport.json_call("lvs", "POST", "/generate_vlm_captions", bad_model)
        negatives.append({"case": "caption_model_identity", "status": status, "passed": status == 400})
        if status != 400:
            raise QualificationError("oracle_failed")
        _progress("file caption operation passed")

        summary = dict(common)
        summary.update(
            {
                "scenario": "Synthetic edge AI qualification.",
                "events": ["visible motion"],
                "objects_of_interest": [],
                "override_vlm_prompt": True,
                "enable_qa": True,
                "num_frames_per_second_or_fixed_frames_chunk": 4,
                "use_fps_for_chunking": False,
            }
        )
        status, value, size = transport.json_call(
            "lvs", "POST", "/v1/summarize", summary, timeout=240
        )
        _record(operations, "POST", "/v1/summarize", status, status == 200 and _completion(value, file_id, model), size)
        graph_mid = _graph_snapshot(transport, password)
        graph_asset_mid = _graph_asset_count(transport, password, file_id)
        if graph_asset_mid <= 0 or graph_mid["nodes"] <= graph_before["nodes"]:
            raise QualificationError("oracle_failed")
        _progress("v1 summarize and graph ingest passed")

        chat = {
            "id": file_id,
            "model": model,
            "messages": [{"role": "user", "content": "What visible motion occurs?"}],
            "is_live": False,
            "max_tokens": 96,
            "temperature": 0.0,
            "top_p": 1.0,
        }
        status, value, size = transport.json_call(
            "lvs", "POST", "/v1/chat/completions", chat, timeout=180
        )
        _record(operations, "POST", "/v1/chat/completions", status, status == 200 and _completion(value, file_id, model), size)
        invalid_chat = dict(chat)
        invalid_chat.pop("messages")
        status, _, _ = transport.json_call("lvs", "POST", "/v1/chat/completions", invalid_chat)
        negatives.append({"case": "chat_required_messages", "status": status, "passed": status == 422})
        if status != 422:
            raise QualificationError("oracle_failed")
        _progress("graph question-answering passed")

        summary["enable_qa"] = False
        status, value, size = transport.json_call(
            "lvs", "POST", "/summarize", summary, timeout=240
        )
        _record(operations, "POST", "/summarize", status, status == 200 and _completion(value, file_id, model), size)
        _progress("legacy summarize alias passed")

        transport.action()
        _run(
            [
                "docker", "run", "-d", "--name", relay_name,
                "--network", relay["network"],
                "-p", f"127.0.0.1:{relay['host_port']}:{relay['container_port']}",
                relay["image"],
            ],
            timeout=30,
            maximum=65536,
        )
        publisher = subprocess.Popen(
            [
                "/usr/bin/ffmpeg", "-hide_banner", "-loglevel", "error", "-re",
                "-stream_loop", "-1", "-i", str(fixture_path), "-c:v", "copy",
                "-rtsp_transport", "tcp", "-f", "rtsp",
                f"rtsp://127.0.0.1:{relay['host_port']}/{relay['path']}",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        time.sleep(5)
        if publisher.poll() is not None:
            raise QualificationError("fixture_error")
        _run(
            [
                "/usr/bin/ffprobe", "-v", "error", "-rtsp_transport", "tcp",
                "-show_entries", "stream=codec_name,width,height", "-of", "json",
                f"rtsp://127.0.0.1:{relay['host_port']}/{relay['path']}",
            ],
            timeout=15,
            maximum=65536,
        )
        probe = _run(
            [
                "docker", "exec", "vss-rtvi-vlm", "/usr/bin/timeout", "8",
                "gst-launch-1.0", "-q",
                "rtspsrc", f"location=rtsp://{relay_name}:{relay['container_port']}/{relay['path']}",
                "protocols=tcp", "latency=0", "!", "rtph264depay", "!",
                "h264parse", "!", "fakesink", "sync=false",
            ],
            timeout=15,
            maximum=65536,
            allowed_statuses={0, 124},
        )
        stream_ready = probe.returncode in {0, 124}
        time.sleep(1)
        _progress("private stream readiness passed")

        status, add_value, _ = transport.json_call(
            "rtvi_vlm", "POST", "/v1/stream/add",
            {
                "key": "sensor",
                "value": {
                    "camera_id": camera_id,
                    "camera_name": "owned-lvs-runtime",
                    "camera_url": f"rtsp://{relay_name}:{relay['container_port']}/{relay['path']}",
                    "change": "camera_add",
                },
                "headers": {"source": "thor-lvs-runtime"},
            },
        )
        if status != 200 or not isinstance(add_value, dict) or not isinstance(add_value.get("asset_id"), str):
            raise QualificationError("oracle_failed")
        asset_id = str(uuid.UUID(add_value["asset_id"]))
        camera_added = True
        live_index = "default_" + asset_id.replace("-", "_")
        pre_count, _ = _es_count(transport, live_index)
        if pre_count != 0:
            raise QualificationError("oracle_failed")

        caption_attempted = True
        live_request = {
            "id": asset_id,
            "model": model,
            "prompt": "Describe visible activity in one concise sentence.",
            "override_vlm_prompt": True,
            "scenario": "Synthetic edge AI qualification.",
            "events": ["visible activity"],
            "objects_of_interest": [],
            "chunk_duration": 2,
            "chunk_overlap_duration": 0,
            "num_frames_per_second_or_fixed_frames_chunk": 4,
            "use_fps_for_chunking": False,
            "max_tokens": 96,
            "temperature": 0.0,
            "top_p": 1.0,
            "seed": 1,
            "enable_qa": False,
        }
        status, value, size = transport.json_call(
            "lvs", "POST", "/v1/generate_captions", live_request, timeout=45
        )
        _record(
            operations, "POST", "/v1/generate_captions", status,
            status == 200 and value == {"id": asset_id, "status": "accepted", "model": model},
            size,
        )
        for _ in range(contract["bounds"]["live_poll_attempts"]):
            time.sleep(contract["bounds"]["live_poll_delay_seconds"])
            live_documents, _ = _es_count(transport, live_index)
            if live_documents > 0:
                break
        if live_documents <= 0:
            raise QualificationError("oracle_failed")
        _progress("live caption delivery passed")

        status, value, size = transport.json_call(
            "lvs", "POST", "/v1/stream_summarize",
            {
                "id": asset_id,
                "model": model,
                "start_time": 0,
                "end_time": 0,
                "camera_id": camera_id,
                "delete_external_collection": False,
                "enable_qa": False,
                "summarize_max_tokens": 128,
                "summarize_temperature": 0.0,
                "summarize_top_p": 1.0,
            },
            timeout=180,
        )
        _record(operations, "POST", "/v1/stream_summarize", status, status == 200 and _completion(value, asset_id, model), size)
        _progress("stream summarize passed")

        malformed_status, _, _ = transport.json_call(
            "lvs", "POST", "/v1/generate_captions",
            {"id": "not-a-uuid", "model": model},
        )
        negatives.append({"case": "live_caption_uuid_schema", "status": malformed_status, "passed": malformed_status == 422})
        if malformed_status != 422:
            raise QualificationError("oracle_failed")

        transport.action()
        status, value, size = transport.json_call(
            "lvs", "DELETE", f"/files/{quote(file_id, safe='')}", timeout=120
        )
        if status != 200 or value != {"id": file_id, "object": "file", "deleted": True}:
            raise QualificationError("oracle_failed")
        file_added = False
        cleanup["file_deleted"] = True
        _record(operations, "DELETE", "/files/{file_id}", status, True, size)
        _progress("file delete passed")

        malformed_status, _, _ = transport.json_call("lvs", "DELETE", "/files/not-a-uuid")
        negatives.append({"case": "file_delete_uuid_schema", "status": malformed_status, "passed": malformed_status == 422})
        if malformed_status != 422:
            raise QualificationError("oracle_failed")
    finally:
        cleanup_failed = False
        if caption_attempted and asset_id:
            try:
                status, _, _ = transport.json_call(
                    "rtvi_vlm", "DELETE", f"/v1/generate_captions/{quote(asset_id, safe='')}",
                    timeout=60, cleanup=True,
                )
                cleanup["caption_stopped"] = status in {200, 400, 404}
                cleanup_failed |= not cleanup["caption_stopped"]
            except QualificationError:
                cleanup_failed = True
        if camera_added:
            try:
                status, _, _ = transport.json_call(
                    "rtvi_vlm", "POST", "/v1/stream/remove",
                    {
                        "key": "sensor",
                        "value": {"camera_id": camera_id, "change": "camera_remove"},
                        "headers": {"source": "thor-lvs-runtime"},
                    },
                    timeout=60, cleanup=True,
                )
                cleanup["camera_removed"] = status in {200, 404}
                cleanup_failed |= not cleanup["camera_removed"]
            except QualificationError:
                cleanup_failed = True
        if live_index:
            try:
                status, _, _ = transport.json_call(
                    "elasticsearch", "DELETE", f"/{quote(live_index, safe='')}",
                    timeout=60, cleanup=True,
                )
                count, exists = _es_count(transport, live_index, cleanup=True)
                cleanup["live_index_absent"] = status in {200, 404} and count == 0 and not exists
                cleanup_failed |= not cleanup["live_index_absent"]
            except QualificationError:
                cleanup_failed = True
        if file_added:
            try:
                status, value, _ = transport.json_call(
                    "lvs", "DELETE", f"/files/{quote(file_id, safe='')}",
                    timeout=120, cleanup=True,
                )
                cleanup["file_deleted"] = status == 200 and isinstance(value, dict) and value.get("deleted") is True
                cleanup_failed |= not cleanup["file_deleted"]
            except QualificationError:
                cleanup_failed = True
        if publisher is not None:
            publisher.terminate()
            try:
                publisher.wait(timeout=10)
            except subprocess.TimeoutExpired:
                publisher.kill()
                publisher.wait(timeout=5)
        try:
            transport.action()
            _run(
                ["docker", "rm", "-f", relay_name],
                timeout=30,
                maximum=65536,
                allowed_statuses={0, 1},
            )
            cleanup["relay_absent"] = _run(
                ["docker", "inspect", relay_name],
                timeout=20,
                maximum=65536,
                allowed_statuses={0, 1},
            ).returncode == 1
            cleanup_failed |= not cleanup["relay_absent"]
        except QualificationError:
            cleanup_failed = True
        if temporary.exists():
            shutil.rmtree(temporary)
        cleanup["fixture_absent"] = not temporary.exists()
        cleanup_failed |= not cleanup["fixture_absent"]
        try:
            file_rows_after = _files(transport, cleanup=True)
            cleanup["catalog_restored"] = _projection(file_rows_after) == catalog_before and not _owned_rows(file_rows_after, prefix)
            graph_after = _graph_snapshot(transport, password)
            cleanup["graph_restored"] = graph_after == graph_before
            cleanup["owned_graph_absent"] = _graph_asset_count(transport, password, file_id) == 0
            cleanup_failed |= not all(
                cleanup[key]
                for key in ("catalog_restored", "graph_restored", "owned_graph_absent")
            )
        except QualificationError:
            cleanup_failed = True
        if cleanup_failed:
            raise QualificationError("cleanup_failed")

    runtime_post = _runtime_snapshot(contract)
    if runtime_post != runtime_pre:
        raise QualificationError("runtime_identity_error")
    _progress("exact cleanup and runtime restoration passed")
    expected_sorted = sorted(contract["expected_operations"], key=lambda row: (row["method"], row["path"]))
    operations_sorted = sorted(operations, key=lambda row: (row["method"], row["path"]))
    if [(row["method"], row["path"]) for row in operations_sorted] != [
        (row["method"], row["path"]) for row in expected_sorted
    ]:
        raise QualificationError("oracle_failed")
    if len(operations) != 18 or not all(row["semantic_pass"] for row in operations):
        raise QualificationError("oracle_failed")
    if not all(row["passed"] for row in negatives):
        raise QualificationError("oracle_failed")

    duration = time.monotonic() - started
    if duration > contract["bounds"]["max_duration_seconds"]:
        raise QualificationError("transport_error")
    receipt = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "capability_id": contract["capability_id"],
        "oracle_id": contract["oracle_id"],
        "target_commit": contract["target_commit"],
        "contract_sha256": _sha(CONTRACT_PATH.read_bytes()),
        "source_hashes": sources,
        "result": "passed",
        "promotion_eligible": True,
        "duration_seconds": round(duration, 3),
        "warehouse_sample_bundle": "excluded",
        "runtime": {"pre": runtime_pre, "post": runtime_post, "unchanged": True},
        "discovery": {
            "operation_count": len(expected_sorted),
            "operation_set_sha256": _sha(_canonical(expected_sorted)),
            "expected_manifest_sha256": contract["expected_manifest_sha256"],
            "exact": True,
        },
        "auth": {
            "declared": "bearer",
            "missing_authorization_status": 200,
            "fake_bearer_status": 200,
            "enforced_by_lvs": False,
            "boundary": contract["policy"]["auth_boundary"],
        },
        "fixture": {
            "bytes": fixture_evidence["bytes"],
            "sha256": fixture_evidence["sha256"],
            "filename_sha256": _sha(filename.encode()),
            "sensor_name_sha256": _sha(sensor_name.encode()),
            "file_id_sha256": _sha(file_id.encode()),
            "camera_id_sha256": _sha(camera_id.encode()),
            "live_asset_id_sha256": _sha(str(asset_id).encode()),
        },
        "operations": operations_sorted,
        "negatives": negatives,
        "file_lifecycle": {
            "catalog_before": catalog_before,
            "catalog_restored": cleanup["catalog_restored"],
            "graph_before": graph_before,
            "graph_mid": graph_mid,
            "graph_asset_mid_count": graph_asset_mid,
            "graph_restored": cleanup["graph_restored"],
            "owned_graph_absent": cleanup["owned_graph_absent"],
            "file_deleted": cleanup["file_deleted"],
        },
        "live": {
            "private_stream_readiness": stream_ready,
            "caption_documents": live_documents,
            "caption_stopped": cleanup["caption_stopped"],
            "camera_removed": cleanup["camera_removed"],
            "owned_index_absent": cleanup["live_index_absent"],
            "relay_absent": cleanup["relay_absent"],
        },
        "cleanup": cleanup,
        "counts": {"requests": transport.requests, "actions": transport.actions},
        "policy": contract["policy"],
    }
    return receipt


def _write_receipt(receipt: dict[str, Any]) -> None:
    raw = _canonical(receipt) + b"\n"
    with tempfile.NamedTemporaryFile(dir=HERE, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(RECEIPT_PATH)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ack", required=True)
    args = parser.parse_args()
    try:
        receipt = execute(args.ack)
        _write_receipt(receipt)
    except QualificationError as exc:
        print(json.dumps({"status": "failed", "failure": exc.code}, sort_keys=True))
        return 1
    print(
        json.dumps(
            {
                "status": "passed",
                "operation_count": len(receipt["operations"]),
                "requests": receipt["counts"]["requests"],
                "actions": receipt["counts"]["actions"],
                "cleanup": "passed",
                "promotion_eligible": receipt["promotion_eligible"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
