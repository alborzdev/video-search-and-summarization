"""Static and mock-only tests for the Video Management Playwright successor."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import stat
import sys
from typing import Any

import pytest


PACKAGE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "ui_video_playwright_executor", PACKAGE / "executor.py"
)
assert SPEC is not None and SPEC.loader is not None
executor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = executor
SPEC.loader.exec_module(executor)

ACK = "I_ACK_UI_VIDEO_MANAGEMENT_PLAYWRIGHT_RUNTIME"


def _manifest(tmp_path: Path) -> dict[str, Any]:
    run_id = "ui-vm-test-001"
    node = tmp_path / "node"
    node.write_bytes(b"reviewed-node-test-double")
    node.chmod(node.stat().st_mode | stat.S_IXUSR)
    playwright_root = tmp_path / "playwright"
    playwright_core_root = tmp_path / "playwright-core"
    playwright_root.mkdir()
    playwright_core_root.mkdir()
    playwright = playwright_root / "index.mjs"
    playwright.write_bytes(b"export const chromium = {};")
    (playwright_root / "package.json").write_text(
        json.dumps(
            {
                "name": "playwright",
                "version": "1.55.0",
                "dependencies": {"playwright-core": "1.55.0"},
            }
        )
    )
    (playwright_core_root / "package.json").write_text(
        json.dumps({"name": "playwright-core", "version": "1.55.0"})
    )
    mp4 = tmp_path / f"{run_id}.video-mp4.mp4"
    mkv = tmp_path / f"{run_id}.video-mkv.mkv"
    mp4.write_bytes(b"m" * (10 * 1024 * 1024 + 1))
    mkv.write_bytes(b"k" * (10 * 1024 * 1024 + 2))
    return {
        "schema_version": 1,
        "run_id": run_id,
        "ui_origin": "http://127.0.0.1:18000",
        "cdp_origin": "http://127.0.0.1:19222",
        "vst_origin": "http://127.0.0.1:18001",
        "agent_origin": "http://127.0.0.1:18002",
        "node_executable": str(node),
        "node_sha256": executor._digest(node.read_bytes()),
        "playwright_module": str(playwright),
        "playwright_sha256": executor._digest(playwright.read_bytes()),
        "playwright_packages": [
            {
                "name": "playwright",
                "path": str(playwright_root),
                "version": "1.55.0",
                "tree_sha256": executor._tree_digest(
                    playwright_root, "invalid_manifest"
                ),
            },
            {
                "name": "playwright-core",
                "path": str(playwright_core_root),
                "version": "1.55.0",
                "tree_sha256": executor._tree_digest(
                    playwright_core_root, "invalid_manifest"
                ),
            },
        ],
        "fixtures": [
            {
                "path": str(mp4),
                "sha256": executor._digest(mp4.read_bytes()),
                "extension": ".mp4",
            },
            {
                "path": str(mkv),
                "sha256": executor._digest(mkv.read_bytes()),
                "extension": ".mkv",
            },
        ],
        "owned_rtsp_name": f"{run_id}.rtsp-sensor",
        "template_field_name": "scenario",
    }


def _pass_result() -> dict[str, Any]:
    return {
        "status": "pass",
        "browser_actions": 23,
        "api_exchanges": 12,
        "semantic_checkpoints": 11,
        "checks": {
            "page_identity": True,
            "not_blank": True,
            "no_framework_overlay": True,
            "console_health": True,
            "desktop_screenshot": "a" * 64,
            "mobile_screenshot": "b" * 64,
            "interaction_proof": True,
            "mp4": True,
            "mkv": True,
            "multi_upload": True,
            "rtsp_positive": True,
            "rtsp_adjacent_negative": True,
            "upload_progress": True,
            "template_environment": True,
            "bulk_delete_confirm": True,
            "bulk_delete_cancel": True,
            "ordered_multichunk_protocol": True,
            "upload_payload_digest_integrity": True,
        },
        "cleanup": {
            "registered_owned_resources": 3,
            "deleted_owned_resources": 3,
            "owned_absent": True,
            "unrelated_state_restored": True,
        },
    }


def test_plan_is_inert_source_locked_and_honest_about_bounds() -> None:
    assert executor.compile_plan() == {
        "schema_version": 1,
        "package_id": "thor-ui-video-management-playwright-successor-v1",
        "status": "inert_plan_valid",
        "runtime_activity_performed": False,
        "selected_metadata_rows": 500,
        "selected_ui_state": "open_unexecuted_null_bound",
        "semantic_checkpoints": 11,
        "max_browser_actions": 40,
        "max_api_exchanges": 32,
        "browser_plugin": "absent_regular_playwright_fallback",
        "browser_launch_allowed": False,
        "playwright_entry_files_pinned": True,
        "playwright_transitive_graph_pinned": True,
        "canonical_bound": False,
        "executor_ready": False,
        "promotion_eligible": False,
        "warehouse_sample_bundle": "excluded",
    }


def test_harness_connects_only_to_preexisting_cdp_and_never_launches() -> None:
    source = (PACKAGE / "harness.mjs").read_text()
    assert "connectOverCDP" in source
    assert ".launch(" not in source
    assert "launchPersistentContext" not in source
    assert "browser.close(" not in source
    assert "process.exit(0)" in source
    assert "child_process" not in source
    assert "reconcileAndCleanup" in source
    assert "[...registered.entries()].reverse()" in source
    assert "input.owned_sensor_ids" not in source
    assert "uniqueNamedRow" in source
    assert "`${agentOrigin}/api/v1${path}`" in source
    assert "`${vstApiBase}/v1/storage/file`" in source
    assert "`${vstApiBase}/v1/replay/streams`" in source
    assert "postDataBuffer" not in source
    assert "XMLHttpRequest.prototype.send" in source
    assert 'crypto.subtle.digest("SHA-256", payload)' in source
    assert "chunk.payloadSha !== sha(expectedPayload)" in source
    assert "MAX_AGENT_DELETE_RESPONSE_BYTES = 64 * 1024" in source
    assert 'response.headers.get("content-length")' in source
    assert "new TextEncoder().encode(text).byteLength" in source
    assert 'value.status !== "success"' in source
    assert "value.video_id !== request.expectedIdentity" in source
    assert "value.name !== request.expectedName" in source
    assert "status !== 404" not in source
    assert "streams.length === 0" in source
    assert (
        'rows.push({ sensorId, streamId: "", name: "", emptySensor: true })' in source
    )
    assert "rows.push({ ...stream, sensorId, emptySensor: false })" in source
    assert "WORKFLOW_DEADLINE_MS = 175 * 1000" in source
    assert "CLEANUP_RESERVE_MS = 45 * 1000" in source
    assert "cleanupDeadline = workflowDeadline + CLEANUP_RESERVE_MS" in source
    assert "withinDeadline" in source
    assert source.count("AbortSignal.timeout(request.timeout)") == 2
    assert "timeout: 120000" not in source
    assert "readStreams(cleanupDeadline, CLEANUP_HTTP_TIMEOUT_MS)" in source
    assert "withinDeadline(() => page.close(), cleanupDeadline, 2000)" in source
    assert (
        source.count(
            'getByText("This deletion is irreversible and cannot be undone.", {'
        )
        == 2
    )
    assert (
        'const streamNames = fixtureNames.map((name) => name.replace(/\\.[^.]+$/, ""));'
        in source
    )
    assert "uniqueNamedRow(afterUpload, streamNames[index])" in source
    assert 'page.getByRole("button", { name: "Select All"' not in source


def test_authorization_precedes_manifest_file_reads_and_runner(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    Path(manifest["fixtures"][0]["path"]).unlink()
    called = False

    def runner(_value: Any) -> dict[str, Any]:
        nonlocal called
        called = True
        return _pass_result()

    with pytest.raises(executor.ExecutorError, match="authorization_required"):
        executor.execute(manifest=manifest, acknowledgement="wrong", runner=runner)
    assert called is False


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("ui_origin", "http://localhost:18000"),
        ("cdp_origin", "https://127.0.0.1:19222"),
        ("vst_origin", "http://192.168.1.2:18001"),
        ("agent_origin", "http://127.0.0.1:18002/base"),
    ],
)
def test_every_origin_is_numeric_loopback_http(
    tmp_path: Path, key: str, value: str
) -> None:
    manifest = _manifest(tmp_path)
    manifest[key] = value
    with pytest.raises(executor.ExecutorError, match="invalid_manifest"):
        executor.execute(
            manifest=manifest,
            acknowledgement=ACK,
            runner=lambda _value: _pass_result(),
        )


def test_ui_agent_and_vst_may_share_thor_public_origin(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    public = "http://127.0.0.1:17777"
    manifest["ui_origin"] = public
    manifest["agent_origin"] = public
    manifest["vst_origin"] = public
    receipt = executor.execute(
        manifest=manifest,
        acknowledgement=ACK,
        runner=lambda _value: _pass_result(),
    )
    assert receipt["status"] == "candidate_pass"


def test_cdp_must_remain_separate_from_public_origin(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    manifest["cdp_origin"] = manifest["ui_origin"]
    with pytest.raises(executor.ExecutorError, match="invalid_manifest"):
        executor.execute(
            manifest=manifest,
            acknowledgement=ACK,
            runner=lambda _value: _pass_result(),
        )


def test_fixture_and_rtsp_name_are_exactly_run_bound(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    manifest["owned_rtsp_name"] = "someone-elses-resource"
    with pytest.raises(executor.ExecutorError, match="invalid_manifest"):
        executor.execute(
            manifest=manifest,
            acknowledgement=ACK,
            runner=lambda _value: _pass_result(),
        )


def test_tool_and_fixture_digest_drift_fails_before_runner(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    manifest["playwright_sha256"] = "f" * 64
    called = False

    def runner(_value: Any) -> dict[str, Any]:
        nonlocal called
        called = True
        return _pass_result()

    with pytest.raises(executor.ExecutorError, match="invalid_manifest"):
        executor.execute(manifest=manifest, acknowledgement=ACK, runner=runner)
    assert called is False


def test_playwright_tree_drift_fails_before_runner(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    root = Path(manifest["playwright_packages"][1]["path"])
    (root / "unexpected.js").write_text("unreviewed")
    with pytest.raises(executor.ExecutorError, match="invalid_manifest"):
        executor.execute(
            manifest=manifest,
            acknowledgement=ACK,
            runner=lambda _value: _pass_result(),
        )


def test_each_fixture_must_cross_the_real_ten_mib_chunk_boundary(
    tmp_path: Path,
) -> None:
    manifest = _manifest(tmp_path)
    fixture = Path(manifest["fixtures"][0]["path"])
    fixture.write_bytes(b"single-chunk")
    manifest["fixtures"][0]["sha256"] = executor._digest(fixture.read_bytes())
    with pytest.raises(executor.ExecutorError, match="invalid_manifest"):
        executor.execute(
            manifest=manifest,
            acknowledgement=ACK,
            runner=lambda _value: _pass_result(),
        )


def test_declared_source_lock_digest_drift_fails_plan(monkeypatch: Any) -> None:
    original = executor._read_regular

    def drift(path: Path, maximum: int, code: str, **kwargs: Any) -> bytes:
        raw = original(path, maximum, code, **kwargs)
        if str(path).endswith(
            "services/ui/packages/common/lib-src/utils/chunkedUpload.ts"
        ):
            return raw + b"drift"
        return raw

    monkeypatch.setattr(executor, "_read_regular", drift)
    with pytest.raises(executor.ExecutorError, match="configuration_error"):
        executor.compile_plan()


def test_pass_receipt_is_strict_sanitized_and_nonpromoting(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    receipt = executor.execute(
        manifest=manifest,
        acknowledgement=ACK,
        runner=lambda _value: _pass_result(),
    )
    assert receipt["status"] == "candidate_pass"
    assert receipt["budget"] == {
        "semantic_checkpoints": 11,
        "browser_actions": 23,
        "api_exchanges": 12,
        "max_browser_actions": 40,
        "max_api_exchanges": 32,
        "max_duration_seconds": 240,
    }
    assert receipt["canonical_bound"] is False
    assert receipt["executor_ready"] is False
    assert receipt["promotion_eligible"] is False
    assert receipt["playwright_transitive_graph_pinned"] is True
    assert receipt["playwright_tree_sha256"] == [
        row["tree_sha256"] for row in manifest["playwright_packages"]
    ]
    serialized = json.dumps(receipt, sort_keys=True)
    assert manifest["run_id"] not in serialized
    assert manifest["ui_origin"] not in serialized
    assert manifest["node_executable"] not in serialized
    assert manifest["fixtures"][0]["path"] not in serialized
    assert manifest["owned_rtsp_name"] not in serialized
    assert manifest["template_field_name"] not in serialized


@pytest.mark.parametrize(
    "mutator",
    [
        lambda value: value.update(browser_actions=41),
        lambda value: value.update(api_exchanges=33),
        lambda value: value["checks"].update(console_health=False),
        lambda value: value["cleanup"].update(unrelated_state_restored=False),
        lambda value: value.update(raw_url="http://127.0.0.1:18000"),
    ],
)
def test_incomplete_oversized_or_extra_harness_result_fails_closed(
    tmp_path: Path, mutator: Any
) -> None:
    manifest = _manifest(tmp_path)
    result = _pass_result()
    mutator(result)
    with pytest.raises(executor.ExecutorError, match="browser_oracle_failed"):
        executor.execute(
            manifest=manifest,
            acknowledgement=ACK,
            runner=lambda _value: result,
        )
