#!/usr/bin/env python3
"""Candidate-only static executor for seven VIOS UI literals and NAT generate/chat."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
from typing import Any, Callable

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4]
INVENTORY_PATH = HERE / "inventory.json"
INVENTORY_SCHEMA_PATH = HERE / "inventory.schema.json"
RESULT_SCHEMA_PATH = HERE / "result.schema.json"
MAX_SOURCE_BYTES = 5_000_000

EXPECTED_INVENTORY_SHA256 = (
    "dbc1045b5d9e6b02ab152f2f0cc9007c0087e265692ef4e4aa911dc12f7935e3"
)
EXPECTED_SOURCE_PLAN = {
    "path": "deploy/docker/thor-local/qualification/advertised-entry-gaps/plan.json",
    "raw_sha256": "dd3c8cbbcae859137e73da4a8d4d9227f535dd674979b5d9e8f5cf25b885d122",
    "plan_payload_sha256": "97cb92ffb83d05388759f7428324344f91ec294116e5d24721c1ba21d994ab7d",
}
EXPECTED_SOURCE_MANIFEST = {
    "path": "deploy/docker/thor-local/parity/manifest.json",
    "raw_sha256": "6b041fbd169649b6dac5e68908e4a6dd219da9160cf72594219058885a9b9127",
}
EXPECTED_PREDECESSORS = [
    {
        "path": "deploy/docker/thor-local/qualification/advertised-entry-executors/inventory.json",
        "raw_sha256": "91406a15ff1340b9b4dba988507470234971fa4905997bc52e64fb983fc12a18",
    },
    {
        "path": "deploy/docker/thor-local/qualification/advertised-entry-executors-wave2/inventory.json",
        "raw_sha256": "2c14f8ae5ade22ccbc556a844b4fcb63661048826660073fb21c5f882047c5d2",
    },
    {
        "path": "deploy/docker/thor-local/qualification/advertised-entry-executors-wave3/inventory.json",
        "raw_sha256": "0b7056eafce7686fc2b7315fef8ae491ddef03d2e52f41e7c7861247933f90ab",
    },
    {
        "path": "deploy/docker/thor-local/qualification/advertised-entry-executors-wave4/inventory.json",
        "raw_sha256": "1de6e9be3c93c349e45b192506e3081758553582dda6f73b79877bc4ff5155a6",
    },
    {
        "path": "deploy/docker/thor-local/qualification/advertised-entry-executors-wave5/inventory.json",
        "raw_sha256": "98876a18d628df644171cd1d0051753dadd904cca67a5fe0fa8696832cb08771",
    },
]
EXPECTED_POLICY = {
    "candidate_only": True,
    "can_mark_passed_current": False,
    "live_acceptance_mutation_allowed": False,
    "live_oracle_mutation_allowed": False,
    "runtime_evidence": [],
    "browser_allowed": False,
    "network_allowed": False,
    "docker_allowed": False,
    "subprocess_allowed": False,
    "lifecycle_allowed": False,
    "downloads_allowed": False,
    "credentials_allowed": False,
    "file_writes_allowed": False,
}
EXPECTED_DENOMINATOR = {
    "advertised_gap_entries": 87,
    "previously_selected_candidate_entries": 63,
    "prior_open_entries": 24,
    "selected_candidate_entries": 8,
    "entries_left_open": 16,
}

ROUTES = "services/vios/ui/vios-ui/src/layout/routes/Routes.tsx"
NAV = "services/vios/ui/vios-ui/src/layout/nav/ListItems.tsx"
DASHBOARD = "services/vios/ui/vios-ui/src/pages/vst/VSTDashboard.tsx"
SENSOR_MANAGEMENT = "services/vios/ui/vios-ui/src/pages/vst/SensorManagement.tsx"
STREAM_DETAILS = "services/vios/ui/vios-ui/src/pages/vst/StreamDetails.tsx"
SENSOR_RECORDING = "services/vios/ui/vios-ui/src/pages/vst/SensorRecording.tsx"
MEDIA_MANAGEMENT = "services/vios/ui/vios-ui/src/pages/vst/MediaManagement.tsx"
MEDIA_UPLOAD = "services/vios/ui/vios-ui/src/pages/nvstreamer/MediaUpload.tsx"
LIVE_STREAM = "services/vios/ui/vios-ui/src/pages/vst/LiveStream.tsx"
REPLAY_STREAM = "services/vios/ui/vios-ui/src/pages/vst/ReplayStream.tsx"
VIDEO_WALL = "services/vios/ui/vios-ui/src/pages/vst/VideoWall.tsx"
EXPERIMENTAL = "services/vios/ui/vios-ui/src/pages/common/Experimental.tsx"
SYSTEM_STATS = (
    "services/vios/ui/vios-ui/src/pages/common/experimentalPages/SystemStats.tsx"
)
STREAM_STATS = (
    "services/vios/ui/vios-ui/src/pages/common/experimentalPages/StreamStats.tsx"
)
RTSP_QOS = (
    "services/vios/ui/vios-ui/src/pages/common/experimentalPages/RTSPStreamQOS.tsx"
)
DEBUG_OPTIONS = "services/vios/ui/vios-ui/src/components/debugOptions/DebugOptions.tsx"
STREAM_AUTOMATION = (
    "services/vios/ui/vios-ui/src/pages/common/experimentalPages/StreamAutomation.tsx"
)
AGENT_EXPECTED = "deploy/docker/thor-local/qualification/expected/agent.json"
AGENT_WORKER = "services/agent/src/vss_agents/api/custom_fastapi_worker.py"
AGENT_PROJECT = "services/agent/pyproject.toml"
AGENT_LOCK = "services/agent/uv.lock"

EXPECTED_CASE_BINDINGS = {
    "manifest-gap.vios-ui.00-vios-dashboard": (
        "/features/22/advertised/0",
        "vios_dashboard_source_contract",
        {ROUTES, NAV, DASHBOARD},
    ),
    "manifest-gap.vios-ui.01-sensor-and-stream-management": (
        "/features/22/advertised/1",
        "sensor_stream_management_source_contract",
        {ROUTES, NAV, SENSOR_MANAGEMENT, STREAM_DETAILS},
    ),
    "manifest-gap.vios-ui.02-recording-schedules": (
        "/features/22/advertised/2",
        "recording_schedules_source_contract",
        {ROUTES, NAV, SENSOR_RECORDING},
    ),
    "manifest-gap.vios-ui.03-media-management-upload": (
        "/features/22/advertised/3",
        "media_management_upload_source_contract",
        {ROUTES, NAV, MEDIA_MANAGEMENT, MEDIA_UPLOAD},
    ),
    "manifest-gap.vios-ui.04-live-replay-video-wall": (
        "/features/22/advertised/4",
        "live_replay_video_wall_source_contract",
        {ROUTES, NAV, LIVE_STREAM, REPLAY_STREAM, VIDEO_WALL},
    ),
    "manifest-gap.vios-ui.05-qos-system-stream-stats": (
        "/features/22/advertised/5",
        "qos_system_stream_stats_source_contract",
        {ROUTES, EXPERIMENTAL, SYSTEM_STATS, STREAM_STATS, RTSP_QOS},
    ),
    "manifest-gap.vios-ui.06-debug-and-playback-automation": (
        "/features/22/advertised/6",
        "debug_playback_automation_source_contract",
        {ROUTES, EXPERIMENTAL, DEBUG_OPTIONS, STREAM_AUTOMATION},
    ),
    "manifest-gap.agent-and-mcp-apis.00-nat-generate-chat": (
        "/features/27/advertised/0",
        "nat_generate_chat_source_contract",
        {AGENT_EXPECTED, AGENT_WORKER, AGENT_PROJECT, AGENT_LOCK},
    ),
}


class QualificationError(RuntimeError):
    """A digest, schema, denominator, boundary, or source assertion failed."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def _strict_json_bytes(data: bytes, label: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise QualificationError(f"duplicate JSON key in {label}: {key!r}")
            value[key] = item
        return value

    try:
        return json.loads(data, object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"invalid JSON in {label}") from exc


