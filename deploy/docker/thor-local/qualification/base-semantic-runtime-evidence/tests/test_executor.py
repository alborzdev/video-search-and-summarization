from __future__ import annotations
import copy
import importlib.util
import json
from pathlib import Path
import sys
from urllib.request import Request
import pytest

HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("base_semantic_executor", HERE / "executor.py")
assert SPEC and SPEC.loader
executor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = executor
SPEC.loader.exec_module(executor)


class Response:
    def __init__(self, url, status, body, media="application/json"):
        self.status, self._url, self._body = status, url, body
        self.headers = {"Content-Length": str(len(body)), "Content-Type": media}
        self.closed = False
    def geturl(self): return self._url
    def read(self, size=-1): return self._body if size < 0 else self._body[:size]
    def close(self): self.closed = True


class Opener:
    proxies_enabled = False
    redirects_enabled = False
    def __init__(self, manifest, fail_step=None):
        self.manifest, self.fail_step, self.requests = manifest, fail_step, []
    def open(self, request: Request, timeout):
        assert timeout == 10
        self.requests.append(request)
        op = self.manifest["operations"][len(self.requests) - 1]
        if op["step_id"] == self.fail_step:
            return Response(request.full_url, 500, b'{"error":"forced"}')
        status = op["oracle"]["allowed_statuses"][0]
        if op["oracle"]["response_mode"] == "empty":
            return Response(request.full_url, status, b"", "application/octet-stream")
        body = json.dumps({"value": " ".join(op["oracle"]["required_literals"]) or "ok"}).encode()
        return Response(request.full_url, status, body)


def op(step, method, path, run_id, statuses=(200,), required=(), mode="json"):
    body, headers = None, {}
    if method == "POST":
        body = {"run_id": run_id, "input_message": step}
        headers = {"Conversation-Id": run_id, "User-Message-ID": "msg-" + step}
    return {"step_id": step, "method": method, "path": path, "body": body, "headers": headers, "oracle": {"allowed_statuses": list(statuses), "response_mode": mode, "require_nonempty": mode != "empty", "required_literals": list(required), "forbidden_literals": ["forced"]}}


def tiny(run_id="run-001"):
    owned = "/static/" + run_id
    return {"schema_version": 1, "case_id": "tiny-agent-media", "run_id": run_id, "owned_namespace_path": owned, "operations": [
        op("capture-pre-state", "GET", owned, run_id, (404,)),
        op("qa-mp4", "POST", "/chat/stream", run_id),
        op("qa-mkv", "POST", "/chat/stream", run_id),
        op("followup-qa", "POST", "/chat/stream", run_id),
        op("generate-report", "POST", "/generate/stream", run_id, required=(owned,)),
        op("reject-unsupported-media", "POST", "/chat/stream", run_id, (422,)),
        op("restore-owned-state", "DELETE", owned, run_id, (204,), mode="empty"),
        op("verify-postconditions", "GET", owned, run_id, (404,))]}


def hitl(run_id="run-002"):
    owned, interaction = "/static/" + run_id, "/executions/exe-01/interactions/int-01/response"
    return {"schema_version": 1, "case_id": "hitl-state-transcript", "run_id": run_id, "owned_namespace_path": owned, "operations": [
        op("capture-pre-state", "GET", owned, run_id, (404,)),
        op("new-prompt", "POST", "/generate/stream", run_id),
        op("generate", "POST", interaction, run_id), op("refine", "POST", interaction, run_id), op("cancel", "POST", interaction, run_id),
        op("render-markdown", "GET", owned + "/report.md", run_id), op("render-pdf", "GET", owned + "/report.pdf", run_id),
        op("restart-and-check-persistence", "POST", "/generate/stream", run_id), op("empty-submit", "POST", interaction, run_id, (422,)),
        op("restore-owned-state", "DELETE", owned, run_id, (204,), mode="empty"), op("verify-postconditions", "GET", owned, run_id, (404,))]}


def run(manifest, opener=None, origin="http://127.0.0.1:8000", ack="I_ACK_BASE_SEMANTIC_LOCAL_RUNTIME"):
    selected = opener or Opener(manifest)
    return executor.execute_http(manifest=manifest, run_id=manifest["run_id"], acknowledgement=ack, origin=origin, opener_factory=lambda: selected)


def test_plan_exact_three_cases():
    plan = executor.compile_plan()
    assert plan["status"] == "pass" and plan["runtime_actions"] == 0 and not plan["promotion_eligible"]
    assert [(x["planning_requirement_id"], x["max_requests"]) for x in plan["cases"]] == [("tiny-agent-media", 8), ("hitl-state-transcript", 11), ("ui-tiny-media", 11)]


@pytest.mark.parametrize("factory", [tiny, hitl])
def test_live_core_is_exact_bounded_sanitized_and_nonpromoting(factory):
    manifest = factory()
    receipt = run(manifest)
    count = len(manifest["operations"])
    assert receipt["budget"] == {"actions": count, "max_actions": count, "requests": count, "max_requests": count}
    assert receipt["cleanup"] == {"owned_namespace_sha256": receipt["cleanup"]["owned_namespace_sha256"], "preexisting_absent": True, "delete_exact_owned_only": True, "postcondition_absent": True, "foreign_resources_mutated": False}
    assert not receipt["promotion_eligible"] and not receipt["canonical_state_advanced"]
    encoded = json.dumps(receipt)
    assert manifest["owned_namespace_path"] not in encoded and "/chat/stream" not in encoded and "input_message" not in encoded


