"""Fake-only tests for terminal Alerts runtime evidence collection."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit
from urllib.request import Request

import pytest


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "alerts_terminal_collector", HERE / "collector.py"
)
assert SPEC is not None and SPEC.loader is not None
collector = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = collector
SPEC.loader.exec_module(collector)

RUN_ID = "terminal-alerts-test-001"
ACK = "I_ACK_CANDIDATE_ALERTS_TERMINAL_JOBS_AND_CONFIG_CLEANUP"
ORIGIN = "http://127.0.0.1:9080"
MEDIA_URL = "http://127.0.0.1:18080/tiny-identity.mp4"


class FakeResponse:
    def __init__(
        self, url: str, status: int, body: dict, *, final_url: str | None = None
    ) -> None:
        self.status = status
        self._body = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        self.headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(self._body)),
        }
        self._url = final_url or url
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        return self._body if size < 0 else self._body[:size]

    def geturl(self) -> str:
        return self._url

    def close(self) -> None:
        self.closed = True


class FakeAlerts:
    proxies_enabled = False
    redirects_enabled = False

    def __init__(
        self,
        *,
        sink: dict | None = None,
        positive_states: tuple[str, ...] = (
            "queued",
            "running",
            "publishing",
            "completed",
        ),
        stale_client_id: bool = False,
        cancel_status: int = 202,
        cancel_result_on_second_get: bool = False,
        replace_after_cleanup: bool = False,
    ) -> None:
        self.configs: dict[str, dict] = {
            "foreign-control": {
                "alert_type": "foreign-control",
                "prompt": "foreign",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            }
        }
        self.sink = sink or {
            "transport": "elastic",
            "outcome": "acknowledged",
            "documentId": "doc-17",
            "index": "alerts-v1",
        }
        self.positive_states = list(positive_states)
        self.stale_client_id = stale_client_id
        self.cancel_status = cancel_status
        self.cancel_result_on_second_get = cancel_result_on_second_get
        self.replace_after_cleanup = replace_after_cleanup
        self.calls: list[tuple[str, str, dict | None]] = []
        self.responses: list[FakeResponse] = []
        self.submit_count = 0
        self.positive_gets = 0
        self.cancel_gets = 0
        self.cancelled = False
        self.config_deleted = False

    def response(self, request: Request, status: int, body: dict) -> FakeResponse:
        value = FakeResponse(request.full_url, status, body)
        self.responses.append(value)
        return value

    @staticmethod
    def snapshot(
        correlation_id: str, state: str, *, result: dict | None = None
    ) -> dict:
        value = {
            "correlationId": correlation_id,
            "state": state,
            "terminal": state in {"completed", "failed", "cancelled"},
            "createdAt": "2026-01-01T00:00:03Z",
            "updatedAt": "2026-01-01T00:00:04Z",
        }
        if result is not None:
            value["result"] = result
        return value

    def open(self, request: Request, timeout: float) -> FakeResponse:
        assert timeout == 10.0
        method = request.get_method()
        path = urlsplit(request.full_url).path
        payload = json.loads(request.data) if request.data else None
        self.calls.append((method, path, payload))
        if method == "GET" and path == "/health":
            return self.response(request, 200, {"status": "ok"})
        if method == "GET" and path == "/api/v1/verification/config":
            if self.replace_after_cleanup and self.config_deleted:
                self.configs["foreign-control"]["prompt"] = "changed"
            values = sorted(self.configs.values(), key=lambda item: item["alert_type"])
            return self.response(
                request,
                200,
                {"status": "success", "configs": values, "count": len(values)},
            )
        if method == "POST" and path == "/api/v1/verification/config":
            assert payload is not None
            stored = {
                **payload,
                "created_at": "2026-01-01T00:00:01Z",
                "updated_at": "2026-01-01T00:00:01Z",
            }
            self.configs[payload["alert_type"]] = stored
            return self.response(request, 201, stored)
        config_prefix = "/api/v1/verification/config/"
        if path.startswith(config_prefix):
            alert_type = path.removeprefix(config_prefix)
            if method == "GET":
                return self.response(request, 200, self.configs[alert_type])
            if method == "DELETE":
                del self.configs[alert_type]
                self.config_deleted = True
                return self.response(
                    request, 200, {"status": "success", "message": "deleted"}
                )
        if method == "POST" and path == "/api/v1/verification/ondemand":
            assert payload is not None
            if payload["category"] not in self.configs:
                return self.response(
                    request, 400, {"status": "error", "error": "unknown_category"}
                )
            self.submit_count += 1
            generated = (
                "job-positive-server-1"
                if self.submit_count == 1
                else "job-cancel-server-2"
            )
            correlation_id = payload["id"] if self.stale_client_id else generated
            return self.response(
                request,
                202,
                {
                    "status": "accepted",
                    "correlationId": correlation_id,
                    "statusUrl": f"/api/v1/verification/ondemand/{correlation_id}",
                    "message": "accepted",
                    "timestamp": "2026-01-01T00:00:02Z",
                },
            )
        job_prefix = "/api/v1/verification/ondemand/"
        if path.startswith(job_prefix):
            correlation_id = path.removeprefix(job_prefix)
            if correlation_id == "job-positive-server-1" and method == "GET":
                state = self.positive_states[
                    min(self.positive_gets, len(self.positive_states) - 1)
                ]
                self.positive_gets += 1
                result = None
                if state == "completed":
                    result = {
                        "processingOutcome": "verified",
                        "sinkDelivery": self.sink,
                    }
                return self.response(
                    request, 200, self.snapshot(correlation_id, state, result=result)
                )
            if correlation_id == "job-cancel-server-2" and method == "DELETE":
                if self.cancel_status != 202:
                    return self.response(
                        request,
                        self.cancel_status,
                        {"status": "error", "error": "job_not_cancellable"},
                    )
                self.cancelled = True
                value = self.snapshot(correlation_id, "cancelled")
                value["cancellationAccepted"] = True
                return self.response(request, 202, value)
            if (
                correlation_id == "job-cancel-server-2"
                and method == "GET"
                and self.cancelled
            ):
                self.cancel_gets += 1
                result = (
                    {"processingOutcome": "verified", "sinkDelivery": self.sink}
                    if self.cancel_result_on_second_get and self.cancel_gets == 2
                    else None
                )
                return self.response(
                    request,
                    200,
                    self.snapshot(correlation_id, "cancelled", result=result),
                )
        raise AssertionError(f"unexpected fake request: {method} {path}")


def run(fake: FakeAlerts | None = None, **overrides):
    fake = fake or FakeAlerts()
    arguments = {
        "run_id": RUN_ID,
        "acknowledgement": ACK,
        "origin": ORIGIN,
        "media_url": MEDIA_URL,
        "opener_factory": lambda: fake,
        "sleeper": lambda _seconds: None,
    }
    arguments.update(overrides)
    return collector.run_collector(**arguments), fake


def test_inert_plan_and_default_cli_never_open_network(monkeypatch, capsys):
    plan = collector.compile_plan()
    assert plan["mode"] == "inert-plan"
    assert plan["runtime_requests"] == plan["runtime_actions"] == 0
    assert plan["warehouse_sample_bundle"] == "excluded"
    monkeypatch.setattr(
        collector,
        "live_opener",
        lambda: (_ for _ in ()).throw(AssertionError("opened")),
    )
    assert collector.main([]) == 0
    assert json.loads(capsys.readouterr().out)["runtime_actions"] == 0


@pytest.mark.parametrize("ack", ["", "wrong", ACK + " "])
def test_authorization_fails_before_opener(ack):
    called = False

    def factory():
        nonlocal called
        called = True
        return FakeAlerts()

    with pytest.raises(collector.CollectorError, match="authorization_required"):
        collector.run_collector(
            run_id=RUN_ID,
            acknowledgement=ack,
            origin=ORIGIN,
            media_url=MEDIA_URL,
            opener_factory=factory,
        )
    assert called is False


@pytest.mark.parametrize(
    "origin", ["http://localhost:9080", "http://192.0.2.1:9080", "http://127.0.0.1"]
)
def test_origin_is_exact_numeric_loopback(origin):
    called = False

    def factory():
        nonlocal called
        called = True
        return FakeAlerts()

    with pytest.raises(collector.CollectorError, match="configuration_error"):
        collector.run_collector(
            run_id=RUN_ID,
            acknowledgement=ACK,
            origin=origin,
            media_url=MEDIA_URL,
            opener_factory=factory,
        )
    assert called is False


def test_success_follows_server_ids_to_terminal_receipt_and_cancel():
    evidence, fake = run()
    assert evidence["status"] == "candidate_terminal_evidence_pass_non_promoting"
    assert evidence["positive"]["polls"] == 4
    assert evidence["positive"]["sink_transport"] == "elastic"
    assert evidence["cancellation"]["delayed_no_publish_result"] is True
    assert evidence["budget"]["requests"] == evidence["budget"]["actions"] == 16
    paths = [path for _method, path, _payload in fake.calls]
    assert "/api/v1/verification/ondemand/job-positive-server-1" in paths
    assert paths.count("/api/v1/verification/ondemand/job-cancel-server-2") == 3
    assert all(response.closed for response in fake.responses)
    assert list(fake.configs) == ["foreign-control"]
    encoded = json.dumps(evidence, sort_keys=True)
    assert "job-positive-server-1" not in encoded
    assert MEDIA_URL not in encoded
    assert hashlib.sha256(MEDIA_URL.encode()).hexdigest() in encoded


def test_kafka_acknowledged_receipt_is_supported():
    evidence, _ = run(
        FakeAlerts(
            sink={
                "transport": "kafka",
                "outcome": "acknowledged",
                "topic": "alerts",
                "partition": "0",
                "offset": "9",
            }
        )
    )
    assert evidence["positive"]["sink_transport"] == "kafka"


@pytest.mark.parametrize(
    "sink",
    [
        {
            "transport": "elastic",
            "outcome": "unconfirmed",
            "documentId": "doc",
            "index": "idx",
        },
        {"transport": "elastic", "outcome": "acknowledged", "index": "idx"},
        {
            "transport": "kafka",
            "outcome": "acknowledged",
            "topic": "alerts",
            "partition": 0,
            "offset": 9,
        },
    ],
)
def test_non_acknowledged_or_incomplete_sink_receipt_fails_but_cleans_up(sink):
    fake = FakeAlerts(sink=sink)
    with pytest.raises(collector.CollectorError, match="oracle_failed"):
        run(fake)
    assert list(fake.configs) == ["foreign-control"]


def test_stale_client_correlation_id_is_rejected_and_cleaned_up():
    fake = FakeAlerts(stale_client_id=True)
    with pytest.raises(collector.CollectorError, match="oracle_failed"):
        run(fake)
    assert list(fake.configs) == ["foreign-control"]


@pytest.mark.parametrize("states", [("running",) * 10, ("running", "queued")])
def test_terminal_poll_exhaustion_or_backward_state_fails_and_cleans_up(states):
    fake = FakeAlerts(positive_states=states)
    with pytest.raises(collector.CollectorError, match="oracle_failed"):
        run(fake)
    assert list(fake.configs) == ["foreign-control"]


def test_cancellation_must_be_accepted_before_publish():
    fake = FakeAlerts(cancel_status=409)
    with pytest.raises(collector.CollectorError, match="oracle_failed"):
        run(fake)
    assert list(fake.configs) == ["foreign-control"]


def test_delayed_cancel_observation_must_remain_without_publish_result():
    fake = FakeAlerts(cancel_result_on_second_get=True)
    with pytest.raises(collector.CollectorError, match="oracle_failed"):
        run(fake)
    assert list(fake.configs) == ["foreign-control"]


def test_non_owned_poststate_drift_is_cleanup_failure():
    fake = FakeAlerts(replace_after_cleanup=True)
    with pytest.raises(collector.CollectorError, match="cleanup_failed"):
        run(fake)
    assert list(fake.configs) == ["foreign-control"]
