#!/usr/bin/env python3
"""Exercise the exact 13-tool LVS MCP contract with an owned file lifecycle."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
from pathlib import Path
import stat
import subprocess
import sys
import time
from typing import Any
from urllib.parse import urlsplit
import uuid


ROOT = Path(__file__).resolve().parents[5]
HERE = Path(__file__).resolve().parent
CONTRACT_PATH = HERE / "contract.json"
RECEIPT_PATH = HERE / "runtime-receipt.json"


class QualificationError(RuntimeError):
    """A bounded error whose message cannot disclose runtime material."""

    ALLOWED = {
        "authorization_required",
        "cleanup_failed",
        "configuration_error",
        "fixture_error",
        "mcp_error",
        "oracle_failed",
        "rest_error",
        "runtime_identity_error",
        "source_lock_error",
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


def _strict(raw: bytes, error_code: str = "configuration_error") -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in items:
            if key in value:
                raise QualificationError(error_code)
            value[key] = item
        return value

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError(error_code) from exc


def _contract() -> dict[str, Any]:
    value = _strict(CONTRACT_PATH.read_bytes())
    if not isinstance(value, dict):
        raise QualificationError("configuration_error")
    return value


def _run(
    argv: list[str],
    *,
    input_bytes: bytes | None = None,
    timeout: int = 30,
    maximum: int = 1_048_576,
) -> bytes:
    try:
        completed = subprocess.run(
            argv,
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            timeout=timeout,
            env={
                "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
            },
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise QualificationError("runtime_identity_error") from exc
    if len(completed.stdout) > maximum or len(completed.stderr) > maximum:
        raise QualificationError("runtime_identity_error")
    return completed.stdout


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
    return result


def _runtime_snapshot(contract: dict[str, Any]) -> dict[str, Any]:
    raw = _run(
        ["docker", "inspect", contract["runtime"]["container"]],
        timeout=20,
        maximum=2_000_000,
    )
    value = _strict(raw, "runtime_identity_error")
    if not isinstance(value, list) or len(value) != 1:
        raise QualificationError("runtime_identity_error")
    item = value[0]
    try:
        state = item["State"]
        observed = {
            "name": item["Name"].lstrip("/"),
            "image": item["Config"]["Image"],
            "container_id_sha256": _sha(item["Id"].encode()),
            "image_id_sha256": _sha(item["Image"].encode()),
            "started_at_sha256": _sha(state["StartedAt"].encode()),
            "restart_count": item["RestartCount"],
            "health": state["Health"]["Status"],
            "network_mode": item["HostConfig"]["NetworkMode"],
        }
    except (AttributeError, KeyError, TypeError) as exc:
        raise QualificationError("runtime_identity_error") from exc
    runtime = contract["runtime"]
    if (
        observed["name"] != runtime["container"]
        or observed["image"] != runtime["image"]
        or observed["health"] != runtime["required_health"]
        or observed["network_mode"] != runtime["network_mode"]
    ):
        raise QualificationError("runtime_identity_error")
    return observed


def _media_inventory(root: Path, prefix: str) -> dict[str, Any]:
    if root.is_symlink() or not root.is_dir():
        raise QualificationError("configuration_error")
    rows: list[dict[str, Any]] = []
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        if path.is_symlink():
            raise QualificationError("configuration_error")
        metadata = path.stat()
        if not stat.S_ISREG(metadata.st_mode):
            continue
        if path.name.startswith(prefix):
            raise QualificationError("fixture_error")
        rows.append(
            {
                "name_sha256": _sha(path.name.encode()),
                "bytes": metadata.st_size,
                "content_sha256": _sha(path.read_bytes()),
            }
        )
    return {
        "regular_file_count": len(rows),
        "projection_sha256": _sha(_canonical(rows)),
    }


class RestClient:
    def __init__(self, contract: dict[str, Any], deadline: float):
        parsed = urlsplit(contract["runtime"]["rest_origin"])
        if (
            parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise QualificationError("configuration_error")
        self.host = parsed.hostname
        self.port = parsed.port
        self.deadline = deadline
        self.maximum = contract["bounds"]["max_rest_response_bytes"]
        self.max_requests = contract["bounds"]["max_rest_validation_requests"]
        self.requests = 0

    def call(self, method: str, path: str, expected: set[int]) -> tuple[int, Any]:
        if method not in {"DELETE", "GET"} or not path.startswith("/"):
            raise QualificationError("configuration_error")
        if self.requests >= self.max_requests or time.monotonic() >= self.deadline:
            raise QualificationError("rest_error")
        connection = http.client.HTTPConnection(
            self.host,
            self.port,
            timeout=max(0.1, min(15.0, self.deadline - time.monotonic())),
        )
        try:
            connection.request(method, path, headers={"Accept": "application/json"})
            response = connection.getresponse()
            raw = response.read(self.maximum + 1)
            status_code = response.status
        except (OSError, TimeoutError, http.client.HTTPException) as exc:
            raise QualificationError("rest_error") from exc
        finally:
            connection.close()
        self.requests += 1
        if status_code not in expected or len(raw) > self.maximum:
            raise QualificationError("rest_error")
        return status_code, _strict(raw, "rest_error")

    def files(self) -> list[dict[str, Any]]:
        _, value = self.call("GET", "/files?purpose=vision", {200})
        rows = value.get("data") if isinstance(value, dict) else None
        if (
            not isinstance(value, dict)
            or value.get("object") != "list"
            or not isinstance(rows, list)
            or len(rows) > 1000
            or not all(isinstance(row, dict) for row in rows)
        ):
            raise QualificationError("rest_error")
        return rows


def _catalog_projection(rows: list[dict[str, Any]]) -> dict[str, Any]:
    encoded = sorted(_canonical(row) for row in rows)
    return {"count": len(rows), "sha256": _sha(b"\n".join(encoded))}


def _owned_rows(
    rows: list[dict[str, Any]], filename: str, sensor_name: str
) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if row.get("filename") == filename or row.get("sensor_name") == sensor_name
    ]


def _cleanup_rest(client: RestClient, filename: str, sensor_name: str) -> int:
    rows = _owned_rows(client.files(), filename, sensor_name)
    if not rows:
        return 0
    if len(rows) != 1 or not isinstance(rows[0].get("id"), str):
        raise QualificationError("cleanup_failed")
    try:
        file_id = str(uuid.UUID(rows[0]["id"]))
    except (AttributeError, TypeError, ValueError) as exc:
        raise QualificationError("cleanup_failed") from exc
    client.call("DELETE", f"/files/{file_id}", {200})
    if _owned_rows(client.files(), filename, sensor_name):
        raise QualificationError("cleanup_failed")
    return 1


def _generate_fixture(path: Path, maximum: int) -> dict[str, Any]:
    _run(
        [
            "/usr/bin/ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-n",
            "-fflags",
            "+bitexact",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=5",
            "-t",
            "1",
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
            "5",
            "-flags:v",
            "+bitexact",
            str(path),
        ],
        timeout=30,
        maximum=65536,
    )
    raw = path.read_bytes()
    if not 1000 <= len(raw) <= maximum:
        raise QualificationError("fixture_error")
    return {"bytes": len(raw), "sha256": _sha(raw)}


def _child_program(filename: str, sensor_name: str, mcp_url: str) -> bytes:
    configuration = json.dumps(
        {"filename": filename, "sensor_name": sensor_name, "mcp_url": mcp_url}
    )
    source = r"""
