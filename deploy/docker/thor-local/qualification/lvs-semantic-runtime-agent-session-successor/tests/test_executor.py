"""Mock-only tests for the LVS NAT Agent session successor."""

from __future__ import annotations

from collections import deque
import importlib.util
from pathlib import Path
import sys
from typing import Any, Mapping
from urllib.parse import urlsplit

import pytest


PACKAGE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "lvs_agent_session_executor", PACKAGE / "executor.py"
)
assert SPEC is not None and SPEC.loader is not None
executor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = executor
SPEC.loader.exec_module(executor)

ACK = "I_ACK_LVS_AGENT_SESSION_RUNTIME_AND_EXACT_REPORT_CLEANUP"
RUN_ID = "lvs-agent-session-test-001"
ORIGIN = "http://127.0.0.1:8100"
OLD_STEM = "/static/vss_report_owned_alpha.mp4_20260802_110000"
FIRST = {
    "scenario": "first traffic monitoring scenario",
    "events": ["first stopped vehicle", "first pedestrian crossing"],
    "objects": ["first truck", "first pedestrian"],
}
LATEST = {
    "scenario": "latest loading dock monitoring scenario",
    "events": ["latest dropped pallet", "latest blocked exit"],
    "objects": ["latest forklift", "latest worker"],
}


def manifest() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_id": RUN_ID,
        "agent_origin": ORIGIN,
        "public_report_origins": [ORIGIN],
        "fixtures": [
            {
                "sensor_name": "owned_alpha.mp4",
                "media_sha256": "1" * 64,
                "duration_seconds": 61,
                "owner_run_id": RUN_ID,
                "ownership_attested": True,
                "vst_registration_attested": True,
                "duration_attested": True,
            },
            {
                "sensor_name": "owned_beta.mp4",
                "media_sha256": "2" * 64,
                "duration_seconds": 62,
                "owner_run_id": RUN_ID,
                "ownership_attested": True,
                "vst_registration_attested": True,
                "duration_attested": True,
            },
        ],
        "first_prompt": FIRST,
        "latest_prompt": LATEST,
    }