def _safe_repo_path(relative_path: str) -> Path:
    pure = PurePosixPath(relative_path)
    if pure.is_absolute() or not pure.parts or ".." in pure.parts:
        raise QualificationError(f"unsafe repository path: {relative_path}")
    path = REPO_ROOT.joinpath(*pure.parts)
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise QualificationError(
            f"repository input is unavailable: {relative_path}"
        ) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise QualificationError(
            f"repository input must be a regular non-symlink: {relative_path}"
        )
    resolved = path.resolve()
    if resolved != REPO_ROOT and REPO_ROOT not in resolved.parents:
        raise QualificationError(f"repository input escaped root: {relative_path}")
    return path


def _read_bytes(relative_path: str, *, max_bytes: int = MAX_SOURCE_BYTES) -> bytes:
    path = _safe_repo_path(relative_path)
    if path.stat().st_size > max_bytes:
        raise QualificationError(
            f"repository input exceeds {max_bytes} bytes: {relative_path}"
        )
    data = path.read_bytes()
    if len(data) > max_bytes:
        raise QualificationError(
            f"repository input exceeds {max_bytes} bytes: {relative_path}"
        )
    return data


def _validate_schema(instance: Any, schema_path: Path, label: str) -> None:
    schema = _strict_json_bytes(schema_path.read_bytes(), schema_path.name)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise QualificationError(f"invalid JSON schema: {schema_path.name}") from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(instance),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        first = errors[0]
        where = "/" + "/".join(str(item) for item in first.absolute_path)
        raise QualificationError(
            f"{label} schema validation failed at {where}: {first.message}"
        )


