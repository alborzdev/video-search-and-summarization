from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from urllib.request import Request

import pytest

HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "base_owned_fixture_executor", HERE / "executor.py"
)
assert SPEC and SPEC.loader
executor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = executor
SPEC.loader.exec_module(executor)

RUN = "owned-base-001"
REPORT_ORIGIN = "http://reports.local:8000"
MD = "/static/vss_report_thor-base-avsync-c569a1a3_20260802_120000.md"
PDF = "/static/vss_report_thor-base-avsync-c569a1a3_20260802_120000.pdf"
SECONDARY = b"\x1a\x45\xdf\xa3bounded-matroska-fixture"
SECONDARY_SHA = hashlib.sha256(SECONDARY).hexdigest()

REPORT = b"""# Exact fixture report

## Summary

The tracked audio/video synchronization fixture was analyzed.

## Visual Timeline

At the beginning, the large disk is predominantly green with a white sector.
At the end, the red disk continues alternating between bright and dark.

## Findings

The visual facts are internally consistent.
"""

PARAPHRASED_REPORT = b"""# Exact fixture report

## Summary

The tracked synchronization fixture was analyzed.

## Visual Timeline

Initially, the large circle is green except for a white wedge.
In the final frames, the red circle keeps flashing between intensities.

## Findings

The observed visual facts are consistent.
"""


class Response:
    def __init__(self, url: str, status: int, body: bytes, media="application/json"):
        self.status = status
        self._url = url
        self._body = body
        self.headers = {
            "Content-Length": str(len(body)),
            "Content-Type": media,
        }
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


def operation(step, path, run_id=RUN, *, status=200, mode="json", required=()):
    body = {"run_id": run_id, "input_message": f"request for {step}"}
    primary_id = executor._contract()["fixture"]["primary_agent_media_id"]
    primary_sha = executor._contract()["fixture"]["primary_media_sha256"]
    if step in {
        "qa-mp4",
        "followup-qa",
        "generate-report",
        "restart-and-check-persistence",
    }:
        body.update({"selected_media": primary_id, "fixture_sha256": primary_sha})
    if step == "qa-mkv":
        body.update(
            {
                "selected_media": "thor-base-avsync-c569a1a3.mkv",
                "fixture_sha256": SECONDARY_SHA,
            }
        )
    return {
        "step_id": step,
        "method": "POST",
        "path": path,
        "body": body,
        "headers": {
            "Conversation-Id": run_id,
            "User-Message-ID": "msg-" + step,
        },
        "oracle": {
            "allowed_statuses": [status],
            "response_mode": mode,
            "require_nonempty": True,
            "required_literals": list(required),
            "forbidden_literals": ["forced"],
        },
    }


def tiny(secondary_path: Path):
    return {
        "schema_version": 1,
        "case_id": "tiny-agent-media",
        "run_id": RUN,
        "reported_static_origins": [REPORT_ORIGIN + "/static/"],
        "fixture_binding": {
            "fixture_id": "thor-base-avsync-c569a1a3-v1",
            "primary_agent_media_id": "thor-base-avsync-c569a1a3.mp4",
            "secondary_agent_media_id": "thor-base-avsync-c569a1a3.mkv",
            "secondary_local_path": str(secondary_path),
            "secondary_sha256": SECONDARY_SHA,
            "secondary_bytes": len(SECONDARY),
        },
        "operations": [
            operation(
                "qa-mp4",
                "/chat/stream",
                required=("predominantly green", "white sector"),
            ),
            operation("qa-mkv", "/chat/stream", required=("does not appear",)),
            operation(
                "followup-qa",
                "/chat/stream",
                required=("small white circle", "to the right"),
            ),
            operation(
                "generate-report",
                "/generate/stream",
                mode="sse",
                required=("Markdown Report", "PDF Report"),
            ),
            operation("reject-unsupported-media", "/chat/stream", status=422),
        ],
    }


