"""Adversarial, side-effect-free tests for the UI runtime evidence contract."""

from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

import pytest

LANE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "ui_runtime_validator", LANE / "validator.py"
)
assert SPEC and SPEC.loader
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


def digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def resource_snapshot(timestamp: str, label: str) -> dict:
    return {
        "captured_at": timestamp,
        "thor_detected": True,
        "cgroup_admitted": True,
        "memory_total_bytes": 10 * 1024**3,
        "memory_available_bytes": 5 * 1024**3,
        "memory_required_bytes": 2 * 1024**3,
        "memory_reserve_percent": 20,
        "disk_free_bytes": 3 * 1024**3,
        "disk_required_bytes": 1024**3,
        "gpu_required": False,
        "endpoints_healthy": True,
        "gate_passed": True,
        "receipt_sha256": digest(f"resource-{label}"),
    }


def endpoint(endpoint_id: str, port: int) -> dict:
    return {
        "endpoint_id": endpoint_id,
        "scheme": "http",
        "host": "127.0.0.1",
        "port": port,
        "base_path_sha256": digest(f"base-path-{endpoint_id}"),
        "preexisting": True,
        "healthy": True,
        "started_by_run": False,
        "tls_verified": False,
    }


def browser(label: str, actions: int) -> dict:
    return {
        "driver": "playwright",
        "driver_version_sha256": digest("driver-version"),
        "ui_endpoint_id": "ui-origin",
        "navigation_origin_sha256": digest("ui-origin"),
        "rendered_ui_observed": True,
        "dom_actions_observed": True,
        "api_only": False,
        "action_count": actions,
        "trace_sha256": digest(f"trace-{label}"),
        "dom_snapshot_sha256": digest(f"dom-{label}"),
        "screenshot_sha256": digest(f"screenshot-{label}"),
        "console_error_count": 0,
        "network_error_count": 0,
        "sanitized": True,
    }


def exchange(
    label: str,
    endpoint_id: str,
    requested: str,
    responded: str,
    run_id: str,
    authorization_id: str,
    status: int = 200,
) -> dict:
    return {
        "exchange_id": f"exchange-{label}",
        "correlation_id": f"correlation-{label}",
        "request_at": requested,
        "response_at": responded,
        "method": "GET",
        "path_sha256": digest(f"path-{label}"),
        "request_body_sha256": digest(f"request-{label}"),
        "response_status": status,
        "response_body_sha256": digest(f"response-{label}"),
        "endpoint_id": endpoint_id,
        "run_id": run_id,
        "authorization_id": authorization_id,
        "sanitized": True,
        "raw_headers_recorded": False,
        "raw_url_recorded": False,
    }


def fixture(
    fixture_id: str,
    kind: str,
    media_type: str,
    run_id: str,
    size: int,
    index: int,
) -> dict:
    extension = {
        "application/json": "json",
        "video/mp4": "mp4",
        "video/x-matroska": "mkv",
    }[media_type]
    return {
        "fixture_id": fixture_id,
        "run_id": run_id,
        "kind": kind,
        "media_type": media_type,
        "generated_locally": True,
        "operator_custom": False,
        "warehouse_sample_bundle": False,
        "artifact_name": f"{run_id}.{fixture_id}.{extension}",
        "sha256": digest(f"fixture-{index}"),
        "size_bytes": size,
        "generator_receipt_sha256": digest(f"generator-{index}"),
        "contains_secret_material": False,
    }