def _resolve_pointer(document: Any, pointer: str) -> Any:
    value = document
    for token in pointer.split("/")[1:]:
        token = token.replace("~1", "/").replace("~0", "~")
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


def _verify_sha(path: str, expected: str, label: str) -> bytes:
    raw = _read_bytes(path)
    actual = _sha256(raw)
    if actual != expected:
        raise QualificationError(f"{label} mismatch for {path}: {actual} != {expected}")
    return raw


def _assert_fragments(path: str, fragments: tuple[str, ...]) -> list[str]:
    text = _read_bytes(path).decode("utf-8", errors="strict")
    missing = [fragment for fragment in fragments if fragment not in text]
    if missing:
        raise QualificationError(
            f"semantic source fragment missing in {path}: {missing}"
        )
    return [f"fragment:{path}:{_sha256(fragment.encode())}" for fragment in fragments]


def _assert_absent(path: str, fragments: tuple[str, ...]) -> list[str]:
    text = _read_bytes(path).decode("utf-8", errors="strict")
    present = [fragment for fragment in fragments if fragment in text]
    if present:
        raise QualificationError(f"unexpected source fragment in {path}: {present}")
    return [f"absent:{path}:{_sha256(fragment.encode())}" for fragment in fragments]


def _dashboard() -> tuple[list[str], list[str], dict[str, Any], str]:
    assertions = _assert_fragments(
        ROUTES,
        ("import VSTDashboard", "{ path: 'dashboard', element: <VSTDashboard /> }"),
    )
    assertions += _assert_fragments(
        NAV, ("<NavLink to='/dashboard'", "<ListItemText primary='Dashboard' />")
    )
    assertions += _assert_fragments(
        DASHBOARD,
        (
            "updateSensorsAndStreams();",
            "<TotalSensorsWidget />",
            "<SensorInformationTable />",
            "<TimelinesGapTable />",
        ),
    )
    return (
        assertions,
        [
            "default VIOS route -> VSTDashboard component",
            "dashboard effect -> sensor/stream refresh and status widgets",
        ],
        {"mounted_route": "/dashboard", "browser_render": False},
        "mounted_source_route",
    )


def _sensor_stream_management() -> tuple[list[str], list[str], dict[str, Any], str]:
    assertions = _assert_fragments(
        ROUTES,
        (
            "{ path: 'sensor-management', element: <SensorManagement /> }",
            "{ path: 'stream-details', element: <StreamDetails /> }",
        ),
    )
    assertions += _assert_fragments(
        NAV,
        (
            "<ListItemText primary='Sensor Management' />",
            "<ListItemText primary='Stream Details' />",
        ),
    )
    assertions += _assert_fragments(
        SENSOR_MANAGEMENT,
        ("<SensorRebootCard />", "<SensorScanCard />", "<AddNewSensorCard />"),
    )
    assertions += _assert_fragments(
        STREAM_DETAILS, ("<h1>Stream Details</h1>", "<RTSPTable />")
    )
    return (
        assertions,
        [
            "default VIOS routes -> sensor-management and stream-details components",
            "sensor action cards plus RTSP table -> static management composition",
        ],
        {
            "mounted_routes": ["/sensor-management", "/stream-details"],
            "api_execution": False,
        },
        "mounted_source_route",
    )


