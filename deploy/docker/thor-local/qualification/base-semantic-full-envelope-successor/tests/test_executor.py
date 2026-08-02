from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys
from urllib.request import Request

import pytest

HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "base_full_envelope_executor", HERE / "executor.py"
)
assert SPEC and SPEC.loader
executor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = executor
SPEC.loader.exec_module(executor)

MD = "/static/vss_report_full-run-001_20260802_120000.md"
PDF = "/static/vss_report_full-run-001_20260802_120000.pdf"
REPORT_ORIGIN = "http://reports.local:8000"


class Response:
    def __init__(self, url: str, status: int, body: bytes, media="application/json"):
        self.status, self._url, self._body = status, url, body
        self.headers = {"Content-Length": str(len(body)), "Content-Type": media}
        self.closed = False

    def geturl(self):
        return self._url

    def read(self, size=-1):
        return self._body if size < 0 else self._body[:size]

    def close(self):
        self.closed = True


def report_response() -> bytes:
    content = (
        f"[Markdown Report]({REPORT_ORIGIN}{MD}) and [PDF Report]({REPORT_ORIGIN}{PDF})"
    )
    return (
        "data: " + json.dumps({"type": "final", "content": content}) + "\n\n"
    ).encode()


class Opener:
    proxies_enabled = False
    redirects_enabled = False

    def __init__(
        self,
        manifest,
        *,
        report_step: str,
        fail_step: str | None = None,
        fail_read: str | None = None,
        fail_delete: str | None = None,
    ):
        self.manifest = manifest
        self.report_step = report_step
        self.fail_step = fail_step
        self.fail_read = fail_read
        self.fail_delete = fail_delete
        self.requests: list[tuple[str, str]] = []
        self.semantic_index = 0
        self.present = {MD: b"# complete report\n", PDF: b"%PDF-1.7\n"}

    def open(self, request: Request, timeout):
        assert timeout == 10
        self.requests.append((request.method, request.full_url))
        path = request.full_url.removeprefix("http://127.0.0.1:8000")
        if request.method == "POST":
            operation = self.manifest["operations"][self.semantic_index]
            self.semantic_index += 1
            assert path == operation["path"]
            if operation["step_id"] == self.fail_step:
                return Response(request.full_url, 500, b'{"error":"forced"}')
            if operation["step_id"] == self.report_step:
                return Response(
                    request.full_url, 200, report_response(), "text/event-stream"
                )
            status = operation["oracle"]["allowed_statuses"][0]
            body = json.dumps(
                {"value": " ".join(operation["oracle"]["required_literals"]) or "ok"}
            ).encode()
            return Response(request.full_url, status, body)
        if request.method == "GET":
            if path == self.fail_read and path in self.present:
                return Response(request.full_url, 404, b'{"detail":"forced"}')
            if path in self.present:
                media = "text/markdown" if path.endswith(".md") else "application/pdf"
                return Response(request.full_url, 200, self.present[path], media)
            return Response(request.full_url, 404, b'{"detail":"not found"}')
        if request.method == "DELETE":
            if path == self.fail_delete:
                return Response(request.full_url, 500, b'{"detail":"forced"}')
            if path in self.present:
                del self.present[path]
                return Response(request.full_url, 204, b"", "application/octet-stream")
            return Response(request.full_url, 404, b'{"detail":"not found"}')
        raise AssertionError((request.method, path))


def operation(step, path, run_id, *, statuses=(200,), mode="json", required=()):
    return {
        "step_id": step,
        "method": "POST",
        "path": path,
        "body": {"run_id": run_id, "input_message": step},
        "headers": {
            "Conversation-Id": run_id,
            "User-Message-ID": "msg-" + step,
        },
        "oracle": {
            "allowed_statuses": list(statuses),
            "response_mode": mode,
            "require_nonempty": True,
            "required_literals": list(required),
            "forbidden_literals": ["forced"],
        },
    }


def tiny(run_id="full-run-001"):
    return {
        "schema_version": 1,
        "case_id": "tiny-agent-media",
        "run_id": run_id,
        "reported_static_origins": [REPORT_ORIGIN + "/static/"],
        "operations": [
            operation("qa-mp4", "/chat/stream", run_id),
            operation("qa-mkv", "/chat/stream", run_id),
            operation("followup-qa", "/chat/stream", run_id),
            operation(
                "generate-report",
                "/generate/stream",
                run_id,
                mode="sse",
                required=("Markdown Report", "PDF Report"),
            ),
            operation(
                "reject-unsupported-media", "/chat/stream", run_id, statuses=(422,)
            ),
        ],
    }


