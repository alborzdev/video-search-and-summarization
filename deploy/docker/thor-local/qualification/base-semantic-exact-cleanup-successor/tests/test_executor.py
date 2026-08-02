from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys

import pytest

HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "base_exact_cleanup_executor", HERE / "executor.py"
)
assert SPEC and SPEC.loader
executor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = executor
SPEC.loader.exec_module(executor)


MD = "/static/vss_report_sensor_20260802_120000.md"
PDF = "/static/vss_report_sensor_20260802_120000.pdf"
REPORT_ORIGIN = "http://reports.local:8000"


class Response:
    def __init__(
        self, url: str, status: int, body: bytes, media: str = "application/json"
    ):
        self.status = status
        self._url = url
        self._body = body
        self.headers = {"Content-Length": str(len(body)), "Content-Type": media}
        self.closed = False

    def geturl(self):
        return self._url

    def read(self, size=-1):
        return self._body if size < 0 else self._body[:size]

    def close(self):
        self.closed = True


class Opener:
    proxies_enabled = False
    redirects_enabled = False

    def __init__(
        self,
        *,
        generation_body: bytes | None = None,
        fail_read: str | None = None,
        fail_delete: str | None = None,
    ):
        self.generation_body = generation_body or report_response()
        self.fail_read = fail_read
        self.fail_delete = fail_delete
        self.requests = []
        self.present = {MD: b"# report\n", PDF: b"%PDF-1.7\n"}

    def open(self, request, timeout):
        assert timeout == 10
        self.requests.append((request.method, request.full_url))
        path = request.full_url.removeprefix("http://127.0.0.1:8000")
        if path == "/generate/stream":
            return Response(
                request.full_url, 200, self.generation_body, "text/event-stream"
            )
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


def report_response(md: str = MD, pdf: str = PDF, origin: str = REPORT_ORIGIN) -> bytes:
    content = f"[Markdown Report]({origin}{md}) and [PDF Report]({origin}{pdf})"
    return (
        "data: " + json.dumps({"type": "final", "content": content}) + "\n\n"
    ).encode()


def manifest(run_id: str = "base-clean-001"):
    return {
        "schema_version": 1,
        "run_id": run_id,
        "reported_static_origins": [REPORT_ORIGIN + "/static/"],
        "generation": {
            "method": "POST",
            "path": "/generate/stream",
            "body": {
                "run_id": run_id,
                "input_message": "Generate a report for the reviewed tiny sensor",
            },
            "headers": {"Conversation-Id": run_id, "User-Message-ID": "message-001"},
            "oracle": {
                "allowed_statuses": [200],
                "response_mode": "sse",
                "required_literals": ["Markdown Report", "PDF Report"],
                "forbidden_literals": ["forced"],
            },
        },
    }


def run(
    value=None,
    opener=None,
    *,
    ack="I_ACK_BASE_EXACT_REPORT_CLEANUP",
    origin="http://127.0.0.1:8000",
):
    selected_manifest = value or manifest()
    selected_opener = opener or Opener()
    return executor.execute_http(
        manifest=selected_manifest,
        run_id=selected_manifest["run_id"],
        acknowledgement=ack,
        origin=origin,
        opener_factory=lambda: selected_opener,
    )


def test_plan_binds_real_exact_file_semantics_and_disclaims_canonical_envelope():
    plan = executor.compile_plan()
    assert plan["status"] == "pass"
    assert plan["static_api_semantics"] == "exact_object_key"
    assert plan["namespace_delete_supported"] is False
    assert plan["exact_cleanup_request_count"] == 7
    assert plan["frozen_base_envelopes"] == {
        "tiny-agent-media": 8,
        "hitl-state-transcript": 11,
    }
    assert plan["required_exact_cleanup_success_envelopes"] == {
        "tiny-agent-media": 11,
        "hitl-state-transcript": 12,
    }
    assert plan["canonical_envelope_binding"] is False
    assert plan["runtime_actions"] == 0 and plan["promotion_eligible"] is False


def test_extract_requires_one_exact_same_stem_markdown_pdf_pair():
    allowed = {("http", "reports.local:8000")}
    assert executor.extract_exact_report_pair(report_response(), allowed) == (MD, PDF)
    with pytest.raises(executor.CleanupError, match="oracle_failed"):
        executor.extract_exact_report_pair(report_response(pdf=MD), allowed)
    with pytest.raises(executor.CleanupError, match="oracle_failed"):
        executor.extract_exact_report_pair(
            report_response(pdf="/static/vss_report_other_20260802_120000.pdf"), allowed
        )
    with pytest.raises(executor.CleanupError, match="oracle_failed"):
        executor.extract_exact_report_pair(
            report_response(origin="http://foreign.local:8000"), allowed
        )
    with pytest.raises(executor.CleanupError, match="oracle_failed"):
        executor.extract_exact_report_pair(
            b"data: /static/base-clean-001/report.md\n", allowed
        )