import anyio
import hashlib
import json
from uuid import UUID
from mcp import ClientSession
from mcp.client.sse import sse_client

CONFIG = __CONFIG__
EXPECTED = [
    "add_file", "delete_file", "generate_captions", "generate_vlm_captions",
    "get_file_info", "get_metrics", "get_recommended_config", "health_live",
    "health_ready", "list_files", "list_models", "stream_summarize",
    "summarize_video",
]

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()

def sha(value):
    return hashlib.sha256(value).hexdigest()

def parsed(result, name, expect_error=False):
    texts = [item.text for item in result.content if getattr(item, "type", None) == "text"]
    if len(texts) != 1:
        raise RuntimeError("content-shape")
    if expect_error:
        try:
            error = json.loads(texts[0])
        except json.JSONDecodeError as exc:
            raise RuntimeError("error-boundary") from exc
        if result.isError is not True or error != {
            "error": f"{name} failed; see the LVS service log for details"
        }:
            raise RuntimeError("error-boundary")
        return None
    if result.isError:
        raise RuntimeError("tool-error")
    return json.loads(texts[0])

def rows(value):
    if not isinstance(value, dict) or value.get("object") != "list" or not isinstance(value.get("data"), list):
        raise RuntimeError("catalog-shape")
    return value["data"]