def _recording_schedules() -> tuple[list[str], list[str], dict[str, Any], str]:
    assertions = _assert_fragments(
        ROUTES, ("{ path: 'record-settings', element: <SensorRecording /> }",)
    )
    assertions += _assert_fragments(
        NAV, ("<ListItemText primary='Record Settings' />",)
    )
    assertions += _assert_fragments(
        SENSOR_RECORDING,
        (
            "/api/v1/record/${selectedSensor?.sensorId}/schedule",
            "/api/v1/record/${selectedSensor?.sensorId}/status",
            "<RecordingScheduleCard",
            "<RecordingScheduleTable",
        ),
    )
    return (
        assertions,
        [
            "record-settings route -> SensorRecording component",
            "selected sensor -> schedule/status API call declarations and schedule controls",
        ],
        {"mounted_route": "/record-settings", "recording_mutation": False},
        "mounted_source_route",
    )


def _media_management_upload() -> tuple[list[str], list[str], dict[str, Any], str]:
    assertions = _assert_fragments(
        ROUTES, ("{ path: 'media-management', element: <VSTMediaManagement /> }",)
    )
    assertions += _assert_fragments(
        NAV, ("<ListItemText primary='Media Management' />",)
    )
    assertions += _assert_fragments(
        MEDIA_MANAGEMENT,
        ("<SensorVideoDownloadCard />", "<SensorVideoDelete />", "<MediaUpload />"),
    )
    assertions += _assert_fragments(
        MEDIA_UPLOAD,
        (
            "const fd = new FormData();",
            "fd.append('mediaFile', file);",
            "${config.storageManagementEndpoint}/api/v1/storage/file",
            "enableChunkUpload",
        ),
    )
    return (
        assertions,
        [
            "media-management route -> download/delete/upload composition",
            "MediaUpload source -> multipart whole-file and chunk-capable request declaration",
        ],
        {"mounted_route": "/media-management", "file_upload_executed": False},
        "mounted_source_route",
    )


def _live_replay_wall() -> tuple[list[str], list[str], dict[str, Any], str]:
    assertions = _assert_fragments(
        ROUTES,
        (
            "{ path: 'live-streams', element: <></> }",
            "{ path: 'recorded-streams', element: <></> }",
            "{ path: 'video-wall', element: <></> }",
        ),
    )
    assertions += _assert_absent(
        ROUTES, ("import LiveStream", "import ReplayStream", "import VideoWall")
    )
    assertions += _assert_fragments(
        NAV,
        (
            "<ListItemText primary='Live Streams' />",
            "<ListItemText primary='Recorded Streams' />",
            "<ListItemText primary='Video Wall' />",
        ),
    )
    assertions += _assert_fragments(
        LIVE_STREAM, ("<h1>Live Streaming</h1>", "streamType={StreamType.Live}")
    )
    assertions += _assert_fragments(
        REPLAY_STREAM,
        ("<h1>Replay Streaming</h1>", "streamType={StreamType.Replay}"),
    )
    assertions += _assert_fragments(
        VIDEO_WALL, ("<h1>Video Wall</h1>", "onClick={handleStartStream}")
    )
    return (
        assertions,
        [
            "navigation labels -> live/replay/video-wall paths",
            "page component sources -> Live, Replay, and Video Wall declarations",
            "route table -> explicit empty placeholders, not mounted components",
        ],
        {
            "placeholder_routes": [
                "/live-streams",
                "/recorded-streams",
                "/video-wall",
            ],
            "page_components_mounted": False,
        },
        "placeholder_source_route",
    )


