"""Fake-only tests for the candidate-alert runtime evidence collector."""

from __future__ import annotations

import copy
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
    "candidate_alerts_collector", HERE / "collector.py"
)
assert SPEC is not None and SPEC.loader is not None
collector = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = collector
SPEC.loader.exec_module(collector)

RUN_ID = "candidate-alerts-test-001"
ACK = "I_ACK_CANDIDATE_ALERTS_CONFIG_MUTATION_AND_BACKGROUND_VLM"
ORIGIN = "http://127.0.0.1:9080"
MEDIA_URL = "http://127.0.0.1:18080/tiny-identity.mp4"


class FakeResponse:
    def __init__(
        self,
        url: str,
        status: int,
        body: dict,
        *,
        final_url: str | None = None,
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


class FakeAlertBridge:
    proxies_enabled = False
    redirects_enabled = False

    def __init__(
        self,
        *,
        preexisting: str | None = None,
        fault_call: int | None = None,
        redirect_call: int | None = None,
        create_outcome: str = "success",
    ) -> None:
        self.configs: dict[str, dict] = {}
        if preexisting is not None:
            self.configs[preexisting] = {
                "alert_type": preexisting,
                "prompt": "preexisting",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            }
        self.fault_call = fault_call
        self.redirect_call = redirect_call
        self.create_outcome = create_outcome
        self.calls: list[tuple[str, str, dict | None]] = []
        self.responses: list[FakeResponse] = []

    def _response(self, request: Request, status: int, body: dict) -> FakeResponse:
        response = FakeResponse(request.full_url, status, body)
        self.responses.append(response)
        return response

    def open(self, request: Request, timeout: float) -> FakeResponse:
        assert timeout == 10.0
        method = request.get_method()
        path = urlsplit(request.full_url).path
        payload = json.loads(request.data) if request.data else None
        self.calls.append((method, path, payload))
        if self.redirect_call == len(self.calls):
            response = FakeResponse(
                request.full_url,
                302,
                {"status": "redirect"},
                final_url="http://127.0.0.1:9081/escaped",
            )
            self.responses.append(response)
            return response
        if self.fault_call == len(self.calls):
            return self._response(
                request, 500, {"status": "error", "error": "fake_fault"}
            )
        if method == "GET" and path == "/health":
            return self._response(request, 200, {"status": "ok", "message": "fake"})
        if method == "GET" and path == "/api/v1/verification/config":
            configs = sorted(self.configs.values(), key=lambda item: item["alert_type"])
            return self._response(
                request,
                200,
                {"status": "success", "configs": configs, "count": len(configs)},
            )
        if method == "POST" and path == "/api/v1/verification/config":
            assert payload is not None
            alert_type = payload["alert_type"]
            foreign = {
                "alert_type": alert_type,
                "prompt": "concurrent external owner",
                "system_prompt": "external",
                "output_category": "external-owner-marker",
                "vlm_params": {"max_tokens": 1},
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            }
            if self.create_outcome == "concurrent-409":
                self.configs[alert_type] = foreign
                return self._response(
                    request,
                    409,
                    {"status": "error", "error": "config_exists"},
                )
            if self.create_outcome == "ambiguous-500":
                self.configs[alert_type] = foreign
                return self._response(
                    request,
                    500,
                    {"status": "error", "error": "ambiguous_create"},
                )
            if alert_type in self.configs:
                return self._response(
                    request,
                    409,
                    {"status": "error", "error": "config_exists"},
                )
            stored = {
                **payload,
                "created_at": "2026-01-01T00:00:01Z",
                "updated_at": "2026-01-01T00:00:01Z",
            }
            self.configs[alert_type] = stored
            response = dict(stored)
            if self.create_outcome == "malformed-201":
                response["output_category"] = "external-owner-marker"
            return self._response(request, 201, response)
        prefix = "/api/v1/verification/config/"
        if path.startswith(prefix):
            alert_type = path.removeprefix(prefix)
            if method == "GET" and alert_type in self.configs:
                if self.create_outcome == "replaced-before-inspect":
                    self.configs[alert_type] = {
                        **self.configs[alert_type],
                        "prompt": "concurrent replacement",
                        "output_category": "external-owner-marker",
                    }
                return self._response(request, 200, self.configs[alert_type])
            if method == "DELETE":
                if alert_type in self.configs:
                    del self.configs[alert_type]
                    return self._response(
                        request,
                        200,
                        {"status": "success", "message": "deleted"},
                    )
                return self._response(
                    request,
                    404,
                    {"status": "error", "error": "config_not_found"},
                )
        if method == "POST" and path == "/api/v1/verification/ondemand":
            assert payload is not None
            if payload["category"] in self.configs:
                return self._response(
                    request,
                    202,
                    {
                        "status": "accepted",
                        "correlationId": payload["id"],
                        "message": "accepted",
                        "timestamp": "2026-01-01T00:00:02Z",
                    },
                )
            return self._response(
                request,
                400,
                {
                    "status": "error",
                    "error": "unknown_category",
                    "message": "unknown",
                    "timestamp": "2026-01-01T00:00:02Z",
                },
            )
        raise AssertionError(f"unexpected fake request: {method} {path}")


def run(fake: FakeAlertBridge | None = None, **overrides):
    fake = fake or FakeAlertBridge()
    arguments = {
        "run_id": RUN_ID,
        "acknowledgement": ACK,
        "origin": ORIGIN,
        "media_url": MEDIA_URL,
        "opener_factory": lambda: fake,
    }
    arguments.update(overrides)
    return collector.run_collector(**arguments), fake


def owned_type(run_id: str = RUN_ID) -> str:
    return f"vss_oracle_candidate_{hashlib.sha256(run_id.encode()).hexdigest()[:16]}"


def test_inert_plan_matches_exact_canonical_binding_and_bounds():
    plan = collector.compile_plan()
    assert plan["planning_requirement_id"] == "candidate-alerts"
    assert plan["capability_id"] == "runtime.workflow.alert-verification"
    assert plan["oracle_id"] == "oracle.runtime.workflow.alert-verification"
    assert plan["execution_bounds"]["max_requests"] == 8
    assert plan["execution_bounds"]["max_actions"] == 8
    assert plan["runtime_actions"] == 0
    assert plan["evidence_scope"] == {
        "promotion_eligible": False,
        "background_vlm_verdict_observed": False,
    }


def test_default_cli_never_constructs_live_opener(monkeypatch, capsys):
    monkeypatch.setattr(
        collector,
        "live_opener",
        lambda: (_ for _ in ()).throw(AssertionError("live opener constructed")),
    )
    assert collector.main([]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "inert-plan"
    assert output["runtime_actions"] == 0


@pytest.mark.parametrize("ack", ["", "wrong", ACK + " "])
def test_wrong_acknowledgement_fails_before_opener_factory(ack):
    called = False

    def factory():
        nonlocal called
        called = True
        return FakeAlertBridge()

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
    "origin",
    [
        "http://localhost:9080",
        "http://192.0.2.1:9080",
        "http://127.0.0.1",
        "http://user@127.0.0.1:9080",
        "http://127.0.0.1:9080/base",
    ],
)
def test_invalid_collector_origin_fails_before_opener_factory(origin):
    called = False

    def factory():
        nonlocal called
        called = True
        return FakeAlertBridge()

    with pytest.raises(collector.CollectorError, match="configuration_error"):
        collector.run_collector(
            run_id=RUN_ID,
            acknowledgement=ACK,
            origin=origin,
            media_url=MEDIA_URL,
            opener_factory=factory,
        )
    assert called is False


@pytest.mark.parametrize(
    "media_url",
    [
        "http://localhost:18080/tiny.mp4",
        "http://192.0.2.1:18080/tiny.mp4",
        "http://127.0.0.1:18080/tiny.mp4?token=x",
        "http://127.0.0.1:18080/%2e%2e/tiny.mp4",
        "https://127.0.0.1:18080/tiny.mp4",
        "http://127.0.0.1:18080/tiny.jpg",
    ],
)
def test_invalid_media_url_fails_before_opener_factory(media_url):
    called = False

    def factory():
        nonlocal called
        called = True
        return FakeAlertBridge()

    with pytest.raises(collector.CollectorError, match="configuration_error"):
        collector.run_collector(
            run_id=RUN_ID,
            acknowledgement=ACK,
            origin=ORIGIN,
            media_url=media_url,
            opener_factory=factory,
        )
    assert called is False


@pytest.mark.parametrize("proxy,redirect", [(True, False), (False, True)])
def test_injected_opener_must_disable_proxies_and_redirects(proxy, redirect):
    fake = FakeAlertBridge()
    fake.proxies_enabled = proxy
    fake.redirects_enabled = redirect
    with pytest.raises(collector.CollectorError, match="configuration_error"):
        run(fake)
    assert fake.calls == []


def test_success_uses_exact_eight_request_and_action_budget():
    evidence, fake = run()
    assert evidence["status"] == "pass"
    assert evidence["promotion_eligible"] is False
    assert evidence["runtime_evidence"]["budget"] == {
        "requests": 8,
        "max_requests": 8,
        "actions": 8,
        "max_actions": 8,
    }
    assert len(fake.calls) == 8
    assert [method for method, _path, _payload in fake.calls] == [
        "GET",
        "GET",
        "POST",
        "GET",
        "POST",
        "POST",
        "DELETE",
        "GET",
    ]
    assert [path for _method, path, _payload in fake.calls] == [
        "/health",
        "/api/v1/verification/config",
        "/api/v1/verification/config",
        f"/api/v1/verification/config/{owned_type()}",
        "/api/v1/verification/ondemand",
        "/api/v1/verification/ondemand",
        f"/api/v1/verification/config/{owned_type()}",
        "/api/v1/verification/config",
    ]
    assert all(response.closed for response in fake.responses)


def test_success_proves_cleanup_and_pre_post_digest_restore():
    evidence, fake = run()
    assert fake.configs == {}
    assert evidence["observations"] == {
        "health": "ok",
        "pre_state_owned_absent": True,
        "config_created": True,
        "config_identity": True,
        "positive_admitted": True,
        "adjacent_rejected": True,
        "cleanup_complete": True,
        "non_owned_state_restored": True,
    }
    cleanup = evidence["runtime_evidence"]["cleanup"]
    assert len(cleanup) == 1
    assert cleanup[0]["action_status"] == "pass"
    assert cleanup[0]["postcondition_status"] == "pass"
    comparison = evidence["runtime_evidence"]["comparisons"][0]
    assert comparison["status"] == "pass"
    assert comparison["pre_sha256"] == comparison["post_sha256"]


def test_sanitized_evidence_omits_urls_payloads_and_exact_resource_ids():
    evidence, _fake = run()
    encoded = json.dumps(evidence, sort_keys=True)
    assert ORIGIN not in encoded
    assert MEDIA_URL not in encoded
    assert owned_type() not in encoded
    assert "Answer only yes or no" not in encoded
    assert "vss-oracle-owner-" not in encoded
    assert "camera-01" not in encoded
    assert hashlib.sha256(ORIGIN.encode()).hexdigest() in encoded
    assert hashlib.sha256(MEDIA_URL.encode()).hexdigest() in encoded


def test_preexisting_exact_owned_config_aborts_without_mutation():
    fake = FakeAlertBridge(preexisting=owned_type())
    with pytest.raises(collector.CollectorError, match="oracle_failed"):
        run(fake)
    assert len(fake.calls) == 2
    assert all(method == "GET" for method, _path, _payload in fake.calls)
    assert owned_type() in fake.configs


def test_semantic_failure_after_create_still_runs_exact_cleanup_and_postcondition():
    fake = FakeAlertBridge(fault_call=5)
    with pytest.raises(collector.CollectorError, match="oracle_failed"):
        run(fake)
    assert fake.configs == {}
    assert [method for method, _path, _payload in fake.calls][-2:] == ["DELETE", "GET"]
    assert [path for _method, path, _payload in fake.calls][-2:] == [
        f"/api/v1/verification/config/{owned_type()}",
        "/api/v1/verification/config",
    ]


def test_unambiguous_create_failure_never_registers_or_runs_cleanup():
    fake = FakeAlertBridge(fault_call=3)
    with pytest.raises(collector.CollectorError, match="oracle_failed"):
        run(fake)
    assert fake.configs == {}
    assert [method for method, _path, _payload in fake.calls] == [
        "GET",
        "GET",
        "POST",
    ]


def test_concurrent_create_409_preserves_external_winner_without_delete():
    fake = FakeAlertBridge(create_outcome="concurrent-409")
    with pytest.raises(collector.CollectorError, match="oracle_failed"):
        run(fake)
    assert fake.configs[owned_type()]["output_category"] == "external-owner-marker"
    assert [method for method, _path, _payload in fake.calls] == [
        "GET",
        "GET",
        "POST",
    ]


def test_ambiguous_create_response_preserves_external_state_without_delete():
    fake = FakeAlertBridge(create_outcome="ambiguous-500")
    with pytest.raises(collector.CollectorError, match="oracle_failed"):
        run(fake)
    assert fake.configs[owned_type()]["output_category"] == "external-owner-marker"
    assert [method for method, _path, _payload in fake.calls] == [
        "GET",
        "GET",
        "POST",
    ]


def test_malformed_success_does_not_admit_cleanup_ownership():
    fake = FakeAlertBridge(create_outcome="malformed-201")
    with pytest.raises(collector.CollectorError, match="oracle_failed"):
        run(fake)
    assert owned_type() in fake.configs
    assert [method for method, _path, _payload in fake.calls] == [
        "GET",
        "GET",
        "POST",
    ]


def test_readback_replacement_preserves_external_state_without_delete():
    fake = FakeAlertBridge(create_outcome="replaced-before-inspect")
    with pytest.raises(collector.CollectorError, match="oracle_failed"):
        run(fake)
    assert fake.configs[owned_type()]["output_category"] == "external-owner-marker"
    assert [method for method, _path, _payload in fake.calls] == [
        "GET",
        "GET",
        "POST",
        "GET",
    ]


def test_redirect_is_rejected_and_response_closed_without_cleanup_ownership():
    fake = FakeAlertBridge(redirect_call=3)
    with pytest.raises(collector.CollectorError, match="transport_error"):
        run(fake)
    assert fake.responses[2].closed is True
    assert fake.configs == {}
    assert [method for method, _path, _payload in fake.calls] == [
        "GET",
        "GET",
        "POST",
    ]


def test_post_state_drift_fails_cleanup_postcondition():
    class DriftingBridge(FakeAlertBridge):
        def open(self, request: Request, timeout: float) -> FakeResponse:
            response = super().open(request, timeout)
            if len(self.calls) == 7:
                self.configs["foreign-drift"] = {
                    "alert_type": "foreign-drift",
                    "prompt": "foreign",
                }
            return response

    fake = DriftingBridge()
    with pytest.raises(collector.CollectorError, match="cleanup_failed"):
        run(fake)
    assert owned_type() not in fake.configs
    assert "foreign-drift" in fake.configs


def test_standalone_collector_schema_rejects_wrapper_and_nested_extras():
    evidence, _fake = run()
    schema = collector._json(HERE / "evidence.schema.json")
    collector._validate(evidence, schema)
    wrapper_extra = copy.deepcopy(evidence)
    wrapper_extra["raw_url"] = ORIGIN
    with pytest.raises(collector.CollectorError, match="configuration_error"):
        collector._validate(wrapper_extra, schema)
    nested_extra = copy.deepcopy(evidence)
    nested_extra["runtime_evidence"]["raw_payload"] = "secret"
    with pytest.raises(collector.CollectorError, match="configuration_error"):
        collector._validate(nested_extra, schema)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update(runtime_evidence={"status": "pass"}),
        lambda value: value["runtime_evidence"]["identity"].update(raw_url=ORIGIN),
        lambda value: value["runtime_evidence"]["actions"][0].update(
            result_code=ORIGIN
        ),
        lambda value: value["runtime_evidence"]["budget"].update(requests=7),
        lambda value: value["runtime_evidence"]["cleanup"].clear(),
        lambda value: value["runtime_evidence"]["comparisons"][0].update(
            comparison_id=ORIGIN
        ),
    ],
)
def test_standalone_schema_rejects_arbitrary_nested_evidence(mutate):
    evidence, _fake = run()
    mutate(evidence)
    with pytest.raises(collector.CollectorError, match="configuration_error"):
        collector._validate(evidence, collector._json(HERE / "evidence.schema.json"))


def test_contract_schema_rejects_unknown_property():
    contract = collector._json(HERE / "contract.json")
    contract["unexpected"] = True
    with pytest.raises(collector.CollectorError, match="configuration_error"):
        collector._validate(contract, collector._json(HERE / "contract.schema.json"))


def test_live_opener_policy_markers_are_explicit_without_opening_connection():
    opener = collector.live_opener()
    assert opener.proxies_enabled is False
    assert opener.redirects_enabled is False


def test_tests_never_call_the_live_opener(monkeypatch):
    monkeypatch.setattr(
        collector,
        "live_opener",
        lambda: (_ for _ in ()).throw(AssertionError("live network attempted")),
    )
    evidence, _fake = run()
    assert evidence["status"] == "pass"