def hitl(run_id="full-run-001"):
    interaction = "/executions/exe-01/interactions/int-01/response"
    return {
        "schema_version": 1,
        "case_id": "hitl-state-transcript",
        "run_id": run_id,
        "reported_static_origins": [REPORT_ORIGIN + "/static/"],
        "operations": [
            operation("new-prompt", "/generate/stream", run_id),
            operation("generate", interaction, run_id),
            operation("refine", interaction, run_id),
            operation("cancel", interaction, run_id),
            operation(
                "restart-and-check-persistence",
                "/generate/stream",
                run_id,
                mode="sse",
                required=("Markdown Report", "PDF Report"),
            ),
            operation("empty-submit", interaction, run_id, statuses=(422,)),
        ],
    }


def run(
    value,
    opener=None,
    *,
    ack="I_ACK_BASE_FULL_ENVELOPE_LOCAL_RUNTIME",
    origin="http://127.0.0.1:8000",
):
    report_step = (
        "generate-report"
        if value["case_id"] == "tiny-agent-media"
        else "restart-and-check-persistence"
    )
    selected = opener or Opener(value, report_step=report_step)
    return executor.execute_http(
        manifest=value,
        run_id=value["run_id"],
        acknowledgement=ack,
        origin=origin,
        opener_factory=lambda: selected,
    )


def test_plan_integrates_exact_corrected_full_envelopes_without_binding():
    plan = executor.compile_plan()
    assert plan["status"] == "pass" and plan["runtime_actions"] == 0
    assert plan["concrete_http_executor_ready"] is True
    assert plan["full_envelope_integrated"] is True
    assert plan["cleanup_semantics"] == "source_locked_report_step_exact_object_keys"
    assert [(row["case_id"], row["max_requests"]) for row in plan["cases"]] == [
        ("tiny-agent-media", 11),
        ("hitl-state-transcript", 12),
    ]
    assert plan["canonical_binding"] is False and plan["promotion_eligible"] is False


@pytest.mark.parametrize("factory, expected", [(tiny, 11), (hitl, 12)])
def test_full_success_is_exact_bounded_sanitized_and_cleans_pair(factory, expected):
    value = factory()
    opener = Opener(
        value,
        report_step=(
            "generate-report"
            if value["case_id"] == "tiny-agent-media"
            else "restart-and-check-persistence"
        ),
    )
    receipt = run(value, opener)
    assert receipt["budget"] == {
        "actions": expected,
        "max_actions": expected,
        "requests": expected,
        "max_requests": expected,
    }
    assert [row["extension"] for row in receipt["artifacts"]] == ["md", "pdf"]
    assert opener.present == {}
    assert [row["step_id"] for row in receipt["observations"]][-6:] == [
        "render-markdown",
        "render-pdf",
        "delete-markdown",
        "delete-pdf",
        "verify-markdown-absent",
        "verify-pdf-absent",
    ]
    assert not receipt["promotion_eligible"] and not receipt["canonical_state_advanced"]
    encoded = json.dumps(receipt)
    assert MD not in encoded and PDF not in encoded
    assert "/chat/stream" not in encoded and "/generate/stream" not in encoded
    assert (
        executor.validate_receipt(receipt)["status"]
        == "candidate_receipt_valid_non_promoting"
    )


def test_failure_after_pair_runs_both_exact_deletes_and_postconditions():
    value = tiny()
    opener = Opener(
        value, report_step="generate-report", fail_step="reject-unsupported-media"
    )
    with pytest.raises(executor.EnvelopeError, match="oracle_failed"):
        run(value, opener)
    assert opener.present == {}
    assert opener.requests[-4:] == [
        ("DELETE", "http://127.0.0.1:8000" + MD),
        ("DELETE", "http://127.0.0.1:8000" + PDF),
        ("GET", "http://127.0.0.1:8000" + MD),
        ("GET", "http://127.0.0.1:8000" + PDF),
    ]