def _stats() -> tuple[list[str], list[str], dict[str, Any], str]:
    assertions = _assert_fragments(
        ROUTES, ("{ path: 'experimental', element: <></> }",)
    )
    assertions += _assert_absent(ROUTES, ("import Experimental",))
    assertions += _assert_fragments(
        EXPERIMENTAL,
        (
            "{ label: 'Stream Stats', content: <StreamStats /> }",
            "{ label: 'System Stats', content: <SystemStats /> }",
            "{ label: 'RTSP Stream QOS', content: <RTSPStreamQOS /> }",
        ),
    )
    assertions += _assert_fragments(
        SYSTEM_STATS,
        (
            "/api/v1/sensor/debug/system/stats",
            "const interval = setInterval(fetchData, 5000);",
        ),
    )
    assertions += _assert_fragments(
        STREAM_STATS,
        ("RTCStatsReport", "stat.type === 'inbound-rtp'", "stat.framesPerSecond"),
    )
    assertions += _assert_fragments(
        RTSP_QOS,
        (
            "/api/v1/proxy/debug/qos",
            "const interval = setInterval(fetchQoSData, 1000);",
        ),
    )
    return (
        assertions,
        [
            "Experimental tab source -> QoS/system/stream statistics components",
            "statistics components -> REST/WebRTC polling declarations",
            "route table -> explicit Experimental placeholder, not mounted component",
        ],
        {"placeholder_route": "/experimental", "polling_executed": False},
        "placeholder_source_route",
    )


def _debug_playback() -> tuple[list[str], list[str], dict[str, Any], str]:
    assertions = _assert_fragments(
        ROUTES, ("{ path: 'experimental', element: <></> }",)
    )
    assertions += _assert_absent(ROUTES, ("import Experimental",))
    assertions += _assert_fragments(
        EXPERIMENTAL,
        (
            "{ label: 'Debug Options', content: <DebugOptions /> }",
            "label: 'Playback Automation'",
            "content: <StreamAutomation />",
        ),
    )
    assertions += _assert_fragments(
        DEBUG_OPTIONS,
        ("<TimestampLogging />", "<PlugUnplugSensor />", "<AddNvStreamerStreams />"),
    )
    assertions += _assert_fragments(
        STREAM_AUTOMATION,
        (
            "streamManagerRef.current.startStreaming(streamConfig);",
            "streamTypes.push(StreamType.Live)",
            "streamTypes.push(StreamType.Replay)",
            "window.setInterval(handleAutomation, interval * 1000)",
        ),
    )
    return (
        assertions,
        [
            "Experimental tab source -> DebugOptions and StreamAutomation components",
            "StreamAutomation source -> live/replay iteration declarations",
            "route table -> explicit Experimental placeholder, not mounted component",
        ],
        {"placeholder_route": "/experimental", "playback_executed": False},
        "placeholder_source_route",
    )


def _nat_generate_chat() -> tuple[list[str], list[str], dict[str, Any], str]:
    assertions = _assert_fragments(
        AGENT_WORKER,
        (
            "class CustomFastApiFrontEndWorker(FastApiFrontEndPluginWorker):",
            "await super().add_routes(app, builder)",
        ),
    )
    assertions += _assert_fragments(
        AGENT_PROJECT,
        (
            '"nvidia-nat[async-endpoints,langchain,mcp,opentelemetry,phoenix,profiler,s3]==1.6.0"',
        ),
    )
    assertions += _assert_fragments(
        AGENT_LOCK,
        (
            'name = "nvidia-nat"',
            'specifier = "==1.6.0"',
            "sha256:f1235ba563f537a535a2c98b2000a5d265c4acfdc4647004af442c9efcf552d8",
        ),
    )
    document = _strict_json_bytes(_read_bytes(AGENT_EXPECTED), AGENT_EXPECTED)
    operations = document.get("operations")
    if (
        document.get("surface") != "agent"
        or document.get("declared_operation_count") != 44
        or not isinstance(operations, list)
        or len(operations) != 44
    ):
        raise QualificationError("static agent API inventory identity drifted")
    actual = {
        (item.get("method"), item.get("path"))
        for item in operations
        if isinstance(item, dict)
    }
    required = {
        ("POST", "/generate"),
        ("POST", "/generate/full"),
        ("POST", "/generate/stream"),
        ("POST", "/chat"),
        ("POST", "/chat/stream"),
        ("POST", "/v1/chat"),
        ("POST", "/v1/chat/completions"),
        ("POST", "/v1/chat/stream"),
    }
    if not required.issubset(actual):
        raise QualificationError("NAT generate/chat static operation inventory drifted")
    assertions += [
        f"agent-operation:{method}:{path}" for method, path in sorted(required)
    ]
    return (
        assertions,
        [
            "exact NAT 1.6.0 lock -> inherited FastAPI front-end implementation",
            "CustomFastApiFrontEndWorker super route registration -> static generate/chat inventory",
        ],
        {
            "nat_version": "1.6.0",
            "static_operation_count": len(required),
            "operations": sorted(f"{method} {path}" for method, path in required),
        },
        "inherited_nat_static_inventory",
    )


