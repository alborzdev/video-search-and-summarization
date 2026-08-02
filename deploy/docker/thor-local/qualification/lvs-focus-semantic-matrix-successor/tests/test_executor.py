"""Fake-only tests for the bounded LVS focus semantic matrix."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping
from urllib.parse import urlsplit
from uuid import uuid5, UUID

import pytest


PACKAGE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "lvs_focus_executor", PACKAGE / "executor.py"
)
assert SPEC is not None and SPEC.loader is not None
executor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = executor
SPEC.loader.exec_module(executor)

ACK = "I_ACK_LVS_FOCUS_MATRIX_AND_EXACT_FILE_CLEANUP"
TERMS = {
    "neutral_scenario": "general observation",
    "target_object": "amber target crate",
    "target_event": "clockwise target rotation",
    "target_scenario": "inspection target station",
    "target_relationship": "target crate rotation relationship",
    "distractor_object": "violet distractor cone",
    "distractor_event": "distractor light blinking",
    "absent_object": "absent silver bicycle",
    "absent_event": "absent bicycle jumping",
}
UNRELATED_ID = "00000000-0000-4000-8000-000000000001"


class FakeTransport:
    proxies_enabled = False
    redirects_enabled = False

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.files: dict[str, dict[str, Any]] = {
            UNRELATED_ID: {
                "id": UNRELATED_ID,
                "bytes": 4,
                "filename": "unrelated.mp4",
                "purpose": "vision",
                "media_type": "video",
                "creation_time": None,
                "sensor_name": "unrelated",
            }
        }
        self.matrix_calls = 0
        self.matrix_requests: list[dict[str, Any]] = []
        self.bad_case: str | None = None
        self.bad_mode: str | None = None
        self.delete_failure = False

    @staticmethod
    def _json(status: int, value: Any) -> executor.Response:
        return executor.Response(status, json.dumps(value, sort_keys=True).encode())

    @staticmethod
    def _part(body: bytes, name: str) -> str:
        match = re.search(rb'name="' + name.encode() + rb'"\r\n\r\n([^\r]+)\r\n', body)
        assert match is not None
        return match.group(1).decode()

    @staticmethod
    def _description(assertion: str) -> str:
        values = {
            "target_object": TERMS["target_object"],
            "target_event": TERMS["target_event"],
            "target_scenario": TERMS["target_scenario"],
            "target_relationship": " ".join(
                [
                    TERMS["target_object"],
                    TERMS["target_event"],
                    TERMS["target_scenario"],
                    TERMS["target_relationship"],
                ]
            ),
            "distractor_object": TERMS["distractor_object"],
            "distractor_event": TERMS["distractor_event"],
        }
        return f"Observed {values[assertion]} in the reviewed source."

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
            return executor.Response(200, b"", "")
        if method == "GET" and path == "/models":
            return self._json(200, {"object": "list", "data": [{"id": "local-model"}]})
        if method == "GET" and path == "/files":
            assert parsed.query == "purpose=vision"
            return self._json(
                200, {"object": "list", "data": list(self.files.values())}
            )
        if method == "POST" and path == "/files":
            assert body is not None
            file_id = self._part(body, "id")
            sensor = self._part(body, "sensor_name")
            filename_match = re.search(rb'name="file"; filename="([^"]+)"', body)
            media_match = re.search(
                rb"Content-Type: video/mp4\r\n\r\n(.*?)\r\n--vss-lvs-focus-",
                body,
                re.DOTALL,
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
            row = dict(self.files[path.rsplit("/", 1)[1]])
            row.pop("media_type")
            return self._json(200, row)
        if method == "POST" and path == "/v1/summarize":
            assert body is not None and headers["Content-Type"] == "application/json"
            request = json.loads(body)
            self.matrix_requests.append(request)
            output_schema = json.loads(request["schema"])
            case_id = output_schema["properties"]["case_id"]["const"]
            caption_sha = output_schema["properties"]["caption_source_sha256"]["const"]
            assertions = output_schema["properties"]["focused_assertions"]["const"]
            evidence = [
                {
                    "assertion": assertion,
                    "start_seconds": float(index),
                    "end_seconds": float(index + 1),
                    "description": self._description(assertion),
                }
                for index, assertion in enumerate(assertions)
            ]
            if case_id == self.bad_case:
                if self.bad_mode == "absent-positive":
                    assertions = ["target_object"]
                    evidence = [
                        {
                            "assertion": "target_object",
                            "start_seconds": 0,
                            "end_seconds": 1,
                            "description": TERMS["absent_object"],
                        }
                    ]
                elif self.bad_mode == "distractor-leak":
                    evidence[0]["description"] += " " + TERMS["distractor_object"]
                elif self.bad_mode == "wrong-video":
                    request["id"] = UNRELATED_ID
            content = json.dumps(
                {
                    "case_id": case_id,
                    "caption_source_sha256": caption_sha,
                    "focused_assertions": assertions,
                    "evidence": evidence,
                }
            )
            self.matrix_calls += 1
            response_id = str(
                uuid5(
                    UUID("ad0cb3bc-f6a6-4a95-80f0-33dd43611ed7"), str(self.matrix_calls)
                )
            )
            if self.bad_mode == "duplicate-id" and self.matrix_calls > 1:
                response_id = str(
                    uuid5(UUID("ad0cb3bc-f6a6-4a95-80f0-33dd43611ed7"), "1")
                )
            return self._json(
                200,
                {
                    "id": response_id,
                    "video_id": request["id"],
                    "model": request["model"],
                    "created": 1,
                    "object": "summarization.completion",
                    "media_info": {
                        "type": "offset",
                        "start_offset": 0,
                        "end_offset": 6,
                    },
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "index": 0,
                            "message": {"content": content, "role": "assistant"},
                        }
                    ],
                    "usage": {"total_chunks_processed": 1},
                },
            )
        if method == "DELETE" and path.startswith("/files/"):
            file_id = path.rsplit("/", 1)[1]
            if self.delete_failure:
                return self._json(503, {"code": "DependencyError"})
            del self.files[file_id]
            return self._json(200, {"id": file_id, "object": "file", "deleted": True})
        raise AssertionError((method, path))


def _manifest(tmp_path: Path) -> dict[str, Any]:
    fixture = tmp_path / "focus.mp4"
    fixture.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"focus-matrix")
    return {
        "schema_version": 1,
        "run_id": "lvs-focus-test-001",
        "lvs_origin": "http://127.0.0.1:38111",
        "model": "local-model",
        "fixture": {
            "path": str(fixture),
            "sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
            "ownership_attested": True,
            "semantic_content_attested": True,
        },
        "semantic_fixture": dict(TERMS),
    }


def test_plan_is_inert_and_reconciles_frozen_action_envelope() -> None:
    assert executor.compile_plan() == {
        "schema_version": 1,
        "package_id": "lvs-focus-semantic-matrix-successor",
        "status": "inert_focus_matrix_valid",
        "runtime_requests": 0,
        "runtime_actions": 0,
        "request_bound": 14,
        "action_bound": 14,
        "matrix_cases": 6,
        "runtime_receipt_present": False,
        "executor_ready": False,
        "promotion_eligible": False,
        "canonical_state_advanced": False,
        "warehouse_sample_bundle": "excluded",
    }


def test_success_is_exact_six_case_14_action_sanitized_candidate(
    tmp_path: Path,
) -> None:
    manifest = _manifest(tmp_path)
    transport = FakeTransport()
    receipt = executor.execute(
        manifest=manifest, acknowledgement=ACK, transport=transport
    )
    assert receipt["status"] == "candidate_focus_matrix_pass_non_promoting"
    assert receipt["budget"] == {
        "requests": 14,
        "max_requests": 14,
        "actions": 14,
        "max_actions": 14,
        "max_duration_seconds": 2400,
    }
    assert [row["case_id"] for row in receipt["matrix"]] == list(executor.CASE_IDS)
    assert [row["evidence_count"] for row in receipt["matrix"]] == [1, 1, 1, 1, 2, 0]
    assert len({row["response_id_sha256"] for row in receipt["matrix"]}) == 6
    assert receipt["cleanup"] == {
        "registered_owned_files": 1,
        "deleted_owned_files": 1,
        "owned_absent": True,
        "unrelated_state_restored": True,
        "exact_delete_confirmation": True,
    }
    assert len(transport.calls) == 14 and transport.matrix_calls == 6
    assert [
        (row["scenario"], row["events"], row["objects_of_interest"])
        for row in transport.matrix_requests
    ] == [
        (TERMS["neutral_scenario"], [], [TERMS["target_object"]]),
        (TERMS["neutral_scenario"], [TERMS["target_event"]], []),
        (TERMS["target_scenario"], [], []),
        (
            TERMS["target_scenario"],
            [TERMS["target_event"], TERMS["distractor_event"]],
            [TERMS["target_object"], TERMS["distractor_object"]],
        ),
        (
            TERMS["neutral_scenario"],
            [TERMS["distractor_event"]],
            [TERMS["distractor_object"]],
        ),
        (
            TERMS["neutral_scenario"],
            [TERMS["absent_event"]],
            [TERMS["absent_object"]],
        ),
    ]
    assert all(
        row["auto_generate_prompt"] is True
        and row["override_vlm_prompt"] is False
        and row["enable_vlm_structured_output"] is True
        for row in transport.matrix_requests
    )
    assert list(transport.files) == [UNRELATED_ID]
    serialized = json.dumps(receipt, sort_keys=True)
    for raw in [
        manifest["run_id"],
        manifest["lvs_origin"],
        manifest["model"],
        manifest["fixture"]["path"],
        *TERMS.values(),
    ]:
        assert raw not in serialized


def test_authorization_precedes_fixture_read_and_transport(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    Path(manifest["fixture"]["path"]).unlink()
    transport = FakeTransport()
    with pytest.raises(executor.ExecutorError, match="authorization_required"):
        executor.execute(
            manifest=manifest, acknowledgement="wrong", transport=transport
        )
    assert transport.calls == []


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:38111",
        "https://127.0.0.1:38111",
        "http://10.0.0.1:38111",
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


def test_fixture_digest_and_mp4_identity_precede_transport(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    manifest["fixture"]["sha256"] = "0" * 64
    transport = FakeTransport()
    with pytest.raises(executor.ExecutorError, match="invalid_manifest"):
        executor.execute(manifest=manifest, acknowledgement=ACK, transport=transport)
    assert transport.calls == []


def test_semantic_terms_must_be_unique_and_non_overlapping(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    manifest["semantic_fixture"]["absent_event"] = TERMS["target_event"] + " extended"
    transport = FakeTransport()
    with pytest.raises(executor.ExecutorError, match="invalid_manifest"):
        executor.execute(manifest=manifest, acknowledgement=ACK, transport=transport)
    assert transport.calls == []


@pytest.mark.parametrize(
    ("case_id", "mode"),
    [
        ("absent_negative", "absent-positive"),
        ("combined_relationship", "distractor-leak"),
        ("event_only", "wrong-video"),
        ("event_only", "duplicate-id"),
    ],
)
def test_semantic_or_correlation_failure_still_cleans_exact_owned_file(
    tmp_path: Path, case_id: str, mode: str
) -> None:
    manifest = _manifest(tmp_path)
    transport = FakeTransport()
    transport.bad_case = case_id
    transport.bad_mode = mode
    with pytest.raises(executor.ExecutorError, match="oracle_failed"):
        executor.execute(manifest=manifest, acknowledgement=ACK, transport=transport)
    assert list(transport.files) == [UNRELATED_ID]
    assert [method for method, _path in transport.calls].count("DELETE") == 1


def test_cleanup_failure_is_not_reported_as_semantic_pass(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    transport = FakeTransport()
    transport.delete_failure = True
    with pytest.raises(executor.ExecutorError, match="cleanup_failed"):
        executor.execute(manifest=manifest, acknowledgement=ACK, transport=transport)
    assert len(transport.files) == 2


@pytest.mark.parametrize(("proxies", "redirects"), [(True, False), (False, True)])
def test_transport_policy_fails_before_activity(
    tmp_path: Path, proxies: bool, redirects: bool
) -> None:
    manifest = _manifest(tmp_path)
    transport = FakeTransport()
    transport.proxies_enabled = proxies
    transport.redirects_enabled = redirects
    with pytest.raises(executor.ExecutorError, match="invalid_manifest"):
        executor.execute(manifest=manifest, acknowledgement=ACK, transport=transport)
    assert transport.calls == []