def test_failed_read_still_cleans_and_delete_failure_is_cleanup_failure():
    value = tiny()
    opener = Opener(value, report_step="generate-report", fail_read=PDF)
    with pytest.raises(executor.EnvelopeError, match="oracle_failed"):
        run(value, opener)
    assert opener.present == {}

    opener = Opener(value, report_step="generate-report", fail_delete=MD)
    with pytest.raises(executor.EnvelopeError, match="cleanup_failed"):
        run(value, opener)
    assert MD in opener.present and PDF not in opener.present
    assert opener.requests[-2:] == [
        ("GET", "http://127.0.0.1:8000" + MD),
        ("GET", "http://127.0.0.1:8000" + PDF),
    ]


def test_authorization_loopback_and_manifest_are_fail_closed():
    with pytest.raises(executor.EnvelopeError, match="authorization_required"):
        run(tiny(), ack="wrong")
    for origin in (
        "http://localhost:8000",
        "http://10.0.0.1:8000",
        "https://example.com:443",
    ):
        with pytest.raises(executor.EnvelopeError, match="authorization_required"):
            run(tiny(), origin=origin)
    value = tiny()
    value["operations"][0]["headers"]["Conversation-Id"] = "foreign"
    with pytest.raises(executor.EnvelopeError, match="invalid_manifest"):
        run(value)
    value = tiny()
    value["operations"][0]["path"] = "/chat/foreign"
    with pytest.raises(executor.EnvelopeError, match="invalid_manifest"):
        run(value)
    value = tiny()
    value["operations"][0]["oracle"]["allowed_statuses"] = [302]
    with pytest.raises(executor.EnvelopeError, match="invalid_manifest"):
        run(value)
    value = tiny()
    value["operations"][3]["oracle"]["response_mode"] = "json"
    with pytest.raises(executor.EnvelopeError, match="invalid_manifest"):
        run(value)
    value = tiny()
    value["operations"][3]["oracle"]["required_literals"] = ["Markdown Report"]
    with pytest.raises(executor.EnvelopeError, match="invalid_manifest"):
        run(value)


def test_no_pair_or_ambiguous_pair_fails_without_a_success_receipt():
    value = tiny()
    opener = Opener(value, report_step="never")
    with pytest.raises(executor.EnvelopeError, match="oracle_failed"):
        run(value, opener)

    malformed = copy.deepcopy(value)
    body = report_response().replace(PDF.encode(), MD.encode())

    class Ambiguous(Opener):
        def open(self, request, timeout):
            response = super().open(request, timeout)
            if (
                self.manifest["operations"][self.semantic_index - 1]["step_id"]
                == "generate-report"
            ):
                return Response(request.full_url, 200, body, "text/event-stream")
            return response

    opener = Ambiguous(malformed, report_step="never")
    with pytest.raises(executor.EnvelopeError, match="oracle_failed"):
        run(malformed, opener)


def test_pair_in_non_report_step_is_never_registered_or_cleaned():
    value = tiny()

    class CrossStepPair(Opener):
        def open(self, request, timeout):
            step = (
                self.manifest["operations"][self.semantic_index]["step_id"]
                if request.method == "POST"
                else None
            )
            response = super().open(request, timeout)
            if step == "generate-report":
                body = b'data: {"content":"Markdown Report and PDF Report unavailable"}\n\n'
                return Response(request.full_url, 200, body, "text/event-stream")
            return response

    opener = CrossStepPair(value, report_step="qa-mp4")
    with pytest.raises(executor.EnvelopeError, match="oracle_failed"):
        run(value, opener)
    assert opener.present == {MD: b"# complete report\n", PDF: b"%PDF-1.7\n"}
    assert all(method == "POST" for method, _url in opener.requests)


def test_receipt_rejects_forged_cleanup_and_order():
    receipt = run(tiny())
    forged = copy.deepcopy(receipt)
    forged["cleanup"]["recursive_delete_claimed"] = True
    with pytest.raises(executor.EnvelopeError, match="invalid_receipt"):
        executor.validate_receipt(forged)
    forged = copy.deepcopy(receipt)
    forged["observations"][-1], forged["observations"][-2] = (
        forged["observations"][-2],
        forged["observations"][-1],
    )
    with pytest.raises(executor.EnvelopeError, match="invalid_receipt"):
        executor.validate_receipt(forged)
    forged = copy.deepcopy(receipt)
    forged["artifacts"][1]["stem_sha256"] = "f" * 64
    with pytest.raises(executor.EnvelopeError, match="invalid_receipt"):
        executor.validate_receipt(forged)
