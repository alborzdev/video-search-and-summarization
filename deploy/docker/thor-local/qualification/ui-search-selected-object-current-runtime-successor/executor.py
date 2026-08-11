#!/usr/bin/env python3
"""Bounded current-runtime UI Search-by-Image qualification for Thor.

The default command is inert.  The authorized command creates two otherwise
absent fixed video-file indices, writes three tiny owned documents, drives the
real VSS UI with an isolated Chromium process, and then deletes only the exact
owned resources after UUID and document-inventory checks.  Retained evidence
contains hashes and semantic facts, never prompts, vectors, URLs, or runtime
object identifiers.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any, Mapping, Sequence
from urllib.parse import urlencode

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4].resolve(strict=True)
CONTRACT_PATH = HERE / "contract.json"
HARNESS_PATH = HERE / "harness.mjs"
SCHEMA_PATH = HERE / "receipt.schema.json"
RECEIPT_PATH = HERE / "runtime-receipt.json"
BACKEND_HERE = HERE.parent / "search-semantic-current-runtime-successor"
BACKEND_EXECUTOR = BACKEND_HERE / "executor.py"
BACKEND_VERIFIER = BACKEND_HERE / "verify.py"

PACKAGE_ID = "thor-ui-search-selected-object-current-runtime-successor-v1"
AUTHORIZATION_ID = "ui-search-selected-object-current-runtime"
ACK = "I_ACK_UI_SEARCH_SELECTED_OBJECT_CURRENT_RUNTIME_AND_EXACT_INDEX_CLEANUP"
BEHAVIOR_INDEX = "mdx-behavior-2025-01-01"
RAW_INDEX = "mdx-raw-2025-01-01"
EMBED_INDEX = "mdx-embed-filtered-2025-01-01"
SEARCH_TEXT = "race car in a pit lane"
UI_ORIGIN = "http://127.0.0.1:3001"
SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
COMMIT_RE = re.compile(r"[0-9a-f]{40}\Z")
PLAIN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
MAX_FILE_BYTES = 32 * 1024 * 1024


def _load_backend() -> Any:
    spec = importlib.util.spec_from_file_location("thor_search_backend_executor", BACKEND_EXECUTOR)
    if spec is None or spec.loader is None:
        raise RuntimeError("backend_import_failed")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


B = _load_backend()
QualificationError = B.QualificationError


def _progress(stage: str) -> None:
    allowed = {
        "admission-passed",
        "backend-evidence-passed",
        "fixture-resolved",
        "embedding-passed",
        "owned-indices-created",
        "owned-documents-indexed",
        "frames-api-passed",
        "browser-started",
        "browser-passed",
        "cleanup-started",
        "cleanup-indices-processed",
        "cleanup-absence-passed",
        "cleanup-embed-passed",
        "cleanup-frames-passed",
        "cleanup-passed",
    }
    if stage not in allowed:
        raise QualificationError("configuration_error")
    print(f"[ui-search-selected-object] {stage}", file=sys.stderr, flush=True)


def _failure(scope: str, code: str) -> None:
    if scope not in {"runtime", "cleanup"} or code not in QualificationError.CODES:
        raise QualificationError("configuration_error")
    print(f"[ui-search-selected-object] {scope}-failure={code}", file=sys.stderr, flush=True)


def _contract() -> dict[str, Any]:
    contract = B._load_object(CONTRACT_PATH)
    expected = {
        "schema_version": 1,
        "package_id": PACKAGE_ID,
        "capability_id": "runtime.ui.search-tab",
        "supporting_capability_id": "runtime.agent.search-profile",
        "oracle_id": "oracle.runtime.ui.search-tab",
        "mode": "authorization-gated-owned-index-isolated-playwright-numeric-loopback-runtime",
        "default_execution_enabled": False,
    }
    if any(contract.get(key) != value for key, value in expected.items()):
        raise QualificationError("configuration_error")
    if contract.get("authorization", {}).get("acknowledgement") != ACK:
        raise QualificationError("configuration_error")
    indices = contract.get("indices", {})
    if indices != {
        "behavior_owned": BEHAVIOR_INDEX,
        "raw_owned": RAW_INDEX,
        "embed_read_only": EMBED_INDEX,
        "vector_dimensions": 1152,
    }:
        raise QualificationError("configuration_error")
    if contract.get("fixture", {}).get("query_contract") != {
        "sha256": B._sha(SEARCH_TEXT.encode("utf-8")),
        "bytes": len(SEARCH_TEXT.encode("utf-8")),
    }:
        raise QualificationError("configuration_error")
    if not COMMIT_RE.fullmatch(str(contract.get("target_commit", ""))):
        raise QualificationError("configuration_error")
    if not isinstance(contract.get("runtime"), dict) or len(contract["runtime"]) != 7:
        raise QualificationError("configuration_error")
    return contract


def _validate_absolute_regular(path_text: Any, expected: Any) -> Path:
    if not isinstance(path_text, str) or not path_text.startswith("/"):
        raise QualificationError("configuration_error")
    if not isinstance(expected, str) or not SHA_RE.fullmatch(expected):
        raise QualificationError("configuration_error")
    path = Path(path_text)
    try:
        resolved = path.resolve(strict=True)
        mode = resolved.stat().st_mode
    except OSError as exc:
        raise QualificationError("configuration_error") from exc
    if not stat.S_ISREG(mode) or _sha_file(resolved) != expected:
        raise QualificationError("configuration_error")
    return path


def _sha_file(path: Path, maximum: int = 512 * 1024 * 1024) -> str:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise QualificationError("configuration_error") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size < 1 or before.st_size > maximum:
            raise QualificationError("configuration_error")
        digest = hashlib.sha256()
        total = 0
        while total < before.st_size:
            chunk = os.read(descriptor, min(1024 * 1024, before.st_size - total))
            if not chunk:
                break
            digest.update(chunk)
            total += len(chunk)
        after = os.fstat(descriptor)
        stable = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
        if total != before.st_size or any(getattr(before, key) != getattr(after, key) for key in stable):
            raise QualificationError("configuration_error")
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def _validate_browser(contract: Mapping[str, Any]) -> dict[str, Path]:
    browser = contract.get("browser")
    if not isinstance(browser, dict):
        raise QualificationError("configuration_error")
    paths = {
        "node": _validate_absolute_regular(browser.get("node_path"), browser.get("node_sha256")),
        "playwright": _validate_absolute_regular(
            browser.get("playwright_entry_path"), browser.get("playwright_entry_sha256")
        ),
        "executable": _validate_absolute_regular(
            browser.get("browser_executable_path"), browser.get("browser_executable_sha256")
        ),
    }
    if browser.get("ui_origin_sha256") != B._sha(UI_ORIGIN.encode("utf-8")):
        raise QualificationError("configuration_error")
    return paths


def _runtime_snapshot(contract: Mapping[str, Any]) -> dict[str, Any]:
    runtime = contract.get("runtime")
    if not isinstance(runtime, dict) or len(runtime) != 7:
        raise QualificationError("configuration_error")
    template = "{{.Name}}|{{.Config.Image}}|{{.Image}}|{{.State.Running}}|{{.RestartCount}}|{{.State.OOMKilled}}|{{.State.StartedAt}}"
    snapshot: dict[str, Any] = {}
    for expected in runtime.values():
        if not isinstance(expected, dict):
            raise QualificationError("configuration_error")
        container = expected.get("container")
        if not isinstance(container, str) or not B.PLAIN_RE.fullmatch(container):
            raise QualificationError("configuration_error")
        raw = B._run(
            ["docker", "inspect", "--format", template, container], timeout=10, maximum=4096
        ).decode("utf-8").strip()
        parts = raw.split("|")
        if len(parts) != 7:
            raise QualificationError("runtime_identity_error")
        name, configured_image, image_id, running, restart_text, oom_killed, started_at = parts
        try:
            restart_count = int(restart_text)
        except ValueError as exc:
            raise QualificationError("runtime_identity_error") from exc
        row = {
            "configured_image": configured_image,
            "image_id": image_id,
            "running": running == "true",
            "restart_count": restart_count,
            "oom_killed": oom_killed == "true",
            "started_at_sha256": B._sha(started_at.encode("utf-8")),
        }
        if (
            name.lstrip("/") != container
            or row["configured_image"] != expected.get("configured_image")
            or row["image_id"] != expected.get("image_id")
            or row["running"] is not True
            or row["restart_count"] != 0
            or row["oom_killed"] is not False
        ):
            raise QualificationError("runtime_identity_error")
        snapshot[container] = row
    return snapshot


def _verify_backend_evidence(contract: Mapping[str, Any]) -> dict[str, Any]:
    expected = contract.get("backend_evidence")
    if not isinstance(expected, dict):
        raise QualificationError("configuration_error")
    try:
        completed = subprocess.run(
            [sys.executable, str(BACKEND_VERIFIER)],
            cwd=BACKEND_HERE,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise QualificationError("configuration_error") from exc
    if len(completed.stdout) > 16384:
        raise QualificationError("configuration_error")
    value = B._decode_json(completed.stdout, object_only=True)
    if (
        value.get("package_id") != expected.get("package_id")
        or value.get("status") != expected.get("required_status")
        or value.get("promotion_eligible") is not True
    ):
        raise QualificationError("configuration_error")
    artifacts = {
        "runtime_receipt_sha256": B._sha(B._read_regular(BACKEND_HERE / "runtime-receipt.json")),
        "official_runtime_evidence_sha256": B._sha(
            B._read_regular(BACKEND_HERE / "official-runtime-evidence.json")
        ),
        "verifier_sha256": B._sha(B._read_regular(BACKEND_VERIFIER)),
    }
    if any(artifacts[key] != expected.get(key) for key in artifacts):
        raise QualificationError("configuration_error")
    return {
        "package_id_sha256": B._sha(str(value["package_id"]).encode("utf-8")),
        "verifier_output_sha256": B._sha(completed.stdout),
        **artifacts,
        "passed": True,
    }


def _make_object_ids(run_id: str) -> tuple[str, str]:
    first = 910000 + int(B._sha((run_id + ":reference-ui").encode())[:6], 16) % 80000
    second = 910000 + int(B._sha((run_id + ":candidate-ui").encode())[:6], 16) % 80000
    if second == first:
        second = 910000 + ((second - 910000 + 1) % 80000)
    return str(first), str(second)


def _bbox_matches(value: Any, expected: Sequence[int]) -> bool:
    if not isinstance(value, dict):
        return False
    return [value.get("leftX"), value.get("topY"), value.get("rightX"), value.get("bottomY")] == list(
        expected
    )


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        return
    try:
        process.wait(timeout=5)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def _run_harness(
    contract: Mapping[str, Any],
    browser_paths: Mapping[str, Path],
    *,
    commit: str,
    sensor_name: str,
    sensor_id: str,
    reference_id: str,
    candidate_id: str,
    timeline_start: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    bounds = contract["bounds"]
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/home/nvidia"),
        "VSS_UI_SEARCH_ACK": ACK,
        "VSS_UI_ORIGIN": UI_ORIGIN,
        "VSS_PLAYWRIGHT_ENTRY": str(browser_paths["playwright"]),
        "VSS_BROWSER_EXECUTABLE": str(browser_paths["executable"]),
        "VSS_TARGET_COMMIT": commit,
        "VSS_SEARCH_TEXT": SEARCH_TEXT,
        "VSS_SENSOR_NAME": sensor_name,
        "VSS_SENSOR_ID": sensor_id,
        "VSS_REFERENCE_ID": reference_id,
        "VSS_CANDIDATE_ID": candidate_id,
        "VSS_TIMELINE_START": timeline_start,
        "VSS_REFERENCE_BBOX": ",".join(str(value) for value in contract["fixture"]["reference_bbox_xyxy"]),
        "VSS_FRAME_WIDTH": str(contract["fixture"]["frame_dimensions"][0]),
        "VSS_FRAME_HEIGHT": str(contract["fixture"]["frame_dimensions"][1]),
    }
    try:
        process = subprocess.Popen(
            [str(browser_paths["node"]), str(HARNESS_PATH), "run"],
            cwd=HERE,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as exc:
        raise QualificationError("runtime_identity_error") from exc
    try:
        stdout, stderr = process.communicate(timeout=bounds["max_browser_duration_ms"] / 1000.0 + 10)
    except subprocess.TimeoutExpired as exc:
        _kill_process_group(process)
        raise QualificationError("deadline_exceeded") from exc
    if process.returncode != 0:
        match = re.search(rb"Error: ([a-z0-9_]{1,64})", stderr)
        code = match.group(1).decode("ascii") if match else "unclassified"
        print(f"[ui-search-selected-object] browser-failure={code}", file=sys.stderr, flush=True)
        raise QualificationError("oracle_failed")
    if (
        len(stdout) < 1
        or len(stdout) > bounds["max_harness_output_bytes"]
        or len(stderr) > bounds["max_harness_output_bytes"]
    ):
        raise QualificationError("oracle_failed")
    report = B._decode_json(stdout, object_only=True)
    process_facts = {
        "stdout_sha256": B._sha(stdout),
        "stdout_bytes": len(stdout),
        "stderr_sha256": B._sha(stderr),
        "stderr_bytes": len(stderr),
        "exit_code": process.returncode,
    }
    return report, process_facts


def _validate_browser_report(
    contract: Mapping[str, Any],
    report: Mapping[str, Any],
    *,
    commit: str,
    sensor_name: str,
    sensor_id: str,
    reference_id: str,
    candidate_id: str,
) -> None:
    if (
        report.get("schema_version") != 1
        or report.get("package_id") != PACKAGE_ID
        or report.get("status") != "passed_current_candidate"
        or report.get("target_commit") != commit
        or report.get("warehouse_sample_bundle") != "excluded"
    ):
        raise QualificationError("oracle_failed")
    identity = report.get("identity")
    browser = contract["browser"]
    expected_identity = {
        "node_sha256": browser["node_sha256"],
        "playwright_entry_sha256": browser["playwright_entry_sha256"],
        "browser_executable_sha256": browser["browser_executable_sha256"],
        "browser_version_sha256": browser["browser_version_sha256"],
        "ui_origin_sha256": browser["ui_origin_sha256"],
        "sensor_name_sha256": B._sha(sensor_name.encode("utf-8")),
        "sensor_id_sha256": B._sha(sensor_id.encode("utf-8")),
    }
    if identity != expected_identity:
        raise QualificationError("runtime_identity_error")
    bounds = report.get("bounds")
    if not isinstance(bounds, dict) or (
        bounds.get("max_duration_ms") != contract["bounds"]["max_browser_duration_ms"]
        or bounds.get("max_browser_actions") != contract["bounds"]["max_browser_actions"]
        or bounds.get("max_loopback_browser_responses") != contract["bounds"]["max_loopback_browser_responses"]
        or not isinstance(bounds.get("duration_ms"), int)
        or not 1 <= bounds["duration_ms"] <= bounds["max_duration_ms"]
        or not isinstance(bounds.get("browser_actions"), int)
        or not 1 <= bounds["browser_actions"] <= bounds["max_browser_actions"]
        or not isinstance(bounds.get("loopback_browser_responses"), int)
        or not 1 <= bounds["loopback_browser_responses"] <= bounds["max_loopback_browser_responses"]
    ):
        raise QualificationError("oracle_failed")
    flow = report.get("flow")
    if not isinstance(flow, dict):
        raise QualificationError("oracle_failed")
    direct = flow.get("direct_search")
    frame = flow.get("frame_selection")
    selected = flow.get("selected_search")
    diagnostics = flow.get("diagnostics")
    if not all(isinstance(value, dict) for value in (direct, frame, selected, diagnostics)):
        raise QualificationError("oracle_failed")
    if (
        direct.get("query_sha256") != contract["fixture"]["query_contract"]["sha256"]
        or direct.get("query_bytes") != contract["fixture"]["query_contract"]["bytes"]
        or direct.get("filter_defaults") != {"top_k": 10, "similarity": -1}
        or direct.get("exact_local_source_selected") is not True
        or direct.get("top_k_5_selected") is not True
        or direct.get("http_status") != 200
        or not isinstance(direct.get("result_count"), int)
        or direct["result_count"] < 1
        or not isinstance(direct.get("rendered_card_count"), int)
        or direct["rendered_card_count"] < 1
        or direct.get("result_aligned_to_fixture_start") is not True
        or direct.get("playback_modal_opened") is not True
        or direct.get("playback_metadata_loaded") is not True
        or direct.get("playback_duration_positive") is not True
    ):
        raise QualificationError("oracle_failed")
    if (
        frame.get("picture_http_status") != 200
        or frame.get("frames_http_status") != 200
        or frame.get("frame_count") != 1
        or frame.get("frame_width") != contract["fixture"]["frame_dimensions"][0]
        or frame.get("frame_height") != contract["fixture"]["frame_dimensions"][1]
        or frame.get("object_count") != 2
        or frame.get("select_hint_visible") is not True
        or frame.get("reference_bbox_clicked") is not True
        or frame.get("selected_object_id_sha256") != B._sha(reference_id.encode("utf-8"))
    ):
        raise QualificationError("oracle_failed")
    if (
        selected.get("http_status") != 200
        or selected.get("exact_composite_identity") is not True
        or selected.get("agent_mode_false") is not True
        or selected.get("source_type_video_file") is not True
        or selected.get("result_count") != 1
        or selected.get("message_count") != 0
        or selected.get("candidate_object_id_sha256") != B._sha(candidate_id.encode("utf-8"))
        or selected.get("seed_object_id_sha256") != B._sha(reference_id.encode("utf-8"))
        or selected.get("seed_excluded") is not True
        or selected.get("candidate_only") is not True
        or selected.get("result_card_rerendered") is not True
        or selected.get("rendered_card_count") != 1
        or selected.get("human_facing_source_name_preserved") is not True
        or selected.get("modal_closed") is not True
        or selected.get("overlay_closed") is not True
    ):
        raise QualificationError("oracle_failed")
    similarity = selected.get("similarity")
    if isinstance(similarity, bool) or not isinstance(similarity, (int, float)) or not math.isfinite(similarity):
        raise QualificationError("oracle_failed")
    expected_empty = {
        "console_error_hashes",
        "page_error_hashes",
        "request_failure_hashes",
        "failing_response_hashes",
    }
    if any(diagnostics.get(key) != [] for key in expected_empty):
        raise QualificationError("oracle_failed")
    for key in (
        "non_loopback_request_count",
        "non_loopback_response_count",
        "non_loopback_websocket_count",
        "framework_error_overlay_count",
    ):
        if diagnostics.get(key) != 0:
            raise QualificationError("oracle_failed")
    cleanup = report.get("cleanup")
    if cleanup != {
        "isolated_browser_closed": True,
        "temporary_screenshots_deleted_after_hashing": True,
    }:
        raise QualificationError("cleanup_failed")
    raw = B._canonical(report).decode("ascii")
    forbidden = (
        "://",
        '"query":',
        '"prompt":',
        '"sensor_id":',
        '"object_id":',
        '"reference_object":',
        '"url":',
        '"vector":',
    )
    if any(item in raw for item in forbidden):
        raise QualificationError("oracle_failed")


def _execute(contract: dict[str, Any], run_id: str, acknowledgement: str) -> dict[str, Any]:
    if acknowledgement != ACK:
        raise QualificationError("authorization_required")
    started = time.monotonic()
    deadline = started + contract["bounds"]["max_duration_ms"] / 1000.0
    source_hashes = B._validate_source_locks(contract)
    browser_paths = _validate_browser(contract)
    commit = B._run(["git", "rev-parse", "HEAD"], timeout=10, maximum=256).decode().strip()
    if commit != contract["target_commit"] or not COMMIT_RE.fullmatch(commit):
        raise QualificationError("configuration_error")
    backend_evidence = _verify_backend_evidence(contract)
    _progress("backend-evidence-passed")
    pre_runtime = _runtime_snapshot(contract)
    host_ip, rtvi_cv_port = B._selected_env()
    try:
        address = ipaddress.ip_address(host_ip)
    except ValueError as exc:
        raise QualificationError("configuration_error") from exc
    origins = {
        "elasticsearch": "http://127.0.0.1:9200",
        "ingress": "http://127.0.0.1:7777",
        "rtvi_cv": f"http://{address.compressed}:{rtvi_cv_port}",
        "ui": UI_ORIGIN,
    }
    budget = B.Budget(
        max_requests=contract["bounds"]["max_fixture_http_requests"],
        max_mutations=contract["bounds"]["max_persistent_mutations"],
    )
    http = B.LocalHttp(
        origins={key: value for key, value in origins.items() if key != "ui"},
        budget=budget,
        response_limit=contract["bounds"]["max_response_bytes"],
        deadline=deadline,
    )
    behavior = B.OwnedIndex(BEHAVIOR_INDEX)
    raw_index = B.OwnedIndex(RAW_INDEX)
    cleanup_rows: dict[str, Any] = {}
    fixture_context: dict[str, Any] = {}
    browser_report: dict[str, Any] | None = None
    browser_process: dict[str, Any] | None = None
    embed_uuid = ""
    embed_count = -1
    sensor_name = ""
    sensor_id = ""
    base: datetime | None = None
    reference_id = ""
    candidate_id = ""
    failure: QualificationError | None = None
    _progress("admission-passed")
    try:
        behavior_pre, _ = B._index_status(http, BEHAVIOR_INDEX, "behavior_prestate")
        raw_pre, _ = B._index_status(http, RAW_INDEX, "raw_prestate")
        if behavior_pre != 404 or raw_pre != 404:
            raise QualificationError("fixture_error")
        embed_uuid = B._index_uuid(http, EMBED_INDEX, "embed_pre_uuid")
        embed_count = B._index_count(http, EMBED_INDEX, "embed_pre_count")
        if embed_count < 1:
            raise QualificationError("fixture_error")

        _, sensors, _ = http.call(
            operation="vios_sensor_inventory",
            target="ingress",
            method="GET",
            path="/vst/api/v1/sensor/list",
        )
        if not isinstance(sensors, list):
            raise QualificationError("fixture_error")
        sensor_hash = contract["fixture"]["existing_sensor_name_sha256"]
        matches = [
            row
            for row in sensors
            if isinstance(row, dict)
            and isinstance(row.get("name"), str)
            and B._sha(row["name"].encode("utf-8")) == sensor_hash
        ]
        if len(matches) != 1:
            raise QualificationError("fixture_error")
        sensor = matches[0]
        sensor_name = sensor.get("name", "")
        sensor_id = sensor.get("sensorId", "")
        if (
            not isinstance(sensor_name, str)
            or not PLAIN_RE.fullmatch(sensor_name)
            or not isinstance(sensor_id, str)
            or not PLAIN_RE.fullmatch(sensor_id)
            or sensor.get("type") != contract["fixture"]["required_sensor_type"]
            or sensor.get("state") != contract["fixture"]["required_sensor_state"]
            or sensor.get("isTimelinePresent") is not True
        ):
            raise QualificationError("fixture_error")
        _, storage, _ = http.call(
            operation="vios_storage_timelines",
            target="ingress",
            method="GET",
            path="/vst/api/v1/storage/size?timelines=true",
        )
        try:
            timeline = storage[sensor_id]["timelines"][0]
            base = B._parse_iso(timeline["startTime"])
            timeline_end = B._parse_iso(timeline["endTime"])
        except (KeyError, IndexError, TypeError) as exc:
            raise QualificationError("fixture_error") from exc
        timeline_seconds = (timeline_end - base).total_seconds()
        if timeline_seconds < contract["fixture"]["minimum_timeline_seconds"]:
            raise QualificationError("fixture_error")
        fixture_context = {
            "sensor_name_sha256": B._sha(sensor_name.encode("utf-8")),
            "sensor_id_sha256": B._sha(sensor_id.encode("utf-8")),
            "timeline_sha256": B._digest(timeline),
            "timeline_seconds": timeline_seconds,
        }
        _progress("fixture-resolved")

        dimensions = contract["indices"]["vector_dimensions"]
        for template_name, operation in (
            ("mdx_behavior_template", "behavior_template"),
            ("mdx_raw_template", "raw_template"),
        ):
            _, template, _ = http.call(
                operation=operation,
                target="elasticsearch",
                method="GET",
                path=f"/_index_template/{template_name}",
            )
            if B._template_dimensions(template) != {dimensions}:
                raise QualificationError("oracle_failed")
        _, live, _ = http.call(
            operation="rtvi_cv_liveness",
            target="rtvi_cv",
            method="GET",
            path="/api/v1/live",
        )
        if not isinstance(live, dict):
            raise QualificationError("oracle_failed")
        _, embedding_value, _ = http.call(
            operation="embedding_query",
            target="rtvi_cv",
            method="POST",
            path="/api/v1/generate_text_embeddings",
            body={"text_input": SEARCH_TEXT, "model": ""},
        )
        embedding = B._vector(embedding_value, dimensions)
        _progress("embedding-passed")

        _, created_behavior, _ = http.call(
            operation="create_behavior_index",
            target="elasticsearch",
            method="PUT",
            path=f"/{BEHAVIOR_INDEX}",
            body={},
            mutation=True,
        )
        if not isinstance(created_behavior, dict) or created_behavior.get("acknowledged") is not True:
            raise QualificationError("oracle_failed")
        behavior.uuid = B._index_uuid(http, BEHAVIOR_INDEX, "behavior_owned_uuid")
        _, created_raw, _ = http.call(
            operation="create_raw_index",
            target="elasticsearch",
            method="PUT",
            path=f"/{RAW_INDEX}",
            body={},
            mutation=True,
        )
        if not isinstance(created_raw, dict) or created_raw.get("acknowledged") is not True:
            raise QualificationError("oracle_failed")
        raw_index.uuid = B._index_uuid(http, RAW_INDEX, "raw_owned_uuid")
        _progress("owned-indices-created")

        reference_id, candidate_id = _make_object_ids(run_id)
        reference_bbox = contract["fixture"]["reference_bbox_xyxy"]
        candidate_bbox = contract["fixture"]["candidate_bbox_xyxy"]
        t0 = B._iso(base)
        t4 = B._iso(base + timedelta(seconds=4.0))
        t42 = B._iso(base + timedelta(seconds=4.2))
        tend = B._iso(timeline_end)
        behavior_docs = [
            (
                f"vssui-{run_id}-behavior-reference",
                {
                    "Id": f"vssui-{run_id}-behavior-reference",
                    "timestamp": t0,
                    "end": tend,
                    "sensor": {"id": sensor_name, "type": "camera"},
                    "object": {
                        "id": reference_id,
                        "type": "Person",
                        "bbox": {
                            "leftX": reference_bbox[0],
                            "topY": reference_bbox[1],
                            "rightX": reference_bbox[2],
                            "bottomY": reference_bbox[3],
                        },
                    },
                    "embeddings": {"vector": embedding},
                },
            ),
            (
                f"vssui-{run_id}-behavior-candidate",
                {
                    "Id": f"vssui-{run_id}-behavior-candidate",
                    "timestamp": t4,
                    "end": t42,
                    "sensor": {"id": sensor_name, "type": "camera"},
                    "object": {
                        "id": candidate_id,
                        "type": "Person",
                        "bbox": {
                            "leftX": candidate_bbox[0],
                            "topY": candidate_bbox[1],
                            "rightX": candidate_bbox[2],
                            "bottomY": candidate_bbox[3],
                        },
                    },
                    "embeddings": {"vector": embedding},
                },
            ),
        ]
        for ordinal, (document_id, document) in enumerate(behavior_docs, start=1):
            http.call(
                operation=f"write_behavior_{ordinal}",
                target="elasticsearch",
                method="PUT",
                path=f"/{BEHAVIOR_INDEX}/_doc/{document_id}",
                body=document,
                allowed=(200, 201),
                mutation=True,
            )
            behavior.document_ids.add(document_id)
        raw_document_id = f"vssui-{run_id}-raw"
        raw_document = {
            "id": 1,
            "timestamp": t0,
            "sensorId": sensor_name,
            "objects": [
                {
                    "id": reference_id,
                    "type": "Person",
                    "bbox": {
                        "leftX": reference_bbox[0],
                        "topY": reference_bbox[1],
                        "rightX": reference_bbox[2],
                        "bottomY": reference_bbox[3],
                    },
                    "embedding": {"vector": embedding},
                },
                {
                    "id": candidate_id,
                    "type": "Person",
                    "bbox": {
                        "leftX": candidate_bbox[0],
                        "topY": candidate_bbox[1],
                        "rightX": candidate_bbox[2],
                        "bottomY": candidate_bbox[3],
                    },
                    "embedding": {"vector": embedding},
                },
            ],
        }
        http.call(
            operation="write_raw_frame",
            target="elasticsearch",
            method="PUT",
            path=f"/{RAW_INDEX}/_doc/{raw_document_id}",
            body=raw_document,
            allowed=(200, 201),
            mutation=True,
        )
        raw_index.document_ids.add(raw_document_id)
        for index, operation in ((BEHAVIOR_INDEX, "refresh_behavior"), (RAW_INDEX, "refresh_raw")):
            http.call(
                operation=operation,
                target="elasticsearch",
                method="POST",
                path=f"/{index}/_refresh",
                mutation=True,
            )
        if B._index_count(http, BEHAVIOR_INDEX, "behavior_fixture_count") != 2:
            raise QualificationError("oracle_failed")
        if B._index_count(http, RAW_INDEX, "raw_fixture_count") != 1:
            raise QualificationError("oracle_failed")
        _progress("owned-documents-indexed")

        frames_query = urlencode(
            {
                "sensorId": sensor_name,
                "fromTimestamp": B._iso(base - timedelta(milliseconds=200)),
                "toTimestamp": t0,
            }
        )
        _, frames_value, _ = http.call(
            operation="analytics_frames",
            target="ingress",
            method="GET",
            path=f"/video-analytics-api/frames?{frames_query}",
        )
        frames = B._frame_rows(frames_value)
        if len(frames) != 1:
            raise QualificationError("oracle_failed")
        frame_objects = frames[0].get("objects")
        if frame_objects is None and isinstance(frames[0].get("metadata"), dict):
            frame_objects = frames[0]["metadata"].get("objects")
        if not isinstance(frame_objects, list) or len(frame_objects) != 2:
            raise QualificationError("oracle_failed")
        by_id = {
            str(row.get("id")): row
            for row in frame_objects
            if isinstance(row, dict) and row.get("id") is not None
        }
        if set(by_id) != {reference_id, candidate_id}:
            raise QualificationError("oracle_failed")
        if not _bbox_matches(by_id[reference_id].get("bbox"), reference_bbox):
            raise QualificationError("oracle_failed")
        if not _bbox_matches(by_id[candidate_id].get("bbox"), candidate_bbox):
            raise QualificationError("oracle_failed")
        _progress("frames-api-passed")

        _progress("browser-started")
        browser_report, browser_process = _run_harness(
            contract,
            browser_paths,
            commit=commit,
            sensor_name=sensor_name,
            sensor_id=sensor_id,
            reference_id=reference_id,
            candidate_id=candidate_id,
            timeline_start=t0,
        )
        _validate_browser_report(
            contract,
            browser_report,
            commit=commit,
            sensor_name=sensor_name,
            sensor_id=sensor_id,
            reference_id=reference_id,
            candidate_id=candidate_id,
        )
        _progress("browser-passed")
    except QualificationError as exc:
        failure = exc
        _failure("runtime", exc.code)
    except Exception as exc:
        failure = QualificationError("oracle_failed")
        failure.__cause__ = exc
        _failure("runtime", failure.code)
    finally:
        try:
            _progress("cleanup-started")
            cleanup_rows["behavior"] = B._cleanup_index(http, behavior)
            cleanup_rows["raw"] = B._cleanup_index(http, raw_index)
            _progress("cleanup-indices-processed")
            absence_rows: list[dict[str, int]] = []
            for check in range(contract["bounds"]["cleanup_absence_checks"]):
                if check:
                    time.sleep(1.0)
                behavior_status, _ = B._index_status(
                    http, BEHAVIOR_INDEX, f"behavior_absent_{check + 1}"
                )
                raw_status, _ = B._index_status(http, RAW_INDEX, f"raw_absent_{check + 1}")
                absence_rows.append({"behavior": behavior_status, "raw": raw_status})
            cleanup_rows["absence_checks"] = absence_rows
            if any(row != {"behavior": 404, "raw": 404} for row in absence_rows):
                raise QualificationError("cleanup_failed")
            if any(
                row.get("foreign_documents_observed")
                for key, row in cleanup_rows.items()
                if key in {"behavior", "raw"}
            ):
                raise QualificationError("cleanup_failed")
            _progress("cleanup-absence-passed")
            embed_post_uuid = B._index_uuid(http, EMBED_INDEX, "embed_post_uuid")
            embed_post_count = B._index_count(http, EMBED_INDEX, "embed_post_count")
            cleanup_rows["embed_read_only_unchanged"] = (
                embed_post_uuid == embed_uuid and embed_post_count == embed_count
            )
            if not cleanup_rows["embed_read_only_unchanged"]:
                raise QualificationError("cleanup_failed")
            _progress("cleanup-embed-passed")
            if base is not None and sensor_name:
                frames_query = urlencode(
                    {
                        "sensorId": sensor_name,
                        "fromTimestamp": B._iso(base - timedelta(milliseconds=200)),
                        "toTimestamp": B._iso(base),
                    }
                )
                _, post_frames_value, _ = http.call(
                    operation="analytics_frames_post_cleanup",
                    target="ingress",
                    method="GET",
                    path=f"/video-analytics-api/frames?{frames_query}",
                )
                cleanup_rows["frames_empty"] = B._frame_rows(post_frames_value) == []
                if not cleanup_rows["frames_empty"]:
                    raise QualificationError("cleanup_failed")
                _progress("cleanup-frames-passed")
            _progress("cleanup-passed")
        except QualificationError as exc:
            failure = exc
            _failure("cleanup", exc.code)

    if failure is not None:
        raise failure
    if browser_report is None or browser_process is None:
        raise QualificationError("oracle_failed")
    post_runtime = _runtime_snapshot(contract)
    if post_runtime != pre_runtime:
        raise QualificationError("runtime_identity_error")
    duration_ms = round((time.monotonic() - started) * 1000)
    if duration_ms < 1 or duration_ms > contract["bounds"]["max_duration_ms"]:
        raise QualificationError("deadline_exceeded")
    receipt = {
        "schema_version": 1,
        "package_id": PACKAGE_ID,
        "status": "passed_current_candidate",
        "promotion_eligible": True,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "target_commit": commit,
        "contract_sha256": B._sha(B._read_regular(CONTRACT_PATH)),
        "executor_sha256": B._sha(B._read_regular(Path(__file__).resolve())),
        "harness_sha256": B._sha(B._read_regular(HARNESS_PATH)),
        "receipt_schema_sha256": B._sha(B._read_regular(SCHEMA_PATH)),
        "identity": {
            "run_id_sha256": B._sha(run_id.encode("utf-8")),
            "authorization_id": AUTHORIZATION_ID,
            "authorization_token_sha256": B._sha(acknowledgement.encode("utf-8")),
            "origin_hashes": {
                name: B._sha(origin.encode("utf-8")) for name, origin in sorted(origins.items())
            },
            "source_hashes": source_hashes,
            "query_contract": contract["fixture"]["query_contract"],
            "backend_evidence": backend_evidence,
            "browser": browser_report["identity"],
            "browser_process": browser_process,
        },
        "pre_state": {
            "runtime": pre_runtime,
            "owned_index_status": {"behavior": 404, "raw": 404},
            "embed_index": {"uuid_sha256": B._sha(embed_uuid.encode("utf-8")), "count": embed_count},
            "fixture": fixture_context,
        },
        "bounds": {
            "duration_ms": duration_ms,
            "fixture_http_requests": budget.requests,
            "persistent_mutations": budget.mutations,
            "browser_duration_ms": browser_report["bounds"]["duration_ms"],
            "browser_actions": browser_report["bounds"]["browser_actions"],
            "loopback_browser_responses": browser_report["bounds"]["loopback_browser_responses"],
            "max_duration_ms": contract["bounds"]["max_duration_ms"],
            "max_fixture_http_requests": budget.max_requests,
            "max_persistent_mutations": budget.max_mutations,
            "max_browser_duration_ms": contract["bounds"]["max_browser_duration_ms"],
            "max_browser_actions": contract["bounds"]["max_browser_actions"],
            "max_loopback_browser_responses": contract["bounds"]["max_loopback_browser_responses"],
        },
        "observations": http.observations,
        "ui_semantics": browser_report["flow"],
        "post_state": {
            "runtime": post_runtime,
            "owned_index_status": {"behavior": 404, "raw": 404},
            "embed_index": {"uuid_sha256": B._sha(embed_uuid.encode("utf-8")), "count": embed_count},
        },
        "cleanup": {
            **cleanup_rows,
            "isolated_browser_closed": True,
            "temporary_screenshots_deleted_after_hashing": True,
            "exact_owned_resources_only": True,
            "persistent_stream_mutations": 0,
            "service_lifecycle_mutations": 0,
            "warehouse_sample_bundle": "excluded",
        },
    }
    schema = B._load_object(SCHEMA_PATH)
    try:
        Draft202012Validator.check_schema(schema)
        errors = list(Draft202012Validator(schema).iter_errors(receipt))
    except Exception as exc:
        raise QualificationError("configuration_error") from exc
    if errors:
        raise QualificationError("configuration_error")
    return receipt


def _atomic_write(receipt: Mapping[str, Any]) -> None:
    raw = json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False).encode("ascii") + b"\n"
    descriptor, temporary = tempfile.mkstemp(prefix=".runtime-receipt.", dir=HERE)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, RECEIPT_PATH)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _plan(contract: Mapping[str, Any]) -> dict[str, Any]:
    source_hashes = B._validate_source_locks(contract)
    _validate_browser(contract)
    return {
        "schema_version": 1,
        "package_id": PACKAGE_ID,
        "mode": "plan",
        "status": "ready_inert",
        "network_requests": 0,
        "persistent_mutations": 0,
        "authorization_required": True,
        "source_lock_count": len(source_hashes),
        "warehouse_sample_bundle": "excluded",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("plan")
    execute = subparsers.add_parser("execute-http")
    execute.add_argument("--ack", required=True)
    execute.add_argument("--run-id", required=True)
    execute.add_argument("--receipt", default=str(RECEIPT_PATH))
    args = parser.parse_args(argv)
    command = args.command or "plan"
    try:
        contract = _contract()
        if command == "plan":
            print(json.dumps(_plan(contract), sort_keys=True))
            return 0
        if command != "execute-http":
            raise QualificationError("configuration_error")
        if Path(args.receipt).resolve() != RECEIPT_PATH.resolve():
            raise QualificationError("configuration_error")
        run_id = args.run_id
        if not isinstance(run_id, str) or not B.PLAIN_RE.fullmatch(run_id):
            raise QualificationError("configuration_error")
        receipt = _execute(contract, run_id, args.ack)
        _atomic_write(receipt)
        print(
            json.dumps(
                {
                    "package_id": PACKAGE_ID,
                    "status": receipt["status"],
                    "promotion_eligible": receipt["promotion_eligible"],
                    "fixture_http_requests": receipt["bounds"]["fixture_http_requests"],
                    "persistent_mutations": receipt["bounds"]["persistent_mutations"],
                    "browser_actions": receipt["bounds"]["browser_actions"],
                    "cleanup_complete": True,
                },
                sort_keys=True,
            )
        )
        return 0
    except QualificationError as exc:
        print(json.dumps({"status": "failed", "failure": exc.code}, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