def test_ack_and_loopback_are_fail_closed():
    with pytest.raises(executor.ExecutorError, match="authorization_required"): run(tiny(), ack="wrong")
    for origin in ("http://localhost:8000", "http://10.0.0.1:8000", "https://example.com:443"):
        with pytest.raises(executor.ExecutorError, match="authorization_required"): run(tiny(), origin=origin)


def test_manifest_drift_and_foreign_cleanup_rejected():
    manifest = tiny(); manifest["operations"][-2]["path"] = "/static/foreign"
    with pytest.raises(executor.ExecutorError, match="invalid_manifest"): run(manifest)
    manifest = tiny(); manifest["operations"][2]["headers"]["Conversation-Id"] = "foreign"
    with pytest.raises(executor.ExecutorError, match="invalid_manifest"): run(manifest)
    manifest = tiny(); manifest["operations"][2]["body"] = {"input_message": "missing owner"}
    with pytest.raises(executor.ExecutorError, match="invalid_manifest"): run(manifest)
    manifest = tiny(); manifest["operations"][2]["oracle"]["allowed_statuses"] = [302]
    with pytest.raises(executor.ExecutorError, match="invalid_manifest"): run(manifest)
    manifest = tiny(); manifest["operations"][2]["oracle"]["required_literals"] = ["forced"]
    with pytest.raises(executor.ExecutorError, match="invalid_manifest"): run(manifest)


def test_failure_after_registration_attempts_only_owned_cleanup():
    manifest = tiny(); opener = Opener(manifest, fail_step="reject-unsupported-media")
    with pytest.raises(executor.ExecutorError, match="oracle_failed"): run(manifest, opener)
    assert [x.full_url for x in opener.requests[-2:]] == ["http://127.0.0.1:8000/static/run-001"] * 2


def ui_receipt():
    case = executor._one(executor._contract()["cases"], "planning_requirement_id", "ui-tiny-media")
    observations = [{"sequence": i, "step_id": step["id"], "status": "pass", "result_code": step["id"].replace("-", "_") + "_verified", "response_status": 0, "response_bytes": 0, "response_sha256": "0" * 64, "oracle_sha256": "1" * 64} for i, step in enumerate(case["workflow"], 1)]
    contract_sha = executor.hashlib.sha256(executor._read(executor.CONTRACT)).hexdigest()
    return {"schema_version": 1, "package_id": "base-semantic-runtime-evidence", "mode": "manual-browser-candidate", "status": "candidate_evidence_complete_non_promoting", "promotion_eligible": False, "planning_requirement_id": "ui-tiny-media", "capability_id": case["capability_id"], "oracle_id": case["oracle_id"], "contract_sha256": contract_sha, "manifest_sha256": "3" * 64, "target_origin_sha256": "4" * 64, "identity": {"run_id": "ui-run", "authorization_id": "base-semantic-runtime", "authorization_token_sha256": "5" * 64}, "budget": {"actions": 11, "max_actions": 11, "requests": 11, "max_requests": 11}, "observations": observations, "cleanup": {"owned_namespace_sha256": "6" * 64, "preexisting_absent": True, "delete_exact_owned_only": True, "postcondition_absent": True, "foreign_resources_mutated": False}, "canonical_state_advanced": False}


def test_ui_receipt_strict_order_and_nonpromotion():
    result = executor.validate_receipt(ui_receipt())
    assert result["status"] == "candidate_receipt_valid_non_promoting"
    receipt = ui_receipt(); receipt["observations"][1], receipt["observations"][2] = receipt["observations"][2], receipt["observations"][1]
    with pytest.raises(executor.ExecutorError, match="invalid_receipt"): executor.validate_receipt(receipt)
    receipt = ui_receipt(); receipt["promotion_eligible"] = True
    with pytest.raises(executor.ExecutorError, match="invalid_receipt"): executor.validate_receipt(receipt)
    receipt = ui_receipt(); receipt["observations"][0]["result_code"] = "invented_verified"
    with pytest.raises(executor.ExecutorError, match="invalid_receipt"): executor.validate_receipt(receipt)


def test_transport_rejects_oversized_declared_response():
    manifest = tiny()
    class Oversized(Opener):
        def open(self, request, timeout):
            response = super().open(request, timeout)
            response.headers["Content-Length"] = str(1048577)
            return response
    with pytest.raises(executor.ExecutorError, match="transport_error"): run(manifest, Oversized(manifest))


def test_extra_fields_rejected():
    manifest = tiny(); manifest["execute_shell"] = True
    with pytest.raises(executor.ExecutorError, match="invalid_manifest"): run(manifest)
    receipt = ui_receipt(); receipt["raw_response"] = "secret"
    with pytest.raises(executor.ExecutorError, match="invalid_receipt"): executor.validate_receipt(receipt)
