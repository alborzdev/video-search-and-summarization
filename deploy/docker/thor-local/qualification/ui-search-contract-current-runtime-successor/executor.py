#!/usr/bin/env python3
"""Bounded read-only current-runtime qualification for the complete Search UI contract."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
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

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4].resolve(strict=True)
CONTRACT_PATH = HERE / "contract.json"
HARNESS_PATH = HERE / "harness.mjs"
SCHEMA_PATH = HERE / "receipt.schema.json"
RECEIPT_PATH = HERE / "runtime-receipt.json"
SELECTED_HERE = HERE.parent / "ui-search-selected-object-current-runtime-successor"
CRITIC_HERE = HERE.parent / "ui-search-playwright-runtime-successor"
PACKAGE_ID = "thor-ui-search-contract-current-runtime-successor-v1"
ACK = "I_ACK_UI_SEARCH_CONTRACT_CURRENT_RUNTIME_READ_ONLY"
UI_ORIGIN = "http://127.0.0.1:3001"
SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
COMMIT_RE = re.compile(r"[0-9a-f]{40}\Z")
MAX_FILE_BYTES = 512 * 1024 * 1024


class QualificationError(RuntimeError):
    """The qualification was not admitted or an exact assertion failed."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _load_object(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise QualificationError(f"duplicate key in {path.name}")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda item: (_ for _ in ()).throw(
                QualificationError(f"non-finite value in {path.name}: {item}")
            ),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"invalid JSON: {path.name}") from exc
    if not isinstance(value, dict):
        raise QualificationError(f"{path.name} must be an object")
    return value


def _sha_file(path: Path, maximum: int = MAX_FILE_BYTES) -> str:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size < 1 or before.st_size > maximum:
            raise QualificationError("invalid regular file")
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
            raise QualificationError("file changed while hashing")
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def _repo_path(relative_text: Any) -> Path:
    if not isinstance(relative_text, str):
        raise QualificationError("invalid source-lock path")
    relative = Path(relative_text)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise QualificationError("invalid source-lock path")
    target = (ROOT / relative).resolve(strict=True)
    target.relative_to(ROOT)
    return target


def _validate_source_locks(contract: Mapping[str, Any]) -> dict[str, str]:
    rows = contract.get("source_locks")
    if not isinstance(rows, list) or len(rows) < 20:
        raise QualificationError("source-lock inventory is incomplete")
    result: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"path", "sha256"}:
            raise QualificationError("invalid source lock")
        relative = row["path"]
        expected = row["sha256"]
        if relative in result or not isinstance(expected, str) or not SHA_RE.fullmatch(expected):
            raise QualificationError("invalid source lock")
        if _sha_file(_repo_path(relative)) != expected:
            raise QualificationError(f"source lock drifted: {relative}")
        result[relative] = expected
    return result


def _validate_absolute_regular(path_text: Any, expected: Any) -> Path:
    if not isinstance(path_text, str) or not path_text.startswith("/"):
        raise QualificationError("invalid browser path")
    if not isinstance(expected, str) or not SHA_RE.fullmatch(expected):
        raise QualificationError("invalid browser digest")
    path = Path(path_text)
    resolved = path.resolve(strict=True)
    if not stat.S_ISREG(resolved.stat().st_mode) or _sha_file(resolved) != expected:
        raise QualificationError("browser identity drifted")
    return path


def _contract() -> dict[str, Any]:
    contract = _load_object(CONTRACT_PATH)
    expected = {
        "schema_version": 1,
        "package_id": PACKAGE_ID,
        "capability_id": "runtime.ui.search-tab",
        "supporting_capability_id": "runtime.agent.search-profile",
        "oracle_id": "oracle.runtime.ui.search-tab",
        "mode": "authorization-gated-read-only-isolated-playwright-numeric-loopback-runtime",
        "default_execution_enabled": False,
    }
    if any(contract.get(key) != value for key, value in expected.items()):
        raise QualificationError("contract identity drifted")
    if contract.get("authorization", {}).get("acknowledgement") != ACK:
        raise QualificationError("authorization contract drifted")
    if not COMMIT_RE.fullmatch(str(contract.get("target_commit", ""))):
        raise QualificationError("target commit is invalid")
    if contract.get("bounds", {}).get("max_persistent_mutations") != 0:
        raise QualificationError("read-only mutation bound drifted")
    _validate_source_locks(contract)
    browser = contract.get("browser")
    if not isinstance(browser, dict):
        raise QualificationError("browser contract missing")
    _validate_absolute_regular(browser.get("node_path"), browser.get("node_sha256"))
    _validate_absolute_regular(browser.get("playwright_entry_path"), browser.get("playwright_entry_sha256"))
    _validate_absolute_regular(browser.get("browser_executable_path"), browser.get("browser_executable_sha256"))
    if browser.get("ui_origin_sha256") != _sha(UI_ORIGIN.encode("utf-8")):
        raise QualificationError("UI origin digest drifted")
    return contract