AdapterResult = tuple[list[str], list[str], dict[str, Any], str]
ADAPTERS: dict[str, Callable[[], AdapterResult]] = {
    "vios_dashboard_source_contract": _dashboard,
    "sensor_stream_management_source_contract": _sensor_stream_management,
    "recording_schedules_source_contract": _recording_schedules,
    "media_management_upload_source_contract": _media_management_upload,
    "live_replay_video_wall_source_contract": _live_replay_wall,
    "qos_system_stream_stats_source_contract": _stats,
    "debug_playback_automation_source_contract": _debug_playback,
    "nat_generate_chat_source_contract": _nat_generate_chat,
}


def _load_inventory() -> tuple[dict[str, Any], bytes]:
    raw = INVENTORY_PATH.read_bytes()
    if _sha256(raw) != EXPECTED_INVENTORY_SHA256:
        raise QualificationError("wave-six inventory identity drifted")
    inventory = _strict_json_bytes(raw, INVENTORY_PATH.name)
    _validate_schema(inventory, INVENTORY_SCHEMA_PATH, "inventory")
    if inventory.get("source_plan") != EXPECTED_SOURCE_PLAN:
        raise QualificationError("source plan lock drifted")
    if inventory.get("source_manifest") != EXPECTED_SOURCE_MANIFEST:
        raise QualificationError("source manifest lock drifted")
    if inventory.get("previous_candidate_inventories") != EXPECTED_PREDECESSORS:
        raise QualificationError("predecessor inventory chain drifted")
    if inventory.get("policy") != EXPECTED_POLICY:
        raise QualificationError("candidate-only policy drifted")
    if inventory.get("denominator") != EXPECTED_DENOMINATOR:
        raise QualificationError("87/63/24/8/16 denominator drifted")

    plan_raw = _verify_sha(
        EXPECTED_SOURCE_PLAN["path"],
        EXPECTED_SOURCE_PLAN["raw_sha256"],
        "gap plan lock",
    )
    plan = _strict_json_bytes(plan_raw, EXPECTED_SOURCE_PLAN["path"])
    if (
        plan.get("plan_payload_sha256") != EXPECTED_SOURCE_PLAN["plan_payload_sha256"]
        or len(plan.get("entries", [])) != 87
    ):
        raise QualificationError("87-entry gap plan identity drifted")
    manifest = _strict_json_bytes(
        _verify_sha(
            EXPECTED_SOURCE_MANIFEST["path"],
            EXPECTED_SOURCE_MANIFEST["raw_sha256"],
            "manifest lock",
        ),
        EXPECTED_SOURCE_MANIFEST["path"],
    )

    predecessor_ids: set[str] = set()
    for spec in EXPECTED_PREDECESSORS:
        previous = _strict_json_bytes(
            _verify_sha(spec["path"], spec["raw_sha256"], "predecessor lock"),
            spec["path"],
        )
        ids = {case["entry_id"] for case in previous.get("cases", [])}
        if ids & predecessor_ids:
            raise QualificationError("predecessor inventories overlap")
        predecessor_ids.update(ids)
    if len(predecessor_ids) != 63:
        raise QualificationError(
            f"predecessor union must contain 63 IDs, found {len(predecessor_ids)}"
        )

    cases = inventory.get("cases", [])
    case_ids = {case["entry_id"] for case in cases}
    if len(cases) != 8 or len(case_ids) != 8 or case_ids != set(EXPECTED_CASE_BINDINGS):
        raise QualificationError(
            "inventory must contain eight exact unique wave-six cases"
        )
    if predecessor_ids & case_ids:
        raise QualificationError("wave-six cases overlap predecessor inventories")
    if 87 - len(predecessor_ids | case_ids) != 16:
        raise QualificationError("wave-six open-entry arithmetic drifted")

    plan_by_pointer = {entry["manifest_pointer"]: entry for entry in plan["entries"]}
    for case in cases:
        pointer, adapter_id, sources = EXPECTED_CASE_BINDINGS[case["entry_id"]]
        if case["manifest_pointer"] != pointer or case["adapter_id"] != adapter_id:
            raise QualificationError(f"case binding drifted: {case['entry_id']}")
        if {lock["path"] for lock in case["source_locks"]} != sources:
            raise QualificationError(f"case source set drifted: {case['entry_id']}")
        gap = plan_by_pointer.get(pointer)
        if gap is None:
            raise QualificationError(f"case pointer absent from gap plan: {pointer}")
        expected_fields = {
            "entry_id": gap["entry_id"],
            "proposed_capability_id": gap["proposed_capability"]["id"],
            "advertised": gap["advertised"],
            "advertised_utf8_sha256": gap["advertised_utf8_sha256"],
            "advertised_canonical_sha256": gap["advertised_canonical_sha256"],
        }
        for field, expected in expected_fields.items():
            if case.get(field) != expected:
                raise QualificationError(f"{pointer} differs from gap plan at {field}")
        oracle = gap.get("required_oracle", {})
        expected_oracle = (
            ("runtime_browser_interaction", "bounded_vios_ui_browser_workflow")
            if pointer.startswith("/features/22/")
            else ("runtime_api_or_mcp_operation", "bounded_agent_mcp_operation_probe")
        )
        if (
            (oracle.get("type"), oracle.get("executor_class")) != expected_oracle
            or oracle.get("status") != "open_unexecuted"
            or oracle.get("runtime_evidence") != []
        ):
            raise QualificationError(f"{pointer} runtime oracle boundary drifted")
        if _resolve_pointer(manifest, pointer) != case["advertised"]:
            raise QualificationError(f"{pointer} differs from manifest literal")
        for lock in case["source_locks"]:
            _verify_sha(lock["path"], lock["sha256"], "source lock")
    return inventory, raw


