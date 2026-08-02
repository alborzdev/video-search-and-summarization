"""Mock-only tests for the bounded LVS HTTP semantic successor."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping
from urllib.parse import urlsplit

import pytest


PACKAGE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "lvs_semantic_http_executor", PACKAGE / "executor.py"
)
assert SPEC is not None and SPEC.loader is not None
executor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = executor
SPEC.loader.exec_module(executor)

ACK = "I_ACK_LVS_HTTP_RUNTIME_AND_EXACT_TWO_FILE_CLEANUP"


class FakeTransport:
    proxies_enabled = False
    redirects_enabled = False

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.files: dict[str, dict[str, Any]] = {
            "00000000-0000-4000-8000-000000000001": {
                "id": "00000000-0000-4000-8000-000000000001",
                "bytes": 4,
                "filename": "unrelated.mp4",
                "purpose": "vision",
                "media_type": "video",
                "creation_time": None,
                "sensor_name": "unrelated",
            }
        }
        self.fail_report = False
        self.delete_failures = 0

    @staticmethod
    def _part(body: bytes, name: str) -> str:
        pattern = rb'name="' + name.encode() + rb'"\r\n\r\n([^\r]+)\r\n'
        match = re.search(pattern, body)
        assert match is not None
        return match.group(1).decode()

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> executor.Response:
        del timeout_seconds, max_response_bytes
        parsed = urlsplit(url)
        path = parsed.path
        self.calls.append((method, path))
        assert parsed.hostname == "127.0.0.1"
        assert "Authorization" not in headers

        if method == "GET" and path == "/v1/ready":
            return executor.Response(200, b"")
        if method == "GET" and path == "/models":
            return self._json(200, {"object": "list", "data": [{"id": "local-model"}]})
        if method == "GET" and path == "/files":
            assert parsed.query == "purpose=vision"
            return self._json(
                200, {"object": "list", "data": list(self.files.values())}
            )
        if method == "POST" and path == "/files":
            assert body is not None
            assert headers["Content-Type"].startswith("multipart/form-data; boundary=")
            file_id = self._part(body, "id")
            sensor = self._part(body, "sensor_name")
            filename_match = re.search(rb'name="file"; filename="([^"]+)"', body)
            media_match = re.search(
                rb"Content-Type: video/mp4\r\n\r\n(.*?)\r\n--vss-lvs-", body, re.DOTALL
            )
            assert filename_match is not None and media_match is not None
            row = {
                "id": file_id,
                "bytes": len(media_match.group(1)),
                "filename": filename_match.group(1).decode(),
                "purpose": "vision",
                "media_type": "video",
                "creation_time": None,
                "sensor_name": sensor,
            }
            self.files[file_id] = row
            return self._json(200, row)
        if method == "GET" and path.startswith("/files/"):
            file_id = path.rsplit("/", 1)[1]
            row = dict(self.files[file_id])
            row.pop("media_type")
            return self._json(200, row)
        if method == "POST" and path == "/v1/summarize":
            assert body is not None
            request = json.loads(body)
            if self.fail_report:
                return self._json(
                    500, {"code": "InternalServerError", "message": "redacted"}
                )
            content = json.dumps(
                {"video_summary": "A tiny local fixture is visible.", "events": []}
            )
            return self._json(
                200,
                {
                    "id": "00000000-0000-4000-8000-000000000099",
                    "video_id": request["id"],
                    "model": request["model"],
                    "choices": [{"message": {"content": content}}],
                },
            )
        if method == "DELETE" and path.startswith("/files/"):
            file_id = path.rsplit("/", 1)[1]
            assert file_id in self.files
            if self.delete_failures:
                self.delete_failures -= 1
                return self._json(
                    503, {"code": "DependencyError", "message": "redacted"}
                )
            del self.files[file_id]
            return self._json(200, {"id": file_id, "object": "file", "deleted": True})
        raise AssertionError((method, path))

    @staticmethod
    def _json(status: int, value: Any) -> executor.Response:
        return executor.Response(status, json.dumps(value, sort_keys=True).encode())


def _manifest(tmp_path: Path) -> dict[str, Any]:
    first = tmp_path / "first.mp4"
    second = tmp_path / "second.mp4"
    first.write_bytes(b"tiny-one")
    second.write_bytes(b"tiny-two-different")
    return {
        "schema_version": 1,
        "run_id": "lvs-http-test-001",
        "lvs_origin": "http://127.0.0.1:38111",
        "model": "local-model",
        "scenario": "activity monitoring",
        "events": ["notable activity"],
        "fixtures": [
            {"path": str(first), "sha256": executor._digest(first.read_bytes())},
            {"path": str(second), "sha256": executor._digest(second.read_bytes())},
        ],
    }


def test_plan_preserves_open_500_row_and_reports_partial_boundary() -> None:
    assert executor.compile_plan() == {
        "schema_version": 1,
        "package_id": "thor-vss-lvs-semantic-runtime-http-successor-v1",
        "status": "inert_plan_valid",
        "runtime_requests": 0,
        "runtime_actions": 0,
        "request_bound": 14,
        "action_bound": 14,
        "selected_metadata_rows": 500,
        "selected_metadata_lvs_state": "open_unexecuted_null_bound",
        "concrete_complete_actions": 1,
        "concrete_partial_actions": 5,
        "residual_adapter_actions": 8,
        "executor_ready": False,
        "promotion_eligible": False,
        "warehouse_sample_bundle": "excluded",
    }


def test_authorization_precedes_fixture_reads_and_transport(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    Path(manifest["fixtures"][0]["path"]).unlink()
    transport = FakeTransport()
    with pytest.raises(executor.ExecutorError, match="authorization_required"):
        executor.execute(
            manifest=manifest, acknowledgement="wrong", transport=transport
        )
    assert transport.calls == []


def test_success_is_exact_14_request_sanitized_candidate(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    transport = FakeTransport()
    receipt = executor.execute(
        manifest=manifest, acknowledgement=ACK, transport=transport
    )
    assert receipt["status"] == "candidate_pass"
    assert receipt["budget"] == {
        "requests": 14,
        "max_requests": 14,
        "actions": 14,
        "max_actions": 14,
        "max_duration_seconds": 900,
    }
    assert receipt["executor_ready"] is receipt["promotion_eligible"] is False
    assert receipt["semantic_coverage"]["concrete_complete"] == ["setup-owned-fixtures"]
    assert len(receipt["semantic_coverage"]["concrete_partial"]) == 5
    assert len(receipt["semantic_coverage"]["residual_adapter_required"]) == 8
    assert receipt["cleanup"] == {
        "registered_owned_files": 2,
        "deleted_owned_files": 2,
        "owned_absent": True,
        "unrelated_state_restored": True,
        "exact_delete_confirmations": True,
    }
    assert len(transport.files) == 1
    assert len(transport.calls) == 14
    serialized = json.dumps(receipt, sort_keys=True)
    assert manifest["run_id"] not in serialized
    assert manifest["lvs_origin"] not in serialized
    assert manifest["fixtures"][0]["path"] not in serialized
    assert "/files/{owned_file_id}" in serialized


def test_report_failure_still_deletes_both_exact_owned_files(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    transport = FakeTransport()
    transport.fail_report = True
    with pytest.raises(executor.ExecutorError, match="oracle_failed"):
        executor.execute(manifest=manifest, acknowledgement=ACK, transport=transport)
    assert list(transport.files) == ["00000000-0000-4000-8000-000000000001"]
    assert [method for method, _path in transport.calls].count("DELETE") == 2


def test_cleanup_failure_still_attempts_every_registered_file(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    transport = FakeTransport()
    transport.delete_failures = 1
    with pytest.raises(executor.ExecutorError, match="cleanup_failed"):
        executor.execute(manifest=manifest, acknowledgement=ACK, transport=transport)
    assert [method for method, _path in transport.calls].count("DELETE") == 2
    assert (
        len(transport.files) == 2
    )  # unrelated sentinel plus the one whose delete failed


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:38111",
        "http://192.168.1.4:38111",
        "https://127.0.0.1:38111",
        "http://127.0.0.1:38111/base",
        "http://user@127.0.0.1:38111",
    ],
)
def test_origin_is_numeric_loopback_http_only(tmp_path: Path, origin: str) -> None:
    manifest = _manifest(tmp_path)
    manifest["lvs_origin"] = origin
    transport = FakeTransport()
    with pytest.raises(executor.ExecutorError, match="invalid_manifest"):
        executor.execute(manifest=manifest, acknowledgement=ACK, transport=transport)
    assert transport.calls == []


def test_fixture_digest_mismatch_precedes_transport(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    manifest["fixtures"][0]["sha256"] = "f" * 64
    transport = FakeTransport()
    with pytest.raises(executor.ExecutorError, match="invalid_manifest"):
        executor.execute(manifest=manifest, acknowledgement=ACK, transport=transport)
    assert transport.calls == []


@pytest.mark.parametrize(("proxies", "redirects"), [(True, False), (False, True)])
def test_transport_policy_fails_closed_before_activity(
    tmp_path: Path, proxies: bool, redirects: bool
) -> None:
    manifest = _manifest(tmp_path)
    transport = FakeTransport()
    transport.proxies_enabled = proxies
    transport.redirects_enabled = redirects
    with pytest.raises(executor.ExecutorError, match="invalid_manifest"):
        executor.execute(manifest=manifest, acknowledgement=ACK, transport=transport)
    assert transport.calls == []