def projection(values):
    encoded = sorted(canonical(value) for value in values)
    return {"count": len(values), "sha256": sha(b"\n".join(encoded))}

async def main():
    calls = []
    created = None
    deleted = False
    async with sse_client(CONFIG["mcp_url"], timeout=5, sse_read_timeout=90) as streams:
        async with ClientSession(*streams) as session:
            initialized = await session.initialize()
            tools = await session.list_tools()
            names = sorted(tool.name for tool in tools.tools)
            if names != EXPECTED or any(not isinstance(tool.inputSchema, dict) for tool in tools.tools):
                raise RuntimeError("tool-catalog")
            catalog_sha = sha(canonical([
                {"name": tool.name, "input_schema": tool.inputSchema}
                for tool in sorted(tools.tools, key=lambda value: value.name)
            ]))

            async def call(name, arguments, expect_error=False):
                result = await session.call_tool(name, arguments)
                value = parsed(result, name, expect_error=expect_error)
                calls.append({"name": name, "result": "expected_error" if expect_error else "passed"})
                return value

            ready = await call("health_ready", {})
            live = await call("health_live", {})
            models = await call("list_models", {})
            recommended = await call("get_recommended_config", {
                "video_length": 300,
                "target_response_time": 60,
                "usecase_event_duration": 5,
            })
            metrics = await call("get_metrics", {})
            before = rows(await call("list_files", {}))
            if any(row.get("filename") == CONFIG["filename"] or row.get("sensor_name") == CONFIG["sensor_name"] for row in before):
                raise RuntimeError("owned-collision")
            await call("add_file", {"path": "../etc/passwd"}, expect_error=True)
            await call("delete_file", {
                "file_id": "11111111-1111-4111-8111-111111111111",
                "confirm_file_id": "22222222-2222-4222-8222-222222222222",
            }, expect_error=True)
            try:
                added = await call("add_file", {
                    "path": CONFIG["filename"],
                    "creation_time": "2025-01-01T00:00:00.000Z",
                    "sensor_name": CONFIG["sensor_name"],
                })
                created = added.get("id") if isinstance(added, dict) else None
                UUID(created)
                if (
                    added.get("filename") != CONFIG["filename"]
                    or added.get("purpose") != "vision"
                    or added.get("media_type") != "video"
                    or added.get("sensor_name") != CONFIG["sensor_name"]
                    or added.get("creation_time") != "2025-01-01T00:00:00.000Z"
                    or not isinstance(added.get("bytes"), int)
                    or added["bytes"] <= 0
                ):
                    raise RuntimeError("add-semantics")
                after_add = rows(await call("list_files", {}))
                matches = [row for row in after_add if row.get("id") == created]
                if len(matches) != 1 or projection([row for row in after_add if row.get("id") != created]) != projection(before):
                    raise RuntimeError("list-after-add")
                info = await call("get_file_info", {"file_id": created})
                for key in ("id", "bytes", "filename", "purpose", "creation_time", "sensor_name"):
                    if info.get(key) != added.get(key):
                        raise RuntimeError("info-semantics")
                deletion = await call("delete_file", {"file_id": created, "confirm_file_id": created})
                if deletion != {"id": created, "object": "file", "deleted": True}:
                    raise RuntimeError("delete-semantics")
                deleted = True
                final_rows = rows(await call("list_files", {}))
                if projection(final_rows) != projection(before):
                    raise RuntimeError("catalog-restoration")
            finally:
                if created is not None and not deleted:
                    await session.call_tool("delete_file", {"file_id": created, "confirm_file_id": created})

            metrics_text = metrics.get("metrics") if isinstance(metrics, dict) else None
            if ready != {"status": "ready", "code": 200} or live != {"status": "alive", "code": 200}:
                raise RuntimeError("health-semantics")
            if not isinstance(models, (dict, list)) or not isinstance(recommended, dict):
                raise RuntimeError("non-inference-semantics")
            if not isinstance(metrics_text, str) or not metrics_text:
                raise RuntimeError("metrics-semantics")
            output = {
                "protocol_version": initialized.protocolVersion,
                "server_name": initialized.serverInfo.name,
                "server_version": initialized.serverInfo.version,
                "tool_count": len(names),
                "all_tools_have_schemas": True,
                "tool_catalog_sha256": catalog_sha,
                "calls": calls,
                "file_id": created,
                "file_bytes": added["bytes"],
                "filename": CONFIG["filename"],
                "sensor_name": CONFIG["sensor_name"],
                "catalog_before": projection(before),
                "catalog_after": projection(final_rows),
                "list_after_add_exact": True,
                "get_info_exact": True,
                "delete_confirmation_exact": True,
                "negative_traversal_sanitized": True,
                "negative_confirmation_sanitized": True,
                "models_response_sha256": sha(canonical(models)),
                "recommended_response_sha256": sha(canonical(recommended)),
                "metrics_bytes": len(metrics_text.encode()),
                "metrics_sha256": sha(metrics_text.encode()),
            }
            print(json.dumps(output, sort_keys=True, separators=(",", ":")))