def hitl(secondary_path: Path):
    interaction = "/executions/exe-01/interactions/int-01/response"
    return {
        "schema_version": 1,
        "case_id": "hitl-state-transcript",
        "run_id": RUN,
        "reported_static_origins": [REPORT_ORIGIN + "/static/"],
        "fixture_binding": {
            "fixture_id": "thor-base-avsync-c569a1a3-v1",
            "primary_agent_media_id": "thor-base-avsync-c569a1a3.mp4",
            "secondary_agent_media_id": "thor-base-avsync-c569a1a3.mkv",
            "secondary_local_path": str(secondary_path),
            "secondary_sha256": SECONDARY_SHA,
            "secondary_bytes": len(SECONDARY),
        },
        "operations": [
            operation("new-prompt", "/generate/stream"),
            operation("generate", interaction),
            operation("refine", interaction),
            operation("cancel", interaction, required=("cancel",)),
            operation(
                "restart-and-check-persistence",
                "/generate/stream",
                mode="sse",
                required=("Markdown Report", "PDF Report"),
            ),
            operation("empty-submit", interaction, status=422),
        ],
    }


class Opener:
    proxies_enabled = False
    redirects_enabled = False

    def __init__(self, manifest, root: Path, *, mutate_negative=False, precreate=False):
        self.manifest = manifest
        self.root = root
        self.semantic_index = 0
        self.mutate_negative = mutate_negative
        self.requests = []
        if precreate:
            self._write_pair()

    def _disk(self, path: str) -> Path:
        return self.root / path.removeprefix("/static/")

    def _write(self, path: str, body: bytes, media: str):
        target = self._disk(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        target.with_name(f".{target.name}.vss-object.json").write_text(
            json.dumps({"content_type": media}), encoding="utf-8"
        )

    def _write_pair(self):
        self._write(MD, REPORT, "text/markdown")
        self._write(PDF, b"%PDF-1.7\nfixture", "application/pdf")

    def _remove(self, path: str):
        target = self._disk(path)
        target.unlink(missing_ok=True)
        target.with_name(f".{target.name}.vss-object.json").unlink(missing_ok=True)

    def open(self, request: Request, timeout):
        assert timeout == 10
        self.requests.append((request.method, request.full_url))
        path = request.full_url.removeprefix("http://127.0.0.1:8000")
        if request.method == "POST":
            operation = self.manifest["operations"][self.semantic_index]
            self.semantic_index += 1
            step = operation["step_id"]
            assert path == operation["path"]
            if step in {"generate-report", "restart-and-check-persistence"}:
                self._write_pair()
                return Response(
                    request.full_url, 200, report_response(), "text/event-stream"
                )
            if self.mutate_negative and step in {
                "reject-unsupported-media",
                "cancel",
                "empty-submit",
            }:
                foreign = self.root / "agent_report_20260802_010101.md"
                foreign.write_text("mutated", encoding="utf-8")
            if step == "qa-mp4":
                body = b'{"answer":"predominantly green disk with a white sector"}'
            elif step == "qa-mkv":
                body = b'{"answer":"the questioned distractor does not appear"}'
            elif step == "followup-qa":
                body = b'{"answer":"the small white circle is to the right"}'
            elif step == "cancel":
                body = b'{"status":"cancelled"}'
            elif operation["oracle"]["allowed_statuses"][0] == 422:
                body = b'{"detail":"invalid request"}'
            else:
                body = b'{"status":"ok"}'
            return Response(
                request.full_url, operation["oracle"]["allowed_statuses"][0], body
            )
        if request.method == "GET":
            target = self._disk(path)
            if target.is_file():
                media = "text/markdown" if path.endswith(".md") else "application/pdf"
                return Response(request.full_url, 200, target.read_bytes(), media)
            return Response(request.full_url, 404, b'{"detail":"not found"}')
        if request.method == "DELETE":
            target = self._disk(path)
            if target.is_file():
                self._remove(path)
                return Response(request.full_url, 204, b"", "application/octet-stream")
            return Response(request.full_url, 404, b'{"detail":"not found"}')
        raise AssertionError((request.method, path))


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    root = tmp_path / "agent-reports"
    root.mkdir()
    secondary = tmp_path / "exact-secondary.mkv"
    secondary.write_bytes(SECONDARY)
    foreign = root / "unrelated-not-a-report.txt"
    foreign.write_text("foreign baseline", encoding="utf-8")
    monkeypatch.setattr(executor, "OBJECT_STORE_ROOT", root)
    return root, secondary


def run(value, root, opener=None, ack="I_ACK_BASE_OWNED_FIXTURE_LOCAL_RUNTIME"):
    selected = opener or Opener(value, root)
    return executor.execute_http(
        manifest=value,
        run_id=RUN,
        acknowledgement=ack,
        origin="http://127.0.0.1:8000",
        opener_factory=lambda: selected,
        quiescence_waiter=lambda _seconds: None,
    )


def test_plan_is_inert_and_honestly_records_remaining_media_identity_gap():
    plan = executor.compile_plan()
    assert plan["status"] == "pass" and plan["runtime_actions"] == 0
    assert plan["primary_pixel_fixture_materialized"] is True
    assert plan["preexisting_exact_pair_absence_observable"] is True
    assert plan["negative_request_report_delta_observable"] is True
    assert plan["agent_media_digest_readback_proven"] is False
    assert not plan["canonical_binding"] and not plan["promotion_eligible"]


@pytest.mark.parametrize("factory", [tiny, hitl])
def test_success_proves_preabsence_semantics_negative_no_delta_and_restoration(
    factory, runtime
):
    root, secondary = runtime
    value = factory(secondary)
    before = {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    receipt = run(value, root)
    after = {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    assert before == after
    assert receipt["object_store"]["preexisting_report_pair_absence_proven"] is True
    assert receipt["object_store"]["post_snapshot_equals_pre_snapshot"] is True
    assert receipt["semantics"]["negative_steps_no_report_delta"] == (
        ["reject-unsupported-media"]
        if value["case_id"] == "tiny-agent-media"
        else ["cancel", "empty-submit"]
    )
    assert receipt["fixture"]["agent_media_digest_readback_proven"] is False
    assert (
        executor.validate_receipt(receipt)["status"]
        == "candidate_receipt_valid_non_promoting"
    )


def test_preexisting_exact_report_pair_is_rejected_without_cleanup_ownership(runtime):
    root, secondary = runtime
    value = tiny(secondary)
    opener = Opener(value, root, precreate=True)
    with pytest.raises(executor.ClosureError, match="snapshot_error"):
        run(value, root, opener)
    assert opener.requests == []


@pytest.mark.parametrize("factory", [tiny, hitl])
def test_invalid_or_cancelled_request_report_delta_is_rejected(factory, runtime):
    root, secondary = runtime
    value = factory(secondary)
    opener = Opener(value, root, mutate_negative=True)
    with pytest.raises(executor.ClosureError, match="oracle_failed"):
        run(value, root, opener)


def test_pixel_distractor_followup_and_report_semantics_are_fail_closed(runtime):
    root, secondary = runtime
    value = tiny(secondary)

    class WrongPixel(Opener):
        def open(self, request, timeout):
            response = super().open(request, timeout)
            if request.method == "POST" and self.semantic_index == 1:
                return Response(
                    request.full_url,
                    200,
                    b'{"answer":"Predominantly green with a white sector; a blue square is visible."}',
                )
            return response

    with pytest.raises(executor.ClosureError, match="oracle_failed"):
        run(value, root, WrongPixel(value, root))

    class WrongReport(Opener):
        def _write_pair(self):
            self._write(
                MD, REPORT.replace(b"## Findings", b"## Other"), "text/markdown"
            )
            self._write(PDF, b"%PDF-1.7\nfixture", "application/pdf")

    with pytest.raises(executor.ClosureError, match="oracle_failed"):
        run(value, root, WrongReport(value, root))

    class HallucinatedAbsentEvent(Opener):
        def _write_pair(self):
            self._write(
                MD,
                REPORT.replace(
                    b"The visual facts are internally consistent.",
                    b"A blue geometric square is visible.",
                ),
                "text/markdown",
            )
            self._write(PDF, b"%PDF-1.7\nfixture", "application/pdf")

    with pytest.raises(executor.ClosureError, match="oracle_failed"):
        run(value, root, HallucinatedAbsentEvent(value, root))


def test_report_event_oracle_accepts_semantic_paraphrase(runtime):
    root, secondary = runtime
    value = tiny(secondary)

    class ParaphrasedReport(Opener):
        def _write_pair(self):
            self._write(MD, PARAPHRASED_REPORT, "text/markdown")
            self._write(PDF, b"%PDF-1.7\nfixture", "application/pdf")

    receipt = run(value, root, ParaphrasedReport(value, root))
    assert receipt["semantics"]["beginning_events_verified"] is True
    assert receipt["semantics"]["ending_events_verified"] is True


def test_orphan_report_metadata_makes_prestate_nonempty(runtime):
    root, secondary = runtime
    orphan = root / ".vss_report_orphan_20260802_120000.md.vss-object.json"
    orphan.write_text('{"content_type":"text/markdown"}', encoding="utf-8")
    opener = Opener(tiny(secondary), root)
    with pytest.raises(executor.ClosureError, match="snapshot_error"):
        run(tiny(secondary), root, opener)
    assert opener.requests == []


def test_json_loader_rejects_duplicate_keys_and_nonfinite_values(tmp_path):
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"key":1,"key":2}', encoding="utf-8")
    with pytest.raises(executor.ClosureError, match="configuration_error"):
        executor._json(duplicate)

    nonfinite = tmp_path / "nonfinite.json"
    nonfinite.write_text('{"key":NaN}', encoding="utf-8")
    with pytest.raises(executor.ClosureError, match="configuration_error"):
        executor._json(nonfinite)


def test_repo_reader_rejects_symlink_components(tmp_path, monkeypatch):
    real = tmp_path / "real"
    real.mkdir()
    (real / "file.txt").write_text("reviewed", encoding="utf-8")
    (tmp_path / "redirect").symlink_to(real, target_is_directory=True)
    monkeypatch.setattr(executor, "ROOT", tmp_path)
    with pytest.raises(executor.ClosureError, match="configuration_error"):
        executor._repo_path("redirect/file.txt")


def test_manifest_requires_exact_media_tokens_and_rejects_answer_leakage(runtime):
    root, secondary = runtime
    value = tiny(secondary)
    del value["operations"][0]["body"]["fixture_sha256"]
    with pytest.raises(executor.ClosureError, match="invalid_manifest"):
        run(value, root)

    value = tiny(secondary)
    value["operations"][0]["body"]["hint"] = "predominantly green"
    with pytest.raises(executor.ClosureError, match="invalid_manifest"):
        run(value, root)

    value = tiny(secondary)
    value["fixture_binding"]["secondary_sha256"] = "0" * 64
    value["operations"][1]["body"]["fixture_sha256"] = "0" * 64
    with pytest.raises(executor.ClosureError, match="fixture_error"):
        run(value, root)


def test_authorization_precedes_secondary_file_read(runtime):
    root, secondary = runtime
    value = tiny(secondary)
    value["fixture_binding"]["secondary_local_path"] = "/definitely/not/read.mkv"
    with pytest.raises(executor.ClosureError, match="authorization_required"):
        run(value, root, ack="wrong")


def test_receipt_rejects_forged_preabsence_and_snapshot_equality(runtime):
    root, secondary = runtime
    receipt = run(tiny(secondary), root)
    forged = copy.deepcopy(receipt)
    forged["object_store"]["preexisting_report_pair_absence_proven"] = False
    with pytest.raises(executor.ClosureError, match="invalid_receipt"):
        executor.validate_receipt(forged)
    forged = copy.deepcopy(receipt)
    forged["object_store"]["post_snapshot_sha256"] = "f" * 64
    with pytest.raises(executor.ClosureError, match="invalid_receipt"):
        executor.validate_receipt(forged)
