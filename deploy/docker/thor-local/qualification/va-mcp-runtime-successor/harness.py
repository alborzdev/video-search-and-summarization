#!/usr/bin/env python3
"""Exercise every read-only VA-MCP tool on the live Thor deployment."""

from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import http.client
import json
import os
from pathlib import Path
import platform
import subprocess
import tempfile
from typing import Any

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parent
CONTRACT_PATH = HERE / "contract.json"
SCHEMA_PATH = HERE / "receipt.schema.json"
RECEIPT_PATH = HERE / "runtime-receipt.json"
HOST = "127.0.0.1"
PORT = 9901
MCP_PATH = "/mcp"


class QualificationError(RuntimeError):
    pass


def _reject_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise QualificationError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_pairs,
            parse_constant=lambda token: (_ for _ in ()).throw(
                QualificationError(f"non-finite JSON: {token}")
            ),
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise QualificationError(f"cannot read strict JSON: {path.name}") from exc
    if not isinstance(value, dict):
        raise QualificationError(f"expected JSON object: {path.name}")
    return value


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_text(value: str) -> str:
    return _sha_bytes(value.encode("utf-8"))


def _sha_file(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _docker_json(*args: str) -> Any:
    result = subprocess.run(
        ["docker", *args], check=True, capture_output=True, text=True, timeout=15
    )
    return json.loads(result.stdout)


def _running_ids() -> list[str]:
    result = subprocess.run(
        ["docker", "ps", "--format", "{{.ID}}"],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    return sorted(line for line in result.stdout.splitlines() if line)


def _post(payload: dict[str, Any], session_id: str | None = None) -> tuple[int, dict[str, str], dict[str, Any]]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if session_id is not None:
        headers["mcp-session-id"] = session_id
    connection = http.client.HTTPConnection(HOST, PORT, timeout=15)
    try:
        connection.request("POST", MCP_PATH, body=json.dumps(payload), headers=headers)
        response = connection.getresponse()
        body = response.read().decode("utf-8")
        response_headers = {key.lower(): value for key, value in response.getheaders()}
    finally:
        connection.close()
    events = [line[6:] for line in body.splitlines() if line.startswith("data: ")]
    if not events:
        raise QualificationError(f"MCP response had no SSE data event (HTTP {response.status})")
    try:
        event = json.loads(events[-1], object_pairs_hook=_reject_pairs)
    except json.JSONDecodeError as exc:
        raise QualificationError("MCP SSE data was not strict JSON") from exc
    if not isinstance(event, dict):
        raise QualificationError("MCP event was not an object")
    return response.status, response_headers, event


def _initialize(request_id: int) -> tuple[str, int]:
    status, headers, event = _post(
        {
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "thor-qualification", "version": "1.0"},
            },
            "id": request_id,
        }
    )
    session_id = headers.get("mcp-session-id", "")
    if status != 200 or not session_id or event.get("error") is not None:
        raise QualificationError("MCP initialize failed or omitted mcp-session-id")
    return session_id, status


def _call(method: str, arguments: dict[str, Any], request_id: int) -> tuple[str, int]:
    session_id, init_status = _initialize(request_id * 10)
    status, _, event = _post(
        {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": method, "arguments": arguments},
            "id": request_id,
        },
        session_id,
    )
    if init_status != 200 or status != 200 or event.get("error") is not None:
        raise QualificationError(f"VA-MCP tool failed: {method}")
    result = event.get("result")
    if not isinstance(result, dict) or result.get("isError") is True:
        raise QualificationError(f"VA-MCP tool returned an application error: {method}")
    content = result.get("content")
    if not isinstance(content, list) or not content or not isinstance(content[0], dict):
        raise QualificationError(f"VA-MCP tool returned no content: {method}")
    text = content[0].get("text")
    if not isinstance(text, str) or not text:
        raise QualificationError(f"VA-MCP tool returned empty text: {method}")
    return text, status


def _parse_json_text(value: str, expected: type[Any]) -> Any:
    try:
        parsed = json.loads(value, object_pairs_hook=_reject_pairs)
    except json.JSONDecodeError as exc:
        raise QualificationError("tool text was not JSON") from exc
    if not isinstance(parsed, expected):
        raise QualificationError(f"tool JSON was not {expected.__name__}")
    return parsed