anyio.run(main)
""".replace("__CONFIG__", configuration)
    return source.encode()


def _validate_child(
    value: Any,
    contract: dict[str, Any],
    fixture: dict[str, Any],
    filename: str,
    sensor_name: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise QualificationError("mcp_error")
    try:
        uuid.UUID(value["file_id"])
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise QualificationError("mcp_error") from exc
    expected_calls = [
        {"name": name, "result": "passed"}
        for name in contract["expected_success_calls"][:6]
    ]
    expected_calls += [
        {"name": "add_file", "result": "expected_error"},
        {"name": "delete_file", "result": "expected_error"},
    ]
    expected_calls += [
        {"name": name, "result": "passed"}
        for name in contract["expected_success_calls"][6:]
    ]
    required_true = (
        "all_tools_have_schemas",
        "list_after_add_exact",
        "get_info_exact",
        "delete_confirmation_exact",
        "negative_traversal_sanitized",
        "negative_confirmation_sanitized",
    )
    if (
        value.get("tool_count") != len(contract["expected_tools"])
        or value.get("calls") != expected_calls
        or any(value.get(key) is not True for key in required_true)
        or value.get("catalog_before") != value.get("catalog_after")
        or value.get("file_bytes") != fixture["bytes"]
        or value.get("filename") != filename
        or value.get("sensor_name") != sensor_name
    ):
        raise QualificationError("oracle_failed")
    return value


def execute(acknowledgement: str) -> dict[str, Any]:
    contract = _contract()
    if acknowledgement != contract["acknowledgement"]:
        raise QualificationError("authorization_required")
    started = time.monotonic()
    deadline = started + contract["bounds"]["max_duration_seconds"]
    source_hashes = _source_hashes(contract)
    before_runtime = _runtime_snapshot(contract)
    media_root = ROOT / contract["fixture"]["host_media_root"]
    prefix = contract["fixture"]["owned_prefix"]
    before_media = _media_inventory(media_root, prefix)
    run_token = uuid.uuid4().hex[:16]
    filename = f"{prefix}{run_token}.mp4"
    sensor_name = f"{prefix}{run_token}"
    fixture_path = media_root / filename
    rest = RestClient(contract, deadline)
    before_rest_rows = rest.files()
    if _owned_rows(before_rest_rows, filename, sensor_name):
        raise QualificationError("fixture_error")
    before_rest = _catalog_projection(before_rest_rows)
    fixture: dict[str, Any] | None = None
    child: dict[str, Any] | None = None
    fallback_deletes = 0
    primary_error: QualificationError | None = None
    try:
        fixture = _generate_fixture(fixture_path, contract["fixture"]["maximum_bytes"])
        raw = _run(
            ["docker", "exec", "-i", contract["runtime"]["container"], "python3", "-"],
            input_bytes=_child_program(
                filename, sensor_name, contract["runtime"]["mcp_url"]
            ),
            timeout=150,
            maximum=contract["bounds"]["max_subprocess_output_bytes"],
        )
        child = _validate_child(
            _strict(raw, "mcp_error"), contract, fixture, filename, sensor_name
        )
    except QualificationError as exc:
        primary_error = exc
    finally:
        try:
            fallback_deletes = _cleanup_rest(rest, filename, sensor_name)
        except QualificationError:
            raise QualificationError("cleanup_failed") from primary_error
        try:
            if fixture_path.exists():
                fixture_path.unlink()
        except OSError as exc:
            raise QualificationError("cleanup_failed") from exc
    if primary_error is not None:
        raise primary_error
    if fixture is None or child is None or fallback_deletes != 0:
        raise QualificationError("oracle_failed")
    after_rest_rows = rest.files()
    after_rest = _catalog_projection(after_rest_rows)
    after_media = _media_inventory(media_root, prefix)
    after_runtime = _runtime_snapshot(contract)
    if (
        before_rest != after_rest
        or before_media != after_media
        or before_runtime != after_runtime
        or _owned_rows(after_rest_rows, filename, sensor_name)
    ):
        raise QualificationError("cleanup_failed")
    duration = time.monotonic() - started
    if duration > contract["bounds"]["max_duration_seconds"]:
        raise QualificationError("oracle_failed")
    receipt = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "capability_id": contract["capability_id"],
        "oracle_id": contract["oracle_id"],
        "target_commit": contract["target_commit"],
        "contract_sha256": _sha(CONTRACT_PATH.read_bytes()),
        "result": "passed",
        "promotion_eligible": True,
        "warehouse_sample_bundle": "excluded",
        "source_hashes": source_hashes,
        "runtime": {"pre": before_runtime, "post": after_runtime, "unchanged": True},
        "transport": {
            "scope": contract["bounds"]["network_scope"],
            "protocol_version": child["protocol_version"],
            "server_name": child["server_name"],
            "server_version": child["server_version"],
            "tool_count": child["tool_count"],
            "all_tools_have_schemas": child["all_tools_have_schemas"],
            "tool_catalog_sha256": child["tool_catalog_sha256"],
        },
        "tool_calls": child["calls"],
        "non_inference": {
            "models_response_sha256": child["models_response_sha256"],
            "recommended_response_sha256": child["recommended_response_sha256"],
            "metrics_bytes": child["metrics_bytes"],
            "metrics_sha256": child["metrics_sha256"],
        },
        "fixture": {
            "generator": contract["fixture"]["generator"],
            "bytes": fixture["bytes"],
            "sha256": fixture["sha256"],
            "filename_sha256": _sha(filename.encode()),
            "sensor_name_sha256": _sha(sensor_name.encode()),
            "file_id_sha256": _sha(child["file_id"].encode()),
        },
        "lifecycle": {
            "catalog_before": child["catalog_before"],
            "catalog_after": child["catalog_after"],
            "list_after_add_exact": child["list_after_add_exact"],
            "get_info_exact": child["get_info_exact"],
            "delete_confirmation_exact": child["delete_confirmation_exact"],
            "negative_traversal_sanitized": child["negative_traversal_sanitized"],
            "negative_confirmation_sanitized": child["negative_confirmation_sanitized"],
        },
        "cleanup": {
            "rest_catalog_before": before_rest,
            "rest_catalog_after": after_rest,
            "media_root_before": before_media,
            "media_root_after": after_media,
            "fallback_deletes": fallback_deletes,
            "owned_resource_absent": True,
            "complete_catalog_restored": True,
            "complete_media_root_restored": True,
            "service_lifecycle_mutations": 0,
        },
        "counts": {
            "tool_calls": len(child["calls"]),
            "successful_tool_calls": sum(
                row["result"] == "passed" for row in child["calls"]
            ),
            "expected_error_tool_calls": sum(
                row["result"] == "expected_error" for row in child["calls"]
            ),
            "rest_validation_requests": rest.requests,
            "persistent_mutations": 4,
            "inference_tool_calls": 0,
            "stream_mutations": 0,
        },
        "duration_milliseconds": round(duration * 1000),
    }
    RECEIPT_PATH.write_bytes(_canonical(receipt) + b"\n")
    return {
        "package_id": receipt["package_id"],
        "result": receipt["result"],
        "tool_count": receipt["transport"]["tool_count"],
        "tool_calls": receipt["counts"]["tool_calls"],
        "persistent_mutations": receipt["counts"]["persistent_mutations"],
        "promotion_eligible": receipt["promotion_eligible"],
        "warehouse_sample_bundle": receipt["warehouse_sample_bundle"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ack", default="")
    args = parser.parse_args()
    try:
        result = execute(args.ack)
    except QualificationError as exc:
        print(json.dumps({"status": "failed", "failure": exc.code}), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