def test_live_cleanup_reads_deletes_and_postchecks_each_exact_report_key():
    opener = Opener()
    receipt = run(opener=opener)
    assert [row["extension"] for row in receipt["artifacts"]] == ["md", "pdf"]
    assert receipt["budget"] == {
        "actions": 7,
        "max_actions": 7,
        "requests": 7,
        "max_requests": 7,
    }
    assert receipt["cleanup"] == {
        "semantics": "exact_object_key",
        "artifact_count": 2,
        "artifact_set_sha256": receipt["cleanup"]["artifact_set_sha256"],
        "pair_stem_sha256": receipt["cleanup"]["pair_stem_sha256"],
        "all_paths_from_generation_response": True,
        "delete_each_exact_key": True,
        "postcondition_each_404": True,
        "namespace_delete_attempted": False,
        "recursive_delete_claimed": False,
        "foreign_resources_mutated": False,
        "preexisting_absence_proven": False,
    }
    expected = [
        ("POST", "http://127.0.0.1:8000/generate/stream"),
        ("GET", "http://127.0.0.1:8000" + MD),
        ("GET", "http://127.0.0.1:8000" + PDF),
        ("DELETE", "http://127.0.0.1:8000" + MD),
        ("DELETE", "http://127.0.0.1:8000" + PDF),
        ("GET", "http://127.0.0.1:8000" + MD),
        ("GET", "http://127.0.0.1:8000" + PDF),
    ]
    assert opener.requests == expected
    encoded = json.dumps(receipt)
    assert (
        MD not in encoded and PDF not in encoded and "/generate/stream" not in encoded
    )
    assert (
        executor.validate_receipt(receipt)["status"]
        == "candidate_receipt_valid_non_promoting"
    )


def test_failed_read_still_attempts_exact_cleanup_for_both_members():
    opener = Opener(fail_read=PDF)
    with pytest.raises(executor.CleanupError, match="oracle_failed"):
        run(opener=opener)
    assert [(method, url) for method, url in opener.requests if method == "DELETE"] == [
        ("DELETE", "http://127.0.0.1:8000" + MD),
        ("DELETE", "http://127.0.0.1:8000" + PDF),
    ]
    assert opener.present == {}


def test_failed_generation_oracle_still_cleans_exact_pair_from_response():
    value = manifest()
    value["generation"]["oracle"]["forbidden_literals"] = ["vss_report_"]
    opener = Opener()
    with pytest.raises(executor.CleanupError, match="oracle_failed"):
        run(value, opener)
    assert opener.present == {}
    assert len(opener.requests) == 7


def test_delete_failure_is_cleanup_failure_and_other_member_is_still_removed():
    opener = Opener(fail_delete=MD)
    with pytest.raises(executor.CleanupError, match="cleanup_failed"):
        run(opener=opener)
    assert PDF not in opener.present and MD in opener.present
    assert opener.requests[-2:] == [
        ("GET", "http://127.0.0.1:8000" + MD),
        ("GET", "http://127.0.0.1:8000" + PDF),
    ]


def test_authorization_loopback_manifest_and_receipt_are_fail_closed():
    with pytest.raises(executor.CleanupError, match="authorization_required"):
        run(ack="wrong")
    with pytest.raises(executor.CleanupError, match="authorization_required"):
        run(origin="http://localhost:8000")
    value = manifest()
    value["generation"]["headers"]["Conversation-Id"] = "foreign"
    with pytest.raises(executor.CleanupError, match="invalid_manifest"):
        run(value)
    value = manifest()
    value["reported_static_origins"] = ["http://reports.local:8000/other/"]
    with pytest.raises(executor.CleanupError, match="invalid_manifest"):
        run(value)

    receipt = run()
    forged = copy.deepcopy(receipt)
    forged["cleanup"]["recursive_delete_claimed"] = True
    with pytest.raises(executor.CleanupError, match="invalid_receipt"):
        executor.validate_receipt(forged)
    forged = copy.deepcopy(receipt)
    forged["artifacts"][1]["path_sha256"] = forged["artifacts"][0]["path_sha256"]
    with pytest.raises(executor.CleanupError, match="invalid_receipt"):
        executor.validate_receipt(forged)
    forged = copy.deepcopy(receipt)
    forged["artifacts"][1]["stem_sha256"] = "f" * 64
    with pytest.raises(executor.CleanupError, match="invalid_receipt"):
        executor.validate_receipt(forged)