def complete_evidence() -> dict:
    run_id = "uiq-abcdefghijkl"
    authorization_id = "uia-abcdefghijklmnop"
    commit = "1" * 40
    scope = {
        "package_id": "thor-ui-runtime-contracts-v1",
        "run_id": run_id,
        "repository_commit": commit,
        "endpoint_ids": ["ui-origin", "alerts-mock", "search-mock", "video-mock"],
        "max_total_duration_seconds": 900,
        "browser_api_only": True,
        "lifecycle_allowed": False,
    }
    alert_exchanges = [
        exchange(
            f"alert-{index}",
            "alerts-mock",
            "2026-08-01T10:01:10Z",
            "2026-08-01T10:01:11Z",
            run_id,
            authorization_id,
        )
        for index in range(2)
    ]
    search_exchanges = [
        exchange(
            f"search-{index}",
            "search-mock",
            "2026-08-01T10:03:10Z",
            "2026-08-01T10:03:11Z",
            run_id,
            authorization_id,
        )
        for index in range(3)
    ]
    video_exchanges = [
        exchange(
            f"video-{index}",
            "video-mock",
            "2026-08-01T10:05:10Z",
            "2026-08-01T10:05:11Z",
            run_id,
            authorization_id,
            status=404 if index == 4 else 200,
        )
        for index in range(5)
    ]
    owned = [
        f"{run_id}.alert-friendly",
        f"{run_id}.alert-custom",
        f"{run_id}.search-session",
        f"{run_id}.video-mp4",
        f"{run_id}.video-mkv",
        f"{run_id}.rtsp-sensor",
    ]
    same_preexisting_digest = digest("preexisting-state")
    return {
        "schema_version": 1,
        "mode": "future_sanitized_browser_api_evidence",
        "package_id": "thor-ui-runtime-contracts-v1",
        "plan_sha256": validator.canonical_sha256(validator.compile_plan()),
        "run_id": run_id,
        "authorization": {
            "authorization_id": authorization_id,
            "run_id": run_id,
            "acknowledgement": "I_ACCEPT_UI_BROWSER_API_QUALIFICATION_RUN",
            "scope": scope,
            "scope_sha256": validator.canonical_sha256(scope),
            "granted_at": "2026-08-01T09:59:00Z",
            "expires_at": "2026-08-01T10:15:00Z",
            "single_use": True,
            "inherited": False,
        },
        "target": {
            "platform": "nvidia-jetson-thor",
            "repository_commit": commit,
            "host_identity_sha256": digest("host"),
            "browser_name": "chromium",
            "browser_version_sha256": digest("browser-version"),
            "ui_build_sha256": digest("ui-build"),
        },
        "preflight": resource_snapshot("2026-08-01T10:00:00Z", "pre"),
        "endpoints": [
            endpoint("ui-origin", 31000),
            endpoint("alerts-mock", 31001),
            endpoint("search-mock", 31002),
            endpoint("video-mock", 31003),
        ],
        "fixtures": [
            fixture(
                "ui-alert-api",
                "generated_mock_json",
                "application/json",
                run_id,
                512,
                0,
            ),
            fixture(
                "ui-search-api",
                "generated_mock_json",
                "application/json",
                run_id,
                768,
                1,
            ),
            fixture(
                "ui-tiny-mp4", "generated_tiny_media", "video/mp4", run_id, 4096, 2
            ),
            fixture(
                "ui-tiny-mkv",
                "generated_tiny_media",
                "video/x-matroska",
                run_id,
                4096,
                3,
            ),
            fixture(
                "ui-tiny-rtsp-inventory",
                "generated_mock_json",
                "application/json",
                run_id,
                512,
                4,
            ),
        ],
        "cases": [
            {
                "case_id": "ui-runtime.alerts",
                "planning_requirement_id": "ui-alert-api",
                "capability_id": "runtime.ui.alerts-tab",
                "oracle_id": "oracle.runtime.ui.alerts-tab",
                "run_id": run_id,
                "authorization_id": authorization_id,
                "endpoint_id": "alerts-mock",
                "started_at": "2026-08-01T10:01:00Z",
                "finished_at": "2026-08-01T10:02:00Z",
                "browser": browser("alerts", 20),
                "api_exchanges": alert_exchanges,
                "observations": {
                    "views": ["View Alerts", "Manage Alerts"],
                    "defaults": {
                        "verified_only": True,
                        "range_minutes": 10,
                        "fetch_count": 100,
                        "refresh_seconds": 1,
                        "rows": 20,
                        "max_search": "unlimited",
                        "bbox_overlay": False,
                    },
                    "create_rule_refreshed_live_streams": True,
                    "friendly_sensor_name_sha256": digest("friendly-name"),
                    "friendly_catalog_rtsp_url_sha256": digest("friendly-rtsp"),
                    "friendly_submitted_sensor_sha256": digest("friendly-rtsp"),
                    "custom_sensor_name_sha256": digest("custom-name"),
                    "custom_submitted_sensor_sha256": digest("custom-name"),
                    "custom_rtsp_url_forwarded": False,
                    "created_resource_ids": owned[:2],
                    "browser_step_ids_sha256": digest("alert-browser-steps"),
                },
            },
            {
                "case_id": "ui-runtime.search",
                "planning_requirement_id": "ui-search-api",
                "capability_id": "runtime.ui.search-tab",
                "oracle_id": "oracle.runtime.ui.search-tab",
                "run_id": run_id,
                "authorization_id": authorization_id,
                "endpoint_id": "search-mock",
                "started_at": "2026-08-01T10:03:00Z",
                "finished_at": "2026-08-01T10:04:00Z",
                "browser": browser("search", 22),
                "api_exchanges": search_exchanges,
                "observations": {
                    "source_default": "Video File",
                    "source_values": ["Video File", "RTSP"],
                    "time_zone": "browser_local_no_conversion",
                    "similarity_range": [-1, 1],
                    "top_k_default": 10,
                    "top_k_minimum": 1,
                    "critic_default_enabled": True,
                    "critic_disable_env_tested": "ENABLE_CRITIC=false",
                    "critic_sort_order": ["confirmed", "unverified", "rejected"],
                    "image_requirements_observed": [
                        "mediaWithObjectsBbox",
                        "mdx_frames_endpoint",
                        "vst_picture_api",
                    ],
                    "bbox_rendered": True,
                    "frame_response_sha256": search_exchanges[0][
                        "response_body_sha256"
                    ],
                    "picture_response_sha256": search_exchanges[1][
                        "response_body_sha256"
                    ],
                    "created_resource_ids": owned[2:3],
                    "browser_step_ids_sha256": digest("search-browser-steps"),
                },
            },
            {
                "case_id": "ui-runtime.video-management",
                "planning_requirement_id": "ui-tiny-media",
                "capability_id": "runtime.ui.video-management-tab",
                "oracle_id": "oracle.runtime.ui.video-management-tab",
                "run_id": run_id,
                "authorization_id": authorization_id,
                "endpoint_id": "video-mock",
                "started_at": "2026-08-01T10:05:00Z",
                "finished_at": "2026-08-01T10:07:00Z",
                "browser": browser("video", 30),
                "api_exchanges": video_exchanges,
                "observations": {
                    "file_types": ["MP4", "MKV"],
                    "multi_upload_observed": True,
                    "rtsp_add_list_delete_observed": True,
                    "bulk_delete_warning": "irreversible",
                    "bulk_delete_confirmed": True,
                    "upload_progress_percent": [0, 20, 80, 100],
                    "optional_template_environment_observed": True,
                    "repeated_delete_status": 404,
                    "created_resource_ids": owned[3:],
                    "browser_step_ids_sha256": digest("video-browser-steps"),
                },
            },
        ],
        "cleanup": {
            "completed_at": "2026-08-01T10:08:00Z",
            "preexisting_resource_ids": ["operator-preexisting-resource"],
            "preexisting_state_before_sha256": same_preexisting_digest,
            "preexisting_state_after_sha256": same_preexisting_digest,
            "owned_resource_ids": owned,
            "deleted_resource_ids": owned,
            "absent_after_resource_ids": owned,
            "delete_receipt_sha256": digest("delete-receipt"),
            "only_exact_owned_deleted": True,
            "repeated_video_delete_observed": True,
            "mock_endpoints_stopped": False,
            "service_state_mutated": False,
        },
        "postflight": resource_snapshot("2026-08-01T10:09:00Z", "post"),
        "boundary": {
            "generated_by_package": False,
            "api_mocks_counted_as_rendered_ui": False,
            "browser_level_observations_present": True,
            "external_network_used": False,
            "dns_used": False,
            "docker_used": False,
            "subprocess_used_by_package": False,
            "process_lifecycle_used_by_package": False,
            "credentials_used": False,
            "secret_material_recorded": False,
            "raw_urls_recorded": False,
            "warehouse_used": False,
            "live_state_promoted": False,
        },
    }