def _run(
    command: Sequence[str],
    *,
    timeout: float,
    maximum: int,
    environment: Mapping[str, str] | None = None,
) -> bytes:
    try:
        completed = subprocess.run(
            list(command),
            cwd=ROOT,
            env=dict(environment) if environment is not None else None,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise QualificationError("bounded command failed") from exc
    if len(completed.stdout) > maximum or len(completed.stderr) > maximum:
        raise QualificationError("bounded command output exceeded")
    return completed.stdout


def _runtime_snapshot(contract: Mapping[str, Any]) -> dict[str, Any]:
    runtime = contract.get("runtime")
    if not isinstance(runtime, dict) or len(runtime) != 3:
        raise QualificationError("runtime contract drifted")
    template = "{{.Name}}|{{.Config.Image}}|{{.Image}}|{{.State.Running}}|{{.RestartCount}}|{{.State.OOMKilled}}|{{.State.StartedAt}}"
    snapshot: dict[str, Any] = {}
    for expected in runtime.values():
        if not isinstance(expected, dict):
            raise QualificationError("runtime contract drifted")
        container = expected.get("container")
        if not isinstance(container, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", container):
            raise QualificationError("runtime container is invalid")
        raw = _run(
            ["docker", "inspect", "--format", template, container],
            timeout=10,
            maximum=4096,
        ).decode("utf-8").strip()
        parts = raw.split("|")
        if len(parts) != 7:
            raise QualificationError("runtime identity shape drifted")
        name, configured_image, image_id, running, restart_text, oom_text, started_at = parts
        try:
            restart_count = int(restart_text)
        except ValueError as exc:
            raise QualificationError("runtime restart count is invalid") from exc
        row = {
            "configured_image": configured_image,
            "image_id": image_id,
            "running": running == "true",
            "restart_count": restart_count,
            "oom_killed": oom_text == "true",
            "started_at_sha256": _sha(started_at.encode("utf-8")),
        }
        if (
            name.lstrip("/") != container
            or configured_image != expected.get("configured_image")
            or image_id != expected.get("image_id")
            or row["running"] is not True
            or restart_count != 0
            or row["oom_killed"] is not False
        ):
            raise QualificationError(f"runtime identity drifted: {container}")
        snapshot[container] = row
    return snapshot


def _critic_runtime_state() -> dict[str, bool]:
    raw = _run(
        ["docker", "inspect", "--format", "{{json .Config.Env}}", "vss-agent"],
        timeout=10,
        maximum=1024 * 1024,
    )
    try:
        environment = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError("Agent environment shape drifted") from exc
    if not isinstance(environment, list) or not all(isinstance(item, str) for item in environment):
        raise QualificationError("Agent environment shape drifted")
    values = [item.split("=", 1)[1] for item in environment if item.startswith("ENABLE_CRITIC=")]
    if values != ["true"]:
        raise QualificationError("current Agent critic default is not enabled")

    compose_text = _repo_path("deploy/docker/services/agent/compose.yml").read_text(encoding="utf-8")
    config_text = _repo_path(
        "deploy/docker/developer-profiles/dev-profile-thor-full/vss-agent/configs/config.yml"
    ).read_text(encoding="utf-8")
    data_models_text = _repo_path("services/agent/src/vss_agents/agents/data_models.py").read_text(encoding="utf-8")
    top_agent_text = _repo_path("services/agent/src/vss_agents/agents/top_agent.py").read_text(encoding="utf-8")
    if "ENABLE_CRITIC: ${ENABLE_CRITIC:-true}" not in compose_text:
        raise QualificationError("critic Compose default contract drifted")
    if config_text.count("enable_critic: ${ENABLE_CRITIC:-true}") < 2:
        raise QualificationError("critic profile default contract drifted")
    if "use_critic: bool = Field(default=True" not in data_models_text:
        raise QualificationError("critic request default contract drifted")
    if "typed_request.use_critic if typed_request.use_critic is not None else True" not in top_agent_text:
        raise QualificationError("critic top-agent default contract drifted")
    return {
        "runtime_default_enabled": True,
        "compose_default_enabled": True,
        "profile_default_enabled": True,
        "request_default_enabled": True,
        "disable_env_supported": True,
    }


def _verify_selected_evidence(contract: Mapping[str, Any]) -> dict[str, Any]:
    expected = contract["selected_object_evidence"]
    verifier = SELECTED_HERE / "verify.py"
    raw = _run([sys.executable, str(verifier)], timeout=30, maximum=16384)
    try:
        result = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError("selected-object verifier output is invalid") from exc
    if (
        result.get("package_id") != expected["package_id"]
        or result.get("status") != expected["required_status"]
        or result.get("promotion_eligible") is not True
    ):
        raise QualificationError("selected-object evidence is not current-passed")
    artifacts = {
        "contract_sha256": _sha_file(SELECTED_HERE / "contract.json"),
        "official_runtime_evidence_sha256": _sha_file(SELECTED_HERE / "official-runtime-evidence.json"),
        "verifier_sha256": _sha_file(verifier),
    }
    if any(artifacts[key] != expected[key] for key in artifacts):
        raise QualificationError("selected-object evidence binding drifted")
    return {**artifacts, "verifier_output_sha256": _sha(raw), "passed": True}


def _verify_critic_evidence(contract: Mapping[str, Any]) -> dict[str, Any]:
    expected = contract["critic_runtime_evidence"]
    verifier = CRITIC_HERE / "verify.py"
    raw = _run([sys.executable, str(verifier)], timeout=30, maximum=16384)
    receipt = _load_object(CRITIC_HERE / "runtime-receipt.json")
    confirmed = sum(
        card.get("label") == "Confirmed"
        for card in receipt.get("critic", {}).get("cards", [])
        if isinstance(card, dict)
    )
    if (
        receipt.get("package_id") != expected["package_id"]
        or receipt.get("status") != expected["required_status"]
        or confirmed < expected["required_confirmed_cards"]
    ):
        raise QualificationError("prior local critic evidence is incomplete")
    artifacts = {
        "contract_sha256": _sha_file(CRITIC_HERE / "contract.json"),
        "runtime_receipt_sha256": _sha_file(CRITIC_HERE / "runtime-receipt.json"),
        "verifier_sha256": _sha_file(verifier),
    }
    if any(artifacts[key] != expected[key] for key in artifacts):
        raise QualificationError("prior critic evidence binding drifted")
    return {
        **artifacts,
        "verifier_output_sha256": _sha(raw),
        "confirmed_card_count": confirmed,
        "passed": True,
    }


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


def _run_harness(contract: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    browser = contract["browser"]
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/home/nvidia"),
        "VSS_UI_SEARCH_CONTRACT_ACK": ACK,
        "VSS_UI_ORIGIN": UI_ORIGIN,
        "VSS_PLAYWRIGHT_ENTRY": browser["playwright_entry_path"],
        "VSS_BROWSER_EXECUTABLE": browser["browser_executable_path"],
        "VSS_TARGET_COMMIT": contract["target_commit"],
    }
    process = subprocess.Popen(
        [browser["node_path"], str(HARNESS_PATH), "run"],
        cwd=HERE,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=contract["bounds"]["max_browser_duration_ms"] / 1000 + 10)
    except subprocess.TimeoutExpired as exc:
        _kill_process_group(process)
        raise QualificationError("browser deadline exceeded") from exc
    if process.returncode != 0:
        match = re.search(rb"Error: ([a-z0-9_]{1,64})", stderr)
        code = match.group(1).decode("ascii") if match else "unclassified"
        print(f"[ui-search-contract] browser-failure={code}", file=sys.stderr, flush=True)
        raise QualificationError("browser qualification failed")
    maximum = contract["bounds"]["max_harness_output_bytes"]
    if len(stdout) < 1 or len(stdout) > maximum or len(stderr) > maximum:
        raise QualificationError("browser output bound exceeded")
    try:
        report = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError("browser report is invalid") from exc
    if not isinstance(report, dict):
        raise QualificationError("browser report is invalid")
    process_facts = {
        "stdout_sha256": _sha(stdout),
        "stdout_bytes": len(stdout),
        "stderr_sha256": _sha(stderr),
        "stderr_bytes": len(stderr),
        "exit_code": process.returncode,
    }
    return report, process_facts


def _validate_browser_report(contract: Mapping[str, Any], report: Mapping[str, Any]) -> None:
    if (
        report.get("schema_version") != 1
        or report.get("package_id") != PACKAGE_ID
        or report.get("status") != "passed_current_candidate"
        or report.get("target_commit") != contract["target_commit"]
        or report.get("warehouse_sample_bundle") != "excluded"
    ):
        raise QualificationError("browser report identity drifted")
    browser = contract["browser"]
    if report.get("identity") != {
        "node_sha256": browser["node_sha256"],
        "playwright_entry_sha256": browser["playwright_entry_sha256"],
        "browser_executable_sha256": browser["browser_executable_sha256"],
        "browser_version_sha256": browser["browser_version_sha256"],
        "ui_origin_sha256": browser["ui_origin_sha256"],
    }:
        raise QualificationError("browser identity drifted")
    bounds = report.get("bounds")
    if not isinstance(bounds, dict) or (
        bounds.get("max_duration_ms") != contract["bounds"]["max_browser_duration_ms"]
        or bounds.get("max_browser_actions") != contract["bounds"]["max_browser_actions"]
        or bounds.get("max_loopback_browser_responses") != contract["bounds"]["max_loopback_browser_responses"]
        or not isinstance(bounds.get("duration_ms"), int)
        or not 1 <= bounds["duration_ms"] <= bounds["max_duration_ms"]
        or not isinstance(bounds.get("browser_actions"), int)
        or not 10 <= bounds["browser_actions"] <= bounds["max_browser_actions"]
        or not isinstance(bounds.get("loopback_browser_responses"), int)
        or not 1 <= bounds["loopback_browser_responses"] <= bounds["max_loopback_browser_responses"]
    ):
        raise QualificationError("browser execution bound drifted")
    flow = report.get("flow")
    if not isinstance(flow, dict):
        raise QualificationError("browser semantic report missing")
    if flow.get("source_contract") != {
        "default_video_file": True,
        "values": ["Video File", "RTSP"],
        "rtsp_and_video_file_round_trip": True,
    }:
        raise QualificationError("source contract was not proven")
    if flow.get("filter_contract") != {
        "defaults": {"top_k": 10, "similarity": -1},
        "top_k_minimum": 1,
        "top_k_minimum_selected": True,
    }:
        raise QualificationError("filter contract was not proven")
    request_contract = flow.get("request_contract", {})
    if (
        request_contract.get("query_sha256") != contract["fixture"]["query_contract"]["sha256"]
        or request_contract.get("query_bytes") != contract["fixture"]["query_contract"]["bytes"]
        or request_contract.get("top_k") != 1
        or any(
            request_contract.get(key) is not True
            for key in ("source_type_video_file", "agent_mode_false", "empty_video_sources", "null_time_range")
        )
    ):
        raise QualificationError("Search request contract was not proven")
    critic = flow.get("critic_contract", {})
    if (
        critic.get("fixture_response_status") != 200
        or critic.get("fixture_response_intercepted_once") is not True
        or critic.get("input_order") != contract["fixture"]["response_input_order"]
        or critic.get("rendered_order") != contract["fixture"]["expected_render_order"]
        or critic.get("rendered_card_count") != 3
        or critic.get("similarities") != [-1, 0.25, 1]
    ):
        raise QualificationError("critic ordering contract was not proven")
    time_contract = flow.get("time_contract", {})
    if (
        time_contract.get("browser_time_zone_sha256")
        != _sha(contract["fixture"]["browser_time_zone"].encode("utf-8"))
        or time_contract.get("literal_local_time_sha256")
        != _sha(contract["fixture"]["literal_local_time"].encode("utf-8"))
        or time_contract.get("local_time_without_offset_conversion") is not True
    ):
        raise QualificationError("browser-local time contract was not proven")
    for viewport in ("desktop", "mobile"):
        value = flow.get(viewport, {}).get("overflow", {})
        if value.get("document", 1) > value.get("viewport", 0) or value.get("body", 1) > value.get("viewport", 0):
            raise QualificationError("horizontal overflow")
    diagnostics = flow.get("diagnostics", {})
    for key in (
        "console_error_hashes",
        "console_warning_hashes",
        "page_error_hashes",
        "request_failure_hashes",
        "failing_response_hashes",
    ):
        if diagnostics.get(key) != []:
            raise QualificationError("unexpected browser diagnostic")
    if diagnostics.get("expected_audio_probe_abort_count") != 1:
        raise QualificationError("Chat audio-probe teardown boundary drifted")
    for key in (
        "non_loopback_request_count",
        "non_loopback_response_count",
        "non_loopback_websocket_count",
        "framework_error_overlay_count",
    ):
        if diagnostics.get(key) != 0:
            raise QualificationError("browser boundary drifted")
    if report.get("cleanup") != {
        "isolated_browser_closed": True,
        "temporary_screenshot_deleted_after_hashing": True,
    }:
        raise QualificationError("browser cleanup failed")
    retained = json.dumps(report, sort_keys=True)
    forbidden = (
        "://",
        '"query":',
        '"prompt":',
        '"sensor_id":',
        '"object_id":',
        '"url":',
        '"vector":',
    )
    if any(item in retained for item in forbidden):
        raise QualificationError("browser report retained forbidden material")


def _execute(contract: dict[str, Any], acknowledgement: str) -> dict[str, Any]:
    if acknowledgement != ACK:
        raise QualificationError("authorization required")
    started = time.monotonic()
    commit = _run(["git", "rev-parse", "HEAD"], timeout=10, maximum=256).decode("ascii").strip()
    if commit != contract["target_commit"]:
        raise QualificationError("target commit drifted")
    source_hashes = _validate_source_locks(contract)
    selected_evidence = _verify_selected_evidence(contract)
    critic_evidence = _verify_critic_evidence(contract)
    pre_runtime = _runtime_snapshot(contract)
    pre_critic = _critic_runtime_state()
    browser_report, browser_process = _run_harness(contract)
    _validate_browser_report(contract, browser_report)
    post_critic = _critic_runtime_state()
    post_runtime = _runtime_snapshot(contract)
    if pre_runtime != post_runtime or pre_critic != post_critic:
        raise QualificationError("runtime changed during read-only qualification")
    duration_ms = round((time.monotonic() - started) * 1000)
    if duration_ms < 1 or duration_ms > contract["bounds"]["max_duration_ms"]:
        raise QualificationError("qualification deadline exceeded")
    receipt = {
        "schema_version": 1,
        "package_id": PACKAGE_ID,
        "status": "passed_current_candidate",
        "promotion_eligible": True,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "target_commit": commit,
        "contract_sha256": _sha_file(CONTRACT_PATH),
        "executor_sha256": _sha_file(Path(__file__).resolve()),
        "harness_sha256": _sha_file(HARNESS_PATH),
        "receipt_schema_sha256": _sha_file(SCHEMA_PATH),
        "identity": {
            "authorization_token_sha256": _sha(acknowledgement.encode("utf-8")),
            "source_hashes": source_hashes,
            "selected_object_evidence": selected_evidence,
            "critic_runtime_evidence": critic_evidence,
            "browser": browser_report["identity"],
            "browser_process": browser_process,
        },
        "pre_state": {"runtime": pre_runtime, "critic": pre_critic},
        "bounds": {
            "duration_ms": duration_ms,
            "browser_duration_ms": browser_report["bounds"]["duration_ms"],
            "browser_actions": browser_report["bounds"]["browser_actions"],
            "loopback_browser_responses": browser_report["bounds"]["loopback_browser_responses"],
            "persistent_mutations": 0,
            "max_duration_ms": contract["bounds"]["max_duration_ms"],
            "max_browser_duration_ms": contract["bounds"]["max_browser_duration_ms"],
            "max_browser_actions": contract["bounds"]["max_browser_actions"],
            "max_loopback_browser_responses": contract["bounds"]["max_loopback_browser_responses"],
            "max_persistent_mutations": 0,
        },
        "ui_semantics": browser_report["flow"],
        "post_state": {"runtime": post_runtime, "critic": post_critic},
        "cleanup": {
            "mutation": "read_only",
            "isolated_browser_closed": True,
            "temporary_screenshot_deleted_after_hashing": True,
            "runtime_unchanged": True,
            "selected_object_evidence_reverified": True,
            "critic_runtime_evidence_reverified": True,
            "persistent_mutations": 0,
            "warehouse_sample_bundle": "excluded",
        },
    }
    schema = _load_object(SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    errors = list(Draft202012Validator(schema).iter_errors(receipt))
    if errors:
        raise QualificationError(f"receipt schema failed: {errors[0].message}")
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
    source_hashes = _validate_source_locks(contract)
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
    execute = subparsers.add_parser("execute")
    execute.add_argument("--ack", required=True)
    execute.add_argument("--receipt", default=str(RECEIPT_PATH))
    args = parser.parse_args(argv)
    try:
        contract = _contract()
        command = args.command or "plan"
        if command == "plan":
            print(json.dumps(_plan(contract), sort_keys=True))
            return 0
        if command != "execute" or Path(args.receipt).resolve() != RECEIPT_PATH.resolve():
            raise QualificationError("invalid command")
        receipt = _execute(contract, args.ack)
        _atomic_write(receipt)
        print(
            json.dumps(
                {
                    "package_id": PACKAGE_ID,
                    "status": receipt["status"],
                    "promotion_eligible": receipt["promotion_eligible"],
                    "browser_actions": receipt["bounds"]["browser_actions"],
                    "persistent_mutations": 0,
                    "cleanup_complete": True,
                },
                sort_keys=True,
            )
        )
        return 0
    except (QualificationError, KeyError, OSError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "failed", "failure": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