class FakeConnection:
    def __init__(self, owner: "FakeTransport", agent: str) -> None:
        self.owner = owner
        self.agent = agent
        self.queue: deque[dict[str, Any]] = deque()
        self.conversation = ""
        self.turn = 0
        self.stage = ""
        self.sent: list[dict[str, Any]] = []
        self.closed = False

    def _interaction(self, text: str) -> None:
        if (
            self.owner.old_pair_in_interaction_only
            and self.agent == "a"
            and self.turn == 1
            and self.stage == "scenario"
        ):
            text += f"\nOld links: {ORIGIN}{OLD_STEM}.md {ORIGIN}{OLD_STEM}.pdf"
        self.queue.append(
            {
                "type": "system_interaction_message",
                "conversation_id": self.conversation,
                "thread_id": f"thread-{self.agent}",
                "parent_id": f"parent-{self.agent}-{self.turn}-{self.stage}",
                "content": {"input_type": "text", "text": text},
            }
        )

    def _complete(self, text: str = "cancelled") -> None:
        self.queue.append(
            {
                "type": "system_response_message",
                "status": "in_progress",
                "conversation_id": self.conversation,
                "content": {"text": text},
            }
        )
        self.queue.append(
            {
                "type": "system_response_message",
                "status": "complete",
                "conversation_id": self.conversation,
                "content": {},
            }
        )

    def _report_complete(self, multi: bool) -> None:
        sensors = (
            ["owned_alpha.mp4", "owned_beta.mp4"] if multi else ["owned_alpha.mp4"]
        )
        stamp = "20260802_120002" if multi else "20260802_120001"
        if self.owner.collision and multi:
            stamp = "20260802_120001"
        values = LATEST if multi else FIRST
        lines = [
            "report_agent",
            *sensors,
            values["scenario"],
            *values["events"],
            *values["objects"],
        ]
        if not self.owner.old_pair_in_interaction_only:
            for sensor in sensors:
                stem = f"/static/vss_report_{sensor}_{stamp}"
                for extension in ("md", "pdf"):
                    path = f"{stem}.{extension}"
                    if self.owner.invalid_artifact_extension == extension:
                        body = b"\xff" if extension == "md" else b"not a PDF"
                    elif extension == "md":
                        body = f"# VSS report\n\n{path}\n".encode()
                    else:
                        body = b"%PDF-1.7\n" + path.encode()
                    self.owner.artifacts[path] = body
                    lines.append(f"{ORIGIN}{path}")
        self.queue.append(
            {
                "type": "system_intermediate_message",
                "conversation_id": self.conversation,
                "content": {"name": "report_agent", "payload": "video_report_gen"},
            }
        )
        report_text = "\n".join(lines)
        if self.owner.error_after_single and not multi:
            self.queue.append(
                {
                    "type": "system_response_message",
                    "status": "in_progress",
                    "conversation_id": self.conversation,
                    "content": {"text": report_text},
                }
            )
            self.queue.append(
                {
                    "type": "error",
                    "conversation_id": self.conversation,
                    "content": {"text": "late failure"},
                }
            )
        else:
            self._complete(report_text)

    def send_json(self, value: Mapping[str, Any]) -> None:
        message = dict(value)
        self.sent.append(message)
        kind = message["type"]
        self.conversation = message["conversation_id"]
        if kind == "user_message":
            self.turn += 1
            self.stage = "scenario"
            if self.agent == "b":
                state = (
                    LATEST["scenario"]
                    if self.owner.isolation_leak
                    else "traffic monitoring"
                )
                label = "CURRENTLY SET" if self.owner.isolation_leak else "DEFAULT"
                self._interaction(f"**{label}:** `{state}`\n\nScenario (REQUIRED)")
            elif self.turn == 1:
                self._interaction(
                    "**DEFAULT:** `traffic monitoring`\n\nScenario (REQUIRED)"
                )
            elif self.turn == 2:
                self._interaction(
                    f"**CURRENTLY SET:** `{FIRST['scenario']}`\n\nScenario (REQUIRED)"
                )
            else:
                self._interaction(
                    f"**CURRENTLY SET:** `{LATEST['scenario']}`\n\nScenario (REQUIRED)"
                )
            return
        assert kind == "user_interaction_message"
        response = message["content"]["messages"][0]["content"][0]["text"]
        if response == "/cancel":
            self._complete()
            return
        current = FIRST if self.turn == 1 else LATEST
        if self.stage == "scenario":
            self.stage = "events"
            label = "DEFAULT" if self.turn == 1 else "CURRENTLY SET"
            prior = (
                "accident, crossing" if self.turn == 1 else ", ".join(FIRST["events"])
            )
            self._interaction(f"**{label}:** `{prior}`\n\nEvents (REQUIRED)")
        elif self.stage == "events":
            self.stage = "objects"
            label = (
                ""
                if self.turn == 1
                else f"**CURRENTLY SET:** `{', '.join(FIRST['objects'])}`\n\n"
            )
            self._interaction(
                f"{label}Objects of Interest (OPTIONAL - requires explicit input)"
            )
        elif self.stage == "objects":
            self.stage = "confirm"
            self._interaction(
                "**Options:** Press Submit, Type `/redo`, or Type `/cancel` to stop."
            )
        else:
            assert self.stage == "confirm"
            assert response == ""
            self._report_complete(multi=self.turn == 2)
        assert current

    def receive_json(self, *, timeout_seconds: float, max_bytes: int) -> dict[str, Any]:
        assert timeout_seconds > 0
        assert max_bytes == 4 * 1024 * 1024
        if not self.queue:
            raise AssertionError("fake transcript exhausted")
        return self.queue.popleft()

    def close(self) -> None:
        self.closed = True