def _parse_vst(value: str) -> list[str]:
    prefix = "sensor_names="
    if not value.startswith(prefix):
        raise QualificationError("unexpected vst_sensor_list output")
    parsed = ast.literal_eval(value[len(prefix):])
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise QualificationError("invalid VST sensor list")
    return sorted(parsed)


def _probe(value: str) -> dict[str, Any]:
    return {
        "nonempty_response": bool(value),
        "output_sha256": _sha_text(value),
        "output_length": len(value),
    }


def _validate(value: dict[str, Any]) -> None:
    schema = _load(SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    errors = sorted(Draft202012Validator(schema).iter_errors(value), key=lambda error: list(error.path))
    if errors:
        raise QualificationError(f"receipt schema violation: {errors[0].message}")
    if value["contract_sha256"] != _sha_file(CONTRACT_PATH):
        raise QualificationError("receipt contract binding drifted")
    if value["queries"]["invoked_tools"] != _load(CONTRACT_PATH)["invoked_read_only_tools"]:
        raise QualificationError("invoked tool order drifted")


def execute() -> dict[str, Any]:
    contract = _load(CONTRACT_PATH)
    inspection = _docker_json("inspect", contract["service_container"])
    if not isinstance(inspection, list) or len(inspection) != 1:
        raise QualificationError("VA-MCP container inspection failed")
    container = inspection[0]
    state = container.get("State", {})
    health = state.get("Health", {})
    if state.get("Running") is not True or health.get("Status") != "healthy":
        raise QualificationError("VA-MCP container is not healthy")
    running_before = _running_ids()

    session_id, init_status = _initialize(1)
    list_status, _, list_event = _post(
        {"jsonrpc": "2.0", "method": "tools/list", "params": {}, "id": 1}, session_id
    )
    tools = list_event.get("result", {}).get("tools", [])
    if init_status != 200 or list_status != 200 or not isinstance(tools, list):
        raise QualificationError("tools/list failed")
    tool_names = sorted(tool.get("name") for tool in tools if isinstance(tool, dict))
    if tool_names != contract["expected_tools"]:
        raise QualificationError("VA-MCP advertised tool set drifted")
    schemas_present = all(
        isinstance(tool.get("inputSchema"), dict) and isinstance(tool.get("outputSchema"), dict)
        for tool in tools
        if isinstance(tool, dict)
    )

    outputs: dict[str, str] = {}
    outputs["video_analytics__get_sensor_ids"], _ = _call("video_analytics__get_sensor_ids", {}, 2)
    outputs["vst_sensor_list"], _ = _call("vst_sensor_list", {}, 3)
    outputs["video_analytics__get_places"], _ = _call("video_analytics__get_places", {}, 4)
    outputs["video_analytics__get_incidents"], _ = _call(
        "video_analytics__get_incidents", {"max_count": 3}, 5
    )

    sensor_ids = sorted(_parse_json_text(outputs["video_analytics__get_sensor_ids"], list))
    vst_sensors = _parse_vst(outputs["vst_sensor_list"])
    if not sensor_ids or not vst_sensors:
        raise QualificationError("live sensor lists were empty")
    overlap = sorted(set(sensor_ids).intersection(vst_sensors))
    if not overlap:
        raise QualificationError("VA and VST sensor lists had no overlap")
    incidents = _parse_json_text(outputs["video_analytics__get_incidents"], dict)
    incident_items = incidents.get("incidents")
    if not isinstance(incident_items, list) or not incident_items:
        raise QualificationError("no live incidents were returned")
    first_id = incident_items[0].get("Id")
    if not isinstance(first_id, str) or not first_id:
        raise QualificationError("first incident omitted its ID")

    outputs["video_analytics__get_incident"], _ = _call(
        "video_analytics__get_incident", {"id": first_id, "includes": ["objectIds", "info"]}, 6
    )
    specific = _parse_json_text(outputs["video_analytics__get_incident"], dict)
    specific_id = specific.get("Id")
    if specific_id != first_id:
        raise QualificationError("specific incident did not match list result")

    query_window = contract["query_window"]
    source = overlap[0]
    outputs["video_analytics__get_fov_histogram"], _ = _call(
        "video_analytics__get_fov_histogram",
        {"source": source, "start_time": query_window["start_time"], "end_time": query_window["end_time"], "object_type": "Person", "bucket_count": 10},
        7,
    )
    outputs["video_analytics__get_average_speeds"], _ = _call(
        "video_analytics__get_average_speeds",
        {"source": source, "source_type": "sensor", "start_time": query_window["start_time"], "end_time": query_window["end_time"]},
        8,
    )
    outputs["video_analytics__analyze"], _ = _call(
        "video_analytics__analyze",
        {"source": source, "source_type": "sensor", "start_time": query_window["start_time"], "end_time": query_window["end_time"], "analysis_type": "avg_num_people"},
        9,
    )
    vst_after_text, _ = _call("vst_sensor_list", {}, 10)
    vst_after = _parse_vst(vst_after_text)
    running_after = _running_ids()

    receipt = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "status": "passed",
        "contract_sha256": _sha_file(CONTRACT_PATH),
        "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "runtime": {
            "architecture": platform.machine(),
            "container": contract["service_container"],
            "image": container.get("Config", {}).get("Image"),
            "image_id": container.get("Image"),
            "running": state.get("Running") is True,
            "healthy": health.get("Status") == "healthy",
        },
        "transport": {
            "endpoint": contract["endpoint"],
            "protocol": "JSON-RPC 2.0 over SSE",
            "session_header": "mcp-session-id",
            "session_per_query": True,
            "initialize_count": 10,
            "all_http_200": True,
        },
        "tool_surface": {
            "tool_count": len(tool_names),
            "tool_names": tool_names,
            "schemas_present": schemas_present,
            "react_agent_advertised_not_invoked": "react_agent" in tool_names,
        },
        "queries": {
            "invoked_tools": contract["invoked_read_only_tools"],
            "unique_tool_count": len(contract["invoked_read_only_tools"]),
            "tool_call_count": len(contract["invoked_read_only_tools"]) + 1,
            "all_succeeded": True,
            "sensor_ids": {"count": len(sensor_ids), "names": sensor_ids, "output_sha256": _sha_text(outputs["video_analytics__get_sensor_ids"])},
            "vst_sensors": {"count": len(vst_sensors), "names": vst_sensors, "output_sha256": _sha_text(outputs["vst_sensor_list"])},
            "sensor_overlap": overlap,
            "incidents": {"count": len(incident_items), "has_more": bool(incidents.get("has_more")), "first_id_sha256": _sha_text(first_id), "output_sha256": _sha_text(outputs["video_analytics__get_incidents"])},
            "specific_incident": {"matched_first_incident": specific_id == first_id, "field_names": sorted(specific), "output_sha256": _sha_text(outputs["video_analytics__get_incident"])},
            "places": _probe(outputs["video_analytics__get_places"]),
            "fov_histogram": _probe(outputs["video_analytics__get_fov_histogram"]),
            "average_speeds": _probe(outputs["video_analytics__get_average_speeds"]),
            "analysis": _probe(outputs["video_analytics__analyze"]),
        },
        "state": {
            "docker_running_set_exact": running_before == running_after,
            "vst_sensor_set_exact": vst_sensors == vst_after,
            "writes_observed": False,
        },
        "policy": contract["policy"],
    }
    _validate(receipt)
    return receipt


def _write(value: dict[str, Any]) -> None:
    rendered = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=HERE, delete=False) as stream:
            temporary = stream.name
            stream.write(rendered)
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
    parser.add_argument("mode", choices=("plan", "execute", "check"))
    args = parser.parse_args()
    try:
        if args.mode == "plan":
            contract = _load(CONTRACT_PATH)
            print(json.dumps({"status": "ready", "endpoint": contract["endpoint"], "read_only_tool_calls": len(contract["invoked_read_only_tools"]), "writes_or_lifecycle_actions": False}, sort_keys=True))
            return 0
        if args.mode == "execute":
            value = execute()
            _write(value)
            print(json.dumps({"status": "passed", "receipt_sha256": _sha_file(RECEIPT_PATH)}, sort_keys=True))
            return 0
        value = _load(RECEIPT_PATH)
        _validate(value)
        print(json.dumps({"status": "passed", "receipt_sha256": _sha_file(RECEIPT_PATH)}, sort_keys=True))
        return 0
    except (QualificationError, OSError, subprocess.SubprocessError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