def rejected(evidence: dict, message: str) -> None:
    with pytest.raises(validator.UIContractError, match=message):
        validator.validate_evidence(evidence)


def test_plan_pins_exact_open_denominator_and_remains_inert() -> None:
    plan = validator.compile_plan()
    assert plan["source_lock_count"] == 4
    assert plan["requirement_count"] == 3
    assert plan["fixture_count"] == 5
    assert plan["required_endpoint_ids"] == [
        "ui-origin",
        "alerts-mock",
        "search-mock",
        "video-mock",
    ]
    assert plan["executor"] is None
    assert plan["runtime_evidence"] == []
    assert plan["live_state_advanced"] is False
    assert all(row["browser_rendering_required"] for row in plan["requirements"])
    assert not any(
        row["api_mock_transcript_alone_admissible"] for row in plan["requirements"]
    )


def test_validator_has_no_runtime_or_process_client_surface() -> None:
    source = (LANE / "validator.py").read_text()
    tree = ast.parse(source)
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not imported & {
        "requests",
        "httpx",
        "urllib",
        "socket",
        "subprocess",
        "playwright",
        "selenium",
        "docker",
    }
    assert "execute" not in {
        constant.value
        for constant in ast.walk(tree)
        if isinstance(constant, ast.Constant) and constant.value == "execute"
    }
    assert "os.system" not in source
    assert "os.popen" not in source