class FakeTransport:
    proxies_enabled = False
    redirects_enabled = False

    def __init__(
        self,
        *,
        isolation_leak: bool = False,
        collision: bool = False,
        error_after_single: bool = False,
        old_pair_in_interaction_only: bool = False,
        invalid_artifact_extension: str | None = None,
    ) -> None:
        self.isolation_leak = isolation_leak
        self.collision = collision
        self.error_after_single = error_after_single
        self.old_pair_in_interaction_only = old_pair_in_interaction_only
        self.invalid_artifact_extension = invalid_artifact_extension
        self.connections: list[FakeConnection] = []
        self.connect_calls: list[dict[str, Any]] = []
        self.http_calls: list[tuple[str, str]] = []
        self.artifacts: dict[str, bytes] = {}
        if old_pair_in_interaction_only:
            self.artifacts = {
                f"{OLD_STEM}.md": b"# preexisting report\n",
                f"{OLD_STEM}.pdf": b"%PDF-1.7\npreexisting report",
            }

    def connect_websocket(self, **kwargs: Any) -> FakeConnection:
        self.connect_calls.append(kwargs)
        connection = FakeConnection(self, "a" if not self.connections else "b")
        self.connections.append(connection)
        return connection

    def request_http(
        self,
        *,
        method: str,
        url: str,
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> executor.HTTPResponse:
        assert timeout_seconds == 15
        assert max_response_bytes == 8 * 1024 * 1024
        path = urlsplit(url).path
        self.http_calls.append((method, path))
        if method == "GET":
            if path in self.artifacts:
                return executor.HTTPResponse(200, self.artifacts[path])
            return executor.HTTPResponse(404, b"")
        assert method == "DELETE"
        if path in self.artifacts:
            del self.artifacts[path]
            return executor.HTTPResponse(204, b"")
        return executor.HTTPResponse(404, b"")


def test_plan_is_inert_and_preserves_honest_boundary() -> None:
    assert executor.compile_plan() == {
        "schema_version": 1,
        "package_id": "thor-vss-lvs-semantic-runtime-agent-session-successor-v1",
        "status": "inert_plan_valid",
        "runtime_activity_performed": False,
        "runtime_evidence_created": False,
        "canonical_selected_bound": False,
        "frozen_selected_request_bound": 14,
        "honest_successor_request_bound": 34,
        "concrete_complete_action_count": 5,
        "concrete_partial_action_count": 5,
        "residual_action_count": 4,
        "five_tool_declaration_source_locked": True,
        "five_tool_runtime_discovery": False,
        "promotion_eligible": False,
        "executor_ready": False,
        "warehouse_sample_bundle": "excluded",
    }


def test_authorization_fails_before_transport_activity() -> None:
    transport = FakeTransport()
    with pytest.raises(executor.ExecutorError, match="authorization_required"):
        executor.execute_agent_session(
            manifest=manifest(), acknowledgement="wrong", transport=transport
        )
    assert transport.connect_calls == []
    assert transport.http_calls == []


def test_wrong_acknowledgement_precedes_programmatic_manifest_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = FakeTransport()

    def unexpected_validation(_value: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("user manifest must not be validated")

    monkeypatch.setattr(executor, "_validate_manifest", unexpected_validation)
    with pytest.raises(executor.ExecutorError, match="authorization_required"):
        executor.execute_agent_session(
            manifest={"user_controlled": True},
            acknowledgement="wrong",
            transport=transport,
        )
    assert transport.connect_calls == []
    assert transport.http_calls == []


def test_cli_wrong_acknowledgement_does_not_read_user_manifest(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    user_manifest = Path("/user-controlled/must-not-be-read.json")
    original_json_file = executor._json_file
    user_reads: list[Path] = []

    def guarded_json_file(
        path: Path, code: str = "configuration_error"
    ) -> dict[str, Any]:
        if path == user_manifest:
            user_reads.append(path)
            raise AssertionError("user manifest must not be read")
        return original_json_file(path, code)

    monkeypatch.setattr(executor, "_json_file", guarded_json_file)
    assert (
        executor.main(
            [
                "execute-agent-session",
                "--manifest",
                str(user_manifest),
                "--acknowledgement",
                "wrong",
            ]
        )
        == 2
    )
    assert user_reads == []
    assert "authorization_required" in capsys.readouterr().err


def test_passing_run_uses_two_sessions_and_exact_cleanup() -> None:
    transport = FakeTransport()
    receipt = executor.execute_agent_session(
        manifest=manifest(), acknowledgement=ACK, transport=transport
    )
    assert receipt["status"] == "agent_session_subset_complete_non_promoting"
    assert receipt["budget"] | {"websocket_inbound_messages": 0} == {
        "actions": 34,
        "max_actions": 34,
        "requests": 34,
        "max_requests": 34,
        "websocket_inbound_messages": 0,
    }
    assert all(receipt["semantic_observations"].values())
    assert receipt["coverage"]["five_tool_runtime_discovery"] is False
    assert len(transport.connections) == 2
    assert len({call["session_id"] for call in transport.connect_calls}) == 2
    assert all(connection.closed for connection in transport.connections)
    assert len(transport.http_calls) == 18
    assert transport.artifacts == {}
    for connection in transport.connections:
        conversation_ids = {message["conversation_id"] for message in connection.sent}
        assert len(conversation_ids) == 1
        for message in connection.sent:
            if message["type"] == "user_interaction_message":
                assert message["thread_id"].startswith("thread-")
                assert message["parent_id"].startswith("parent-")
    serialized = str(receipt)
    for secret in [
        RUN_ID,
        "owned_alpha.mp4",
        "owned_beta.mp4",
        *FIRST.values(),
        *LATEST.values(),
    ]:
        if isinstance(secret, list):
            for item in secret:
                assert item not in serialized
        else:
            assert secret not in serialized
    assert ACK not in serialized
    assert ORIGIN not in serialized


def test_cross_session_leak_fails_but_cleans_all_generated_reports() -> None:
    transport = FakeTransport(isolation_leak=True)
    with pytest.raises(executor.ExecutorError, match="oracle_failed"):
        executor.execute_agent_session(
            manifest=manifest(), acknowledgement=ACK, transport=transport
        )
    assert transport.artifacts == {}
    assert len(transport.http_calls) == 18


def test_report_name_collision_fails_and_cleans_every_unique_object() -> None:
    transport = FakeTransport(collision=True)
    with pytest.raises(executor.ExecutorError, match="oracle_failed"):
        executor.execute_agent_session(
            manifest=manifest(), acknowledgement=ACK, transport=transport
        )
    assert transport.artifacts == {}
    # The second alpha pair overwrote the same exact keys; four unique objects exist.
    assert len(transport.http_calls) == 12


def test_late_agent_error_cleans_report_objects_already_announced() -> None:
    transport = FakeTransport(error_after_single=True)
    with pytest.raises(executor.ExecutorError, match="oracle_failed"):
        executor.execute_agent_session(
            manifest=manifest(), acknowledgement=ACK, transport=transport
        )
    assert transport.artifacts == {}
    assert len(transport.http_calls) == 6


def test_interaction_only_old_report_pair_is_never_admitted_or_deleted() -> None:
    transport = FakeTransport(old_pair_in_interaction_only=True)
    old_artifacts = dict(transport.artifacts)
    with pytest.raises(executor.ExecutorError, match="oracle_failed"):
        executor.execute_agent_session(
            manifest=manifest(), acknowledgement=ACK, transport=transport
        )
    assert transport.http_calls == []
    assert transport.artifacts == old_artifacts


@pytest.mark.parametrize("extension", ["md", "pdf"])
def test_invalid_artifact_body_fails_oracle_but_cleanup_remains_exact(
    extension: str,
) -> None:
    transport = FakeTransport(invalid_artifact_extension=extension)
    with pytest.raises(executor.ExecutorError, match="oracle_failed"):
        executor.execute_agent_session(
            manifest=manifest(), acknowledgement=ACK, transport=transport
        )
    assert len(transport.http_calls) == 18
    assert transport.artifacts == {}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["fixtures"][1].update(media_sha256="1" * 64),
        lambda value: value["fixtures"][0].update(duration_seconds=60),
        lambda value: value["fixtures"][0].update(sensor_name="report_agent.mp4"),
        lambda value: value["fixtures"][0].update(owner_run_id="somebody-else"),
        lambda value: value.update(agent_origin="http://thor.local:8100"),
        lambda value: value.update(latest_prompt=dict(value["first_prompt"])),
    ],
)
def test_invalid_manifest_fails_before_transport(mutate: Any) -> None:
    value = manifest()
    mutate(value)
    transport = FakeTransport()
    with pytest.raises(executor.ExecutorError, match="invalid_manifest"):
        executor.execute_agent_session(
            manifest=value, acknowledgement=ACK, transport=transport
        )
    assert transport.connect_calls == []
    assert transport.http_calls == []


def test_proxy_capable_adapter_is_rejected_before_connection() -> None:
    transport = FakeTransport()
    transport.proxies_enabled = True
    with pytest.raises(executor.ExecutorError, match="configuration_error"):
        executor.execute_agent_session(
            manifest=manifest(), acknowledgement=ACK, transport=transport
        )
    assert transport.connect_calls == []
