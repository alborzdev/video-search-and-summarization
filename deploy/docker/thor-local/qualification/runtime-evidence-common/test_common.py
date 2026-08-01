"""Fake-only tests for the inert runtime-evidence-common primitives."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys
from urllib.request import Request

import pytest

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "runtime_evidence_common", HERE / "common.py"
)
assert SPEC is not None and SPEC.loader is not None
common = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = common
SPEC.loader.exec_module(common)


class FakeResponse:
    def __init__(
        self,
        url: str,
        body: bytes = b"{}",
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = status
        self.headers = (
            headers
            if headers is not None
            else {
                "Content-Length": str(len(body)),
                "Content-Type": "application/json; charset=utf-8",
            }
        )
        self._url = url
        self._body = body
        self.read_sizes: list[int] = []
        self.closed = False

    def geturl(self) -> str:
        return self._url

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        return self._body if size < 0 else self._body[:size]

    def close(self) -> None:
        self.closed = True


class FakeOpener:
    proxies_enabled = False
    redirects_enabled = False

    def __init__(self, response_factory=None) -> None:
        self.requests: list[tuple[Request, float]] = []
        self.response_factory = response_factory or (
            lambda request: FakeResponse(request.full_url)
        )

    def open(self, request: Request, timeout: float) -> FakeResponse:
        self.requests.append((request, timeout))
        return self.response_factory(request)


def identity():
    guard = common.RunAuthorizationGuard.from_token(
        run_id="run-001", authorization_id="bundle-001", authorization_token="approval"
    )
    return guard.admit(
        run_id="run-001", authorization_id="bundle-001", authorization_token="approval"
    )


def target():
    return common.LoopbackTarget.admit(
        "http://127.0.0.1:8080", ["/health", "/v1/items"]
    )


def transport(*, opener=None, budget=None, **bounds):
    return common.BoundedHTTPTransport(
        target=target(),
        opener=opener or FakeOpener(),
        budget=budget or common.ExecutionBudget(max_requests=4, max_actions=4),
        **bounds,
    )


def test_package_contract_and_schemas_are_valid():
    result = common.check_package()
    assert result == {
        "schema_version": 1,
        "package_id": "runtime-evidence-common",
        "mode": "static-check",
        "status": "pass",
        "runtime_actions": 0,
    }


def test_contract_schema_rejects_unknown_property():
    contract = json.loads((HERE / "contract.json").read_text())
    schema = json.loads((HERE / "contract.schema.json").read_text())
    contract["unexpected"] = True
    with pytest.raises(common.AdmissionError, match="invalid_evidence"):
        common.validate_schema(contract, schema)


def test_strict_json_rejects_duplicate_keys_and_non_object():
    with pytest.raises(common.AdmissionError, match="configuration_error"):
        common.strict_json(b'{"a":1,"a":2}', "fixture")
    with pytest.raises(common.AdmissionError, match="configuration_error"):
        common.strict_json(b"[]", "fixture")


def test_numeric_ipv4_and_ipv6_loopback_origins_are_canonical():
    ipv4 = common.LoopbackTarget.admit("http://127.0.0.1:80", ["/x"])
    ipv6 = common.LoopbackTarget.admit("https://[0:0:0:0:0:0:0:1]:443/", ["/x"])
    assert ipv4.origin == "http://127.0.0.1:80"
    assert ipv6.origin == "https://[::1]:443"


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:8080",
        "http://example.com:8080",
        "http://10.0.0.1:8080",
        "http://127.0.0.1",
        "ftp://127.0.0.1:21",
        "http://user@127.0.0.1:8080",
        "http://127.0.0.1:8080/base",
        "http://127.0.0.1:8080?x=1",
        "http://[::1%25lo]:8080",
    ],
)
def test_origin_admission_rejects_dns_remote_implicit_and_decorated(origin):
    with pytest.raises(common.AdmissionError, match="configuration_error"):
        common.LoopbackTarget.admit(origin, ["/x"])


def test_path_admission_is_exact():
    admitted = target()
    assert admitted.admit_path("/health") == "/health"
    with pytest.raises(common.AdmissionError, match="invalid_path"):
        admitted.admit_path("/health/extra")


@pytest.mark.parametrize(
    "path",
    [
        "health",
        "/v1/../health",
        "/health?next=x",
        "//evil/x",
        "///evil/x",
        "/%2e%2e/x",
        "/x\\y",
        "/café",
        "/x\x7fy",
    ],
)
def test_path_admission_rejects_ambiguous_or_traversing_paths(path):
    with pytest.raises(common.AdmissionError, match="invalid_path"):
        common.LoopbackTarget.admit("http://127.0.0.1:8080", [path])


@pytest.mark.parametrize(
    "proxy_value,redirect_value",
    [(True, False), (False, True), (None, False), (False, None)],
)
def test_transport_requires_explicit_proxy_and_redirect_disable_markers(
    proxy_value, redirect_value
):
    opener = FakeOpener()
    opener.proxies_enabled = proxy_value
    opener.redirects_enabled = redirect_value
    with pytest.raises(common.AdmissionError, match="configuration_error"):
        transport(opener=opener)


def test_transport_requires_injected_opener():
    with pytest.raises(common.AdmissionError, match="configuration_error"):
        common.BoundedHTTPTransport(
            target=target(),
            opener=None,
            budget=common.ExecutionBudget(max_requests=1, max_actions=1),
        )


def test_transport_revalidates_directly_constructed_target():
    forged = common.LoopbackTarget("http://example.com:8080", ("/health",))
    with pytest.raises(common.AdmissionError, match="configuration_error"):
        common.BoundedHTTPTransport(
            target=forged,
            opener=FakeOpener(),
            budget=common.ExecutionBudget(max_requests=1, max_actions=1),
        )


def test_bounded_transport_uses_fake_opener_and_exact_url():
    response = FakeResponse("http://127.0.0.1:8080/health", b'{"ok":true}')
    opener = FakeOpener(lambda _request: response)
    budget = common.ExecutionBudget(max_requests=1, max_actions=1)
    result = transport(opener=opener, budget=budget).request("GET", "/health")
    assert result.status == 200
    assert result.media_type == "application/json"
    assert result.body == b'{"ok":true}'
    assert opener.requests[0][0].full_url == "http://127.0.0.1:8080/health"
    assert opener.requests[0][1] == 10.0
    assert response.read_sizes == [1024 * 1024 + 1]
    assert response.closed is True
    assert budget.requests == 1


@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_transport_rejects_redirect_status(status):
    response = FakeResponse("http://127.0.0.1:8080/health", status=status)
    opener = FakeOpener(lambda _request: response)
    with pytest.raises(common.TransportError, match="transport_error"):
        transport(opener=opener).request("GET", "/health")
    assert response.closed is True


def test_transport_rejects_final_url_drift():
    opener = FakeOpener(lambda _request: FakeResponse("http://127.0.0.1:8081/health"))
    with pytest.raises(common.TransportError, match="transport_error"):
        transport(opener=opener).request("GET", "/health")


def test_transport_rejects_oversize_declared_response_before_read():
    response = FakeResponse(
        "http://127.0.0.1:8080/health",
        headers={"Content-Length": "9", "Content-Type": "application/json"},
    )
    with pytest.raises(common.TransportError, match="response_too_large"):
        transport(
            opener=FakeOpener(lambda _request: response), max_response_bytes=8
        ).request("GET", "/health")
    assert response.read_sizes == []


def test_transport_rejects_oversize_streamed_response_with_bounded_read():
    response = FakeResponse("http://127.0.0.1:8080/health", b"123456789", headers={})
    with pytest.raises(common.TransportError, match="response_too_large"):
        transport(
            opener=FakeOpener(lambda _request: response), max_response_bytes=8
        ).request("GET", "/health")
    assert response.read_sizes == [9]
    assert response.closed is True


def test_transport_closes_response_when_bounded_read_raises():
    class BrokenResponse(FakeResponse):
        def read(self, size: int = -1) -> bytes:
            self.read_sizes.append(size)
            raise OSError("fake read failure")

    response = BrokenResponse("http://127.0.0.1:8080/health", headers={})
    with pytest.raises(common.TransportError, match="transport_error"):
        transport(opener=FakeOpener(lambda _request: response)).request(
            "GET", "/health"
        )
    assert response.closed is True


def test_request_bound_is_checked_before_injected_opener():
    opener = FakeOpener()
    with pytest.raises(common.TransportError, match="request_too_large"):
        transport(opener=opener, max_request_bytes=2).request(
            "POST", "/v1/items", body=b"abc", media_type="application/json"
        )
    assert opener.requests == []


def test_request_budget_denies_second_request_before_opener():
    opener = FakeOpener()
    budget = common.ExecutionBudget(max_requests=1, max_actions=1)
    client = transport(opener=opener, budget=budget)
    client.request("GET", "/health")
    with pytest.raises(common.BudgetError, match="request_budget_exceeded"):
        client.request("GET", "/health")
    assert len(opener.requests) == 1


def test_action_budget_denies_second_evidence_record():
    budget = common.ExecutionBudget(max_requests=1, max_actions=1)
    recorder = common.EvidenceRecorder(budget)
    recorder.record(
        action_id="one", kind="fake", status="pass", payload=b"a", result_code="ok"
    )
    with pytest.raises(common.BudgetError, match="action_budget_exceeded"):
        recorder.record(
            action_id="two", kind="fake", status="pass", payload=b"b", result_code="ok"
        )
    assert len(recorder.actions) == 1


def test_action_budget_has_strict_per_run_ceiling_of_64():
    assert common.ExecutionBudget(max_requests=1, max_actions=14).max_actions == 14
    assert common.ExecutionBudget(max_requests=1, max_actions=64).max_actions == 64
    with pytest.raises(common.AdmissionError, match="configuration_error"):
        common.ExecutionBudget(max_requests=1, max_actions=65)


def test_run_authorization_guard_admits_only_exact_identity_and_token():
    guard = common.RunAuthorizationGuard.from_token(
        run_id="run-001", authorization_id="bundle-001", authorization_token="approval"
    )
    admitted = guard.admit(
        run_id="run-001", authorization_id="bundle-001", authorization_token="approval"
    )
    assert admitted.run_id == "run-001"
    assert admitted.authorization_token_sha256 == common.sha256_bytes(b"approval")
    assert "approval" not in json.dumps(admitted.evidence())
    with pytest.raises(common.AdmissionError, match="identity_mismatch"):
        guard.admit(
            run_id="run-002",
            authorization_id="bundle-001",
            authorization_token="approval",
        )
    with pytest.raises(common.AdmissionError, match="authorization_mismatch"):
        guard.admit(
            run_id="run-001", authorization_id="bundle-001", authorization_token="wrong"
        )


def test_direct_identity_construction_still_validates_fields():
    with pytest.raises(common.AdmissionError, match="configuration_error"):
        common.EvidenceIdentity("bad run", "bundle-001", "0" * 64)
    with pytest.raises(common.AdmissionError, match="configuration_error"):
        common.EvidenceIdentity("run-001", "bundle-001", "not-a-digest")


def test_resource_ledger_cleans_exact_ids_in_lifo_order_and_redacts_them():
    seen: list[str] = []
    existing = {"private-first", "private-second"}
    budget = common.ExecutionBudget(max_requests=1, max_actions=4)
    ledger = common.ResourceLedger(identity(), budget)
    for resource_id in ["private-first", "private-second"]:
        ledger.register(
            owner_run_id="run-001",
            resource_type="mock-item",
            resource_id=resource_id,
            cleanup=lambda exact, values=existing: (
                seen.append(exact),
                values.remove(exact),
            ),
            postcondition=lambda exact, values=existing: exact not in values,
        )
    assert ledger.cleanup() is True
    assert seen == ["private-second", "private-first"]
    assert ledger.active_count == 0
    assert budget.actions == 4
    ledger.assert_postconditions()
    assert "private-first" not in json.dumps(ledger.records)
    assert "private-second" not in json.dumps(ledger.records)


def test_resource_ledger_rejects_wrong_owner_and_duplicate_exact_target():
    ledger = common.ResourceLedger(
        identity(), common.ExecutionBudget(max_requests=1, max_actions=2)
    )

    def callback(_exact):
        return None

    def postcondition(_exact):
        return True

    with pytest.raises(common.AdmissionError, match="identity_mismatch"):
        ledger.register(
            owner_run_id="other-run",
            resource_type="mock-item",
            resource_id="one",
            cleanup=callback,
            postcondition=postcondition,
        )
    ledger.register(
        owner_run_id="run-001",
        resource_type="mock-item",
        resource_id="one",
        cleanup=callback,
        postcondition=postcondition,
    )
    with pytest.raises(common.AdmissionError, match="configuration_error"):
        ledger.register(
            owner_run_id="run-001",
            resource_type="mock-item",
            resource_id="one",
            cleanup=callback,
            postcondition=postcondition,
        )


def test_resource_ledger_stops_on_failure_and_retains_top_for_recovery():
    budget = common.ExecutionBudget(max_requests=1, max_actions=4)
    ledger = common.ResourceLedger(identity(), budget)
    attempts = 0

    def cleanup(_exact):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("private detail")

    ledger.register(
        owner_run_id="run-001",
        resource_type="mock-item",
        resource_id="private-id",
        cleanup=cleanup,
        postcondition=lambda _exact: True,
    )
    assert ledger.cleanup() is False
    assert ledger.active_count == 1
    assert "private detail" not in json.dumps(ledger.records)
    assert ledger.cleanup() is True
    assert ledger.active_count == 0
    assert budget.actions == 4


def test_resource_ledger_postcondition_must_return_literal_true():
    ledger = common.ResourceLedger(
        identity(), common.ExecutionBudget(max_requests=1, max_actions=2)
    )
    ledger.register(
        owner_run_id="run-001",
        resource_type="mock-item",
        resource_id="private-id",
        cleanup=lambda _exact: None,
        postcondition=lambda _exact: 1,
    )
    assert ledger.cleanup() is False
    with pytest.raises(common.CleanupError, match="cleanup_failed"):
        ledger.assert_postconditions()


def test_one_remaining_action_denies_cleanup_atomically_before_callback():
    budget = common.ExecutionBudget(max_requests=1, max_actions=2)
    budget.consume_action()
    ledger = common.ResourceLedger(identity(), budget)
    called: list[str] = []
    ledger.register(
        owner_run_id="run-001",
        resource_type="mock-item",
        resource_id="private-id",
        cleanup=lambda exact: called.append(exact),
        postcondition=lambda _exact: True,
    )
    with pytest.raises(common.BudgetError, match="action_budget_exceeded"):
        ledger.cleanup()
    assert called == []
    assert ledger.active_count == 1
    assert budget.actions == 1
    assert ledger.records == []


def test_digest_comparison_records_only_digests_and_exact_expectation():
    equal = common.DigestComparison.compare("state-restore", {"a": 1}, {"a": 1})
    changed = common.DigestComparison.compare(
        "state-change", {"a": 1}, {"a": 2}, expectation="different"
    )
    failed = common.DigestComparison.compare("state-drift", {"a": 1}, {"a": 2})
    assert equal.status == changed.status == "pass"
    assert failed.status == "fail"
    assert set(equal.evidence()) == {
        "comparison_id",
        "pre_sha256",
        "post_sha256",
        "expectation",
        "status",
    }


def test_digest_comparison_rejects_forged_status():
    digest = common.digest_value([])
    with pytest.raises(common.AdmissionError, match="configuration_error"):
        common.DigestComparison("forged", digest, digest, "equal", "fail")


def test_evidence_record_contains_payload_digest_not_payload_or_headers():
    recorder = common.EvidenceRecorder(
        common.ExecutionBudget(max_requests=1, max_actions=1)
    )
    raw = b'{"password":"do-not-record"}'
    recorder.record(
        action_id="inspect-one",
        kind="fake-http",
        status="pass",
        payload=raw,
        result_code="oracle_passed",
    )
    encoded = json.dumps(recorder.actions)
    assert "do-not-record" not in encoded
    assert common.sha256_bytes(raw) in encoded
    assert set(recorder.actions[0]) == {
        "order",
        "action_id",
        "kind",
        "status",
        "payload_bytes",
        "payload_sha256",
        "result_code",
    }


def test_built_evidence_is_strict_schema_valid_and_status_is_derived():
    admitted = identity()
    budget = common.ExecutionBudget(max_requests=1, max_actions=1)
    ledger = common.ResourceLedger(admitted, budget)
    recorder = common.EvidenceRecorder(budget)
    recorder.record(
        action_id="inspect-one",
        kind="fake-http",
        status="pass",
        result_code="oracle_passed",
    )
    evidence = recorder.build(
        identity=admitted,
        ledger=ledger,
        comparisons=[common.DigestComparison.compare("restore", [], [])],
    )
    assert evidence["status"] == "pass"
    assert evidence["cleanup"] == []
    mutated = copy.deepcopy(evidence)
    mutated["raw_url"] = "http://127.0.0.1:8080"
    schema = json.loads((HERE / "evidence.schema.json").read_text())
    with pytest.raises(common.AdmissionError, match="invalid_evidence"):
        common.validate_schema(mutated, schema)


def test_failed_comparison_forces_failed_evidence_status():
    admitted = identity()
    budget = common.ExecutionBudget(max_requests=1, max_actions=1)
    evidence = common.EvidenceRecorder(budget).build(
        identity=admitted,
        ledger=common.ResourceLedger(admitted, budget),
        comparisons=[common.DigestComparison.compare("restore", [], [1])],
    )
    assert evidence["status"] == "fail"


def test_evidence_build_rejects_a_ledger_with_a_different_budget():
    admitted = identity()
    recorder_budget = common.ExecutionBudget(max_requests=1, max_actions=1)
    ledger_budget = common.ExecutionBudget(max_requests=1, max_actions=1)
    with pytest.raises(common.AdmissionError, match="configuration_error"):
        common.EvidenceRecorder(recorder_budget).build(
            identity=admitted,
            ledger=common.ResourceLedger(admitted, ledger_budget),
            comparisons=[],
        )


def test_fake_self_test_covers_transport_cleanup_and_evidence_without_live_io():
    evidence = common.fake_self_test()
    assert evidence["status"] == "pass"
    assert evidence["budget"] == {
        "actions": 3,
        "max_actions": 3,
        "requests": 1,
        "max_requests": 1,
    }
    assert evidence["cleanup"][0]["postcondition_status"] == "pass"


def test_source_has_no_live_opener_subprocess_container_or_host_primitives():
    source = (HERE / "common.py").read_text()
    forbidden = [
        "urlopen(",
        "build_opener(",
        "ProxyHandler(",
        "import subprocess",
        "docker",
        "/proc/",
        "/sys/",
        "socket.",
    ]
    assert not [token for token in forbidden if token in source]