def test_complete_future_receipt_validates_but_is_non_admitting() -> None:
    result = validator.validate_evidence(complete_evidence())
    assert result == {
        "schema_version": 1,
        "package_id": "thor-ui-runtime-contracts-v1",
        "run_id": "uiq-abcdefghijkl",
        "authorization_id": "uia-abcdefghijklmnop",
        "validated_case_count": 3,
        "validated_fixture_count": 5,
        "validated_endpoint_count": 4,
        "validated_api_exchange_count": 10,
        "browser_rendering_required": True,
        "api_mock_transcript_alone_admissible": False,
        "cleanup_verified": True,
        "candidate_evidence_only": True,
        "live_state_advanced": False,
    }


def test_default_cli_is_plan_only(capsys: pytest.CaptureFixture[str]) -> None:
    assert validator.main([]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["mode"] == "nonexecuting_future_evidence_plan"
    assert result["executor"] is None


def test_strict_json_rejects_duplicate_keys_and_nonfinite_values() -> None:
    with pytest.raises(validator.UIContractError, match="duplicate JSON key"):
        validator._strict_json(b'{"a":1,"a":2}', "test")
    with pytest.raises(validator.UIContractError, match="non-finite"):
        validator._strict_json(b'{"a":NaN}', "test")


def test_source_lock_drift_fails_closed(tmp_path: Path) -> None:
    contract = json.loads((LANE / "contract.json").read_text())
    for lock in contract["source_locks"]:
        source = validator.REPO_ROOT / lock["path"]
        target = tmp_path / lock["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    acceptance = tmp_path / contract["source_locks"][0]["path"]
    acceptance.write_bytes(acceptance.read_bytes() + b"\n")
    with pytest.raises(validator.UIContractError, match="raw SHA-256 mismatch"):
        validator.compile_plan(tmp_path)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda value: value.__setitem__("plan_sha256", digest("wrong-plan")),
            "plan identity",
        ),
        (
            lambda value: value["authorization"].__setitem__("acknowledgement", "NO"),
            "schema violation",
        ),
        (
            lambda value: value["authorization"].__setitem__(
                "run_id", "uiq-zzzzzzzzzzzz"
            ),
            "run identity",
        ),
        (
            lambda value: value["authorization"].__setitem__(
                "scope_sha256", digest("wrong-scope")
            ),
            "scope digest",
        ),
        (
            lambda value: value["endpoints"][0].__setitem__("host", "localhost"),
            "schema violation",
        ),
        (
            lambda value: value["endpoints"][3].__setitem__("port", 31002),
            "four-endpoint",
        ),
        (
            lambda value: value["endpoints"][0].__setitem__("tls_verified", True),
            "incoherent TLS",
        ),
        (lambda value: value["fixtures"].reverse(), "five-fixture"),
        (
            lambda value: value["fixtures"][0].__setitem__(
                "artifact_name", "unbound.json"
            ),
            "artifact name",
        ),
        (
            lambda value: value["fixtures"][0].__setitem__("size_bytes", 1048577),
            "size bound",
        ),
        (
            lambda value: value["fixtures"][3].__setitem__(
                "sha256", value["fixtures"][2]["sha256"]
            ),
            "distinct artifacts",
        ),
        (
            lambda value: value["preflight"].__setitem__(
                "memory_available_bytes", 3 * 1024**3
            ),
            "memory gate",
        ),
        (
            lambda value: value["preflight"].__setitem__(
                "disk_free_bytes", 2 * 1024**3 - 1
            ),
            "disk gate",
        ),
        (
            lambda value: value["cases"][1].__setitem__(
                "started_at", "2026-08-01T10:01:30Z"
            ),
            "overlaps",
        ),
        (
            lambda value: value["cases"][0]["browser"].__setitem__("api_only", True),
            "schema violation",
        ),
        (
            lambda value: value["cases"][0]["browser"].__setitem__(
                "rendered_ui_observed", False
            ),
            "schema violation",
        ),
        (
            lambda value: value["cases"][0]["browser"].__setitem__("action_count", 33),
            "action bound",
        ),
        (
            lambda value: value["cases"][0]["api_exchanges"][0].__setitem__(
                "endpoint_id", "search-mock"
            ),
            "escaped",
        ),
        (
            lambda value: value["cases"][0]["api_exchanges"][0].__setitem__(
                "run_id", "uiq-zzzzzzzzzzzz"
            ),
            "not run/authorization-bound",
        ),
        (
            lambda value: value["cases"][0]["api_exchanges"][0].__setitem__(
                "request_at", "2026-08-01T10:02:30Z"
            ),
            "timing escaped",
        ),
        (
            lambda value: value["cases"][1]["api_exchanges"][0].__setitem__(
                "exchange_id", "exchange-alert-0"
            ),
            "duplicate API exchange",
        ),
        (
            lambda value: value["cases"][0]["observations"].__setitem__(
                "friendly_submitted_sensor_sha256", digest("wrong")
            ),
            "friendly sensor",
        ),
        (
            lambda value: value["cases"][1]["observations"].__setitem__(
                "frame_response_sha256", digest("uncorrelated")
            ),
            "not API-correlated",
        ),
        (
            lambda value: value["cases"][2]["observations"].__setitem__(
                "upload_progress_percent", [0, 80, 40, 100]
            ),
            "monotonic",
        ),
        (
            lambda value: value["cleanup"]["preexisting_resource_ids"].append(
                value["cleanup"]["owned_resource_ids"][0]
            ),
            "collided",
        ),
        (
            lambda value: value["cleanup"]["deleted_resource_ids"].reverse(),
            "resource set mismatch",
        ),
        (
            lambda value: value["cleanup"].__setitem__(
                "preexisting_state_after_sha256", digest("changed")
            ),
            "not restored",
        ),
        (
            lambda value: value["cleanup"].__setitem__(
                "completed_at", "2026-08-01T10:16:00Z"
            ),
            "escaped authorization",
        ),
        (
            lambda value: value["cleanup"]["preexisting_resource_ids"].append(
                "http://outside.invalid"
            ),
            "URL or secret-like",
        ),
        (
            lambda value: value["cleanup"]["preexisting_resource_ids"].append(
                "Bearer secret-value"
            ),
            "URL or secret-like",
        ),
    ],
)
def test_adversarial_receipts_fail_closed(mutation, message: str) -> None:
    evidence = deepcopy(complete_evidence())
    mutation(evidence)
    rejected(evidence, message)