def execute(selected: list[str] | None = None) -> dict[str, Any]:
    inventory, inventory_raw = _load_inventory()
    cases = inventory["cases"]
    by_id = {case["entry_id"]: case for case in cases}
    selected_ids = selected or [case["entry_id"] for case in cases]
    if len(selected_ids) != len(set(selected_ids)):
        raise QualificationError("duplicate --case selection")
    unknown = sorted(set(selected_ids) - set(by_id))
    if unknown:
        raise QualificationError(f"unknown --case selection: {unknown}")

    results: list[dict[str, Any]] = []
    for entry_id in selected_ids:
        case = by_id[entry_id]
        assertions, edges, detail, route_state = ADAPTERS[case["adapter_id"]]()
        source_paths = sorted(lock["path"] for lock in case["source_locks"])
        semantic_output = {
            "contract_scope": "exact-digest-locked-ui-and-nat-static-source-contract-only",
            "contract_edges": edges,
            "semantic_assertions": assertions,
            "matched_source_files": source_paths,
            "route_state": route_state,
            "browser_executed": False,
            "api_executed": False,
            "service_executed": False,
            "ui_render_proven": False,
            "backend_state_correlated": False,
            "request_response_proven": False,
            "service_readiness_proven": False,
            "real_file_writes": 0,
            "detail": detail,
        }
        input_payload = {
            "case": case,
            "locked_source_digests": [lock["sha256"] for lock in case["source_locks"]],
        }
        results.append(
            {
                "manifest_pointer": case["manifest_pointer"],
                "entry_id": case["entry_id"],
                "proposed_capability_id": case["proposed_capability_id"],
                "advertised": case["advertised"],
                "evidence_scope": case["evidence_scope"],
                "observation": "observed_static_source_contract",
                "input_sha256": _sha256(_canonical_bytes(input_payload)),
                "semantic_output_sha256": _sha256(_canonical_bytes(semantic_output)),
                "semantic_output": semantic_output,
                "runtime_evidence": [],
                "official_capability_effect": "none_candidate_only",
            }
        )

    result = {
        "schema_version": 1,
        "mode": inventory["mode"],
        "candidate_only": True,
        "inventory_sha256": _sha256(inventory_raw),
        "denominator": inventory["denominator"],
        "runtime_evidence": [],
        "official_capability_effect": "none_candidate_only",
        "results": results,
    }
    _validate_schema(result, RESULT_SCHEMA_PATH, "result")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", action="append", dest="cases")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args(argv)
    try:
        inventory, _ = _load_inventory()
        if args.list:
            if args.cases:
                raise QualificationError("--list cannot be combined with --case")
            for case in inventory["cases"]:
                print(case["entry_id"])
            return 0
        print(json.dumps(execute(args.cases), sort_keys=True, indent=2))
    except QualificationError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
