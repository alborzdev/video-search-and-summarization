#!/usr/bin/env python3
"""Bounded localhost Base/HITL executor and UI receipt validator."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Callable, Sequence
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from jsonschema import Draft202012Validator

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4].resolve(strict=True)
CONTRACT = HERE / "contract.json"
CONTRACT_SCHEMA = HERE / "contract.schema.json"
MANIFEST_SCHEMA = HERE / "request-manifest.schema.json"
RECEIPT_SCHEMA = HERE / "receipt.schema.json"
MAX_BYTES = 32 * 1024 * 1024
PLAIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
INTERACTION = re.compile(r"/executions/[A-Za-z0-9_.-]{1,128}/interactions/[A-Za-z0-9_.-]{1,128}/response\Z")


class ExecutorError(RuntimeError):
    CODES = {"authorization_required", "cleanup_failed", "configuration_error", "invalid_manifest", "invalid_receipt", "oracle_failed", "transport_error"}
    def __init__(self, code: str):
        self.code = code if code in self.CODES else "configuration_error"
        super().__init__(self.code)


def _common():
    path = HERE.parent / "runtime-evidence-common" / "common.py"
    spec = importlib.util.spec_from_file_location("base_semantic_common", path)
    if spec is None or spec.loader is None:
        raise ExecutorError("configuration_error")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


common = _common()


def _read(path: Path, maximum: int = MAX_BYTES) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ExecutorError("configuration_error") from exc
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum:
            raise ExecutorError("configuration_error")
        raw = os.read(fd, maximum + 1)
        after = os.fstat(fd)
        fields = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
        if len(raw) != before.st_size or any(getattr(before, f) != getattr(after, f) for f in fields):
            raise ExecutorError("configuration_error")
        return raw
    finally:
        os.close(fd)


def _decode(raw: bytes, code="configuration_error") -> dict[str, Any]:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ExecutorError(code)
            result[key] = value
        return result
    try:
        value = json.loads(raw.decode(), object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ExecutorError(code)))
    except ExecutorError:
        raise
    except Exception as exc:
        raise ExecutorError(code) from exc
    if not isinstance(value, dict):
        raise ExecutorError(code)
    return value


def _json(path: Path, code="configuration_error"):
    return _decode(_read(path), code)


def _validate(value, schema, code):
    try:
        Draft202012Validator.check_schema(schema)
        errors = list(Draft202012Validator(schema).iter_errors(value))
    except Exception as exc:
        raise ExecutorError("configuration_error") from exc
    if errors:
        raise ExecutorError(code)


def _path(relative: str) -> Path:
    item = Path(relative)
    if item.is_absolute() or not item.parts or ".." in item.parts:
        raise ExecutorError("configuration_error")
    current = ROOT
    for part in item.parts:
        current /= part
        if stat.S_ISLNK(current.lstat().st_mode):
            raise ExecutorError("configuration_error")
    current.resolve(strict=True).relative_to(ROOT)
    return current


def _contract():
    value = _json(CONTRACT)
    _validate(value, _json(CONTRACT_SCHEMA), "configuration_error")
    return value


def _one(rows, key, value):
    found = [row for row in rows if isinstance(row, dict) and row.get(key) == value]
    if len(found) != 1:
        raise ExecutorError("configuration_error")
    return found[0]


def compile_plan():
    contract = _contract()
    for lock in contract["source_locks"]:
        if hashlib.sha256(_read(_path(lock["path"]))).hexdigest() != lock["sha256"]:
            raise ExecutorError("configuration_error")
    oracles = _json(_path("deploy/docker/thor-local/parity/capability-oracles.json"))["oracles"]
    bounds = _json(_path("deploy/docker/thor-local/qualification/runtime-execution-bounds-audit/verified-integrations.json"))["cases"]
    operations = {(row.get("method"), row.get("path")) for row in _json(_path("deploy/docker/thor-local/qualification/expected/agent.json"))["operations"]}
    if not {("POST", "/chat/stream"), ("POST", "/generate/stream"), ("POST", "/executions/{execution_id}/interactions/{interaction_id}/response"), ("GET", "/static/{file_path:path}"), ("DELETE", "/static/{file_path:path}")}.issubset(operations):
        raise ExecutorError("configuration_error")
    result = []
    audit_cases = {row["planning_requirement_id"]: row for row in _json(_path("deploy/docker/thor-local/qualification/runtime-execution-bounds-audit/contract.json"))["cases"]}
    for case in contract["cases"]:
        oracle = _one(oracles, "oracle_id", case["oracle_id"])
        bound = _one(bounds, "planning_requirement_id", case["planning_requirement_id"])
        if oracle.get("current_state") != "open_unexecuted" or oracle.get("evidence") != [] or oracle.get("capability_id") != case["capability_id"]:
            raise ExecutorError("configuration_error")
        if (bound.get("integrated_max_requests"), bound.get("integrated_max_actions"), bound.get("integration_verified")) != (case["max_requests"], case["max_actions"], True):
            raise ExecutorError("configuration_error")
        audit = audit_cases[case["planning_requirement_id"]]
        expected_workflow = ["capture-pre-state"] + [row["id"] for row in audit["positive_steps"]] + [audit["adjacent_negative"]["id"], "restore-owned-state", "verify-postconditions"]
        if [row["id"] for row in case["workflow"]] != expected_workflow:
            raise ExecutorError("configuration_error")
        result.append({key: case[key] for key in ("planning_requirement_id", "capability_id", "oracle_id", "adapter", "max_requests", "max_actions")} | {"workflow": [x["id"] for x in case["workflow"]]})
    return {"schema_version": 1, "package_id": contract["package_id"], "mode": "inert-plan", "status": "pass", "runtime_actions": 0, "default_execution_enabled": False, "warehouse_sample_bundle": "excluded", "contract_sha256": hashlib.sha256(_read(CONTRACT)).hexdigest(), "cases": result, "promotion_eligible": False}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class LiveOpener:
    proxies_enabled = False
    redirects_enabled = False
    def __init__(self):
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())
    def open(self, request, timeout):
        try:
            return self._opener.open(request, timeout=timeout)
        except HTTPError as response:
            return response


class Transport:
    def __init__(self, target, opener, budget, bounds):
        if common.LoopbackTarget.admit(target.origin, target.allowed_paths) != target or getattr(opener, "proxies_enabled", None) is not False or getattr(opener, "redirects_enabled", None) is not False:
            raise ExecutorError("configuration_error")
        self.target, self.opener, self.budget, self.bounds = target, opener, budget, bounds
    def request(self, operation):
        path = self.target.admit_path(operation["path"])
        body = b"" if operation["body"] is None else common.canonical_bytes(operation["body"])
        if len(body) > self.bounds["max_request_bytes"]:
            raise ExecutorError("transport_error")
        self.budget.consume_request()
        url = self.target.origin + path
        headers = {"Accept": "application/json, text/event-stream, application/octet-stream", "Content-Length": str(len(body))}
        if body:
            headers["Content-Type"] = "application/json"
        headers.update(operation["headers"])
        response = None
        try:
            response = self.opener.open(Request(url, data=body or None, headers=headers, method=operation["method"]), self.bounds["timeout_seconds"])
            status = response.status
            declared = response.headers.get("Content-Length")
            if not isinstance(status, int) or not 100 <= status <= 599 or response.geturl() != url or 300 <= status <= 399:
                raise ExecutorError("transport_error")
            if declared is not None and (not declared.isascii() or not declared.isdecimal() or int(declared) > self.bounds["max_response_bytes"]):
                raise ExecutorError("transport_error")
            raw = response.read(self.bounds["max_response_bytes"] + 1)
            if not isinstance(raw, bytes) or len(raw) > self.bounds["max_response_bytes"]:
                raise ExecutorError("transport_error")
            return common.HTTPResult(status, response.headers.get("Content-Type", "").split(";", 1)[0].lower(), raw)
        except ExecutorError:
            raise
        except Exception as exc:
            raise ExecutorError("transport_error") from exc
        finally:
            if response is not None:
                response.close()


def _matches(template, path, owned):
    if template == "/static/{owned_path}":
        return path == owned or path.startswith(owned + "/")
    if template.startswith("/executions/"):
        return INTERACTION.fullmatch(path) is not None
    return path == template


def _manifest(manifest, case, run_id):
    _validate(manifest, _json(MANIFEST_SCHEMA), "invalid_manifest")
    required = {"schema_version", "case_id", "run_id", "owned_namespace_path", "operations"}
    if set(manifest) != required or manifest["schema_version"] != 1 or manifest["case_id"] != case["planning_requirement_id"] or manifest["run_id"] != run_id or not PLAIN.fullmatch(run_id):
        raise ExecutorError("invalid_manifest")
    owned, operations = manifest["owned_namespace_path"], manifest["operations"]
    if owned != f"/static/{run_id}" or not isinstance(operations, list) or len(operations) != len(case["workflow"]):
        raise ExecutorError("invalid_manifest")
    operation_keys = {"step_id", "method", "path", "body", "headers", "oracle"}
    oracle_keys = {"allowed_statuses", "response_mode", "require_nonempty", "required_literals", "forbidden_literals"}
    for op, step in zip(operations, case["workflow"], strict=True):
        if not isinstance(op, dict) or set(op) != operation_keys or op["step_id"] != step["id"] or op["method"] not in step["methods"] or not any(_matches(x, op["path"], owned) for x in step["paths"]):
            raise ExecutorError("invalid_manifest")
        if not isinstance(op["oracle"], dict) or set(op["oracle"]) != oracle_keys or op["oracle"]["response_mode"] not in {"json", "sse", "binary", "empty"}:
            raise ExecutorError("invalid_manifest")
        oracle = op["oracle"]
        if any(300 <= status <= 399 for status in oracle["allowed_statuses"]) or set(oracle["required_literals"]) & set(oracle["forbidden_literals"]):
            raise ExecutorError("invalid_manifest")
        if oracle["response_mode"] == "empty" and (oracle["require_nonempty"] or oracle["required_literals"]):
            raise ExecutorError("invalid_manifest")
        if op["method"] == "POST":
            if not isinstance(op["body"], dict) or op["headers"].get("Conversation-Id") != run_id or run_id.encode() not in common.canonical_bytes(op["body"]):
                raise ExecutorError("invalid_manifest")
        elif op["body"] is not None or op["headers"]:
            raise ExecutorError("invalid_manifest")
    if (operations[0]["path"], operations[0]["oracle"]["allowed_statuses"], operations[-2]["method"], operations[-2]["path"], operations[-1]["method"], operations[-1]["path"], operations[-1]["oracle"]["allowed_statuses"]) != (owned, [404], "DELETE", owned, "GET", owned, [404]):
        raise ExecutorError("invalid_manifest")
    if not set(operations[-2]["oracle"]["allowed_statuses"]).issubset({200, 204, 404}):
        raise ExecutorError("invalid_manifest")
    register = operations[4 if case["planning_requirement_id"] == "tiny-agent-media" else 6]
    if not register["path"].startswith(owned + "/") and owned not in register["oracle"]["required_literals"]:
        raise ExecutorError("invalid_manifest")


def _assert(result, oracle):
    if result.status not in oracle["allowed_statuses"] or (oracle["require_nonempty"] and not result.body) or (oracle["response_mode"] == "empty" and result.body):
        raise ExecutorError("oracle_failed")
    if oracle["response_mode"] in {"json", "sse"}:
        try:
            text = result.body.decode()
        except UnicodeDecodeError as exc:
            raise ExecutorError("oracle_failed") from exc
        if oracle["response_mode"] == "json" and result.body:
            _decode(result.body, "oracle_failed")
        if oracle["response_mode"] == "sse" and result.body and "data:" not in text:
            raise ExecutorError("oracle_failed")
        if any(x not in text for x in oracle["required_literals"]) or any(x in text for x in oracle["forbidden_literals"]):
            raise ExecutorError("oracle_failed")
    return hashlib.sha256(common.canonical_bytes(oracle)).hexdigest()


def _obs(sequence, operation, result, oracle_sha):
    return {"sequence": sequence, "step_id": operation["step_id"], "status": "pass", "result_code": operation["step_id"].replace("-", "_") + "_verified", "response_status": result.status, "response_bytes": len(result.body), "response_sha256": hashlib.sha256(result.body).hexdigest(), "oracle_sha256": oracle_sha}


def execute_http(*, manifest, run_id, acknowledgement, origin, opener_factory: Callable[[], Any] = LiveOpener):
    plan, contract = compile_plan(), _contract()
    case = _one(contract["cases"], "planning_requirement_id", manifest.get("case_id"))
    if case["adapter"] != "bounded-http":
        raise ExecutorError("invalid_manifest")
    _manifest(manifest, case, run_id)
    if acknowledgement != contract["authorization"]["acknowledgement"]:
        raise ExecutorError("authorization_required")
    try:
        guard = common.RunAuthorizationGuard.from_token(run_id=run_id, authorization_id=contract["authorization"]["authorization_id"], authorization_token=acknowledgement)
        identity = guard.admit(run_id=run_id, authorization_id=contract["authorization"]["authorization_id"], authorization_token=acknowledgement)
        paths = list(dict.fromkeys(op["path"] for op in manifest["operations"]))
        target = common.LoopbackTarget.admit(origin, paths)
    except common.EvidenceCommonError as exc:
        raise ExecutorError("authorization_required") from exc
    budget = common.ExecutionBudget(case["max_requests"], case["max_actions"])
    transport = Transport(target, opener_factory(), budget, contract["transport"])
    ledger = common.ResourceLedger(identity, budget, max_resources=1)
    observations, operations = [], manifest["operations"]
    cleanup_op, post_op = operations[-2:]
    def cleanup(exact):
        if exact != manifest["owned_namespace_path"]:
            raise ExecutorError("cleanup_failed")
        result = transport.request(cleanup_op)
        observations.append(_obs(len(operations) - 1, cleanup_op, result, _assert(result, cleanup_op["oracle"])))
    def postcondition(exact):
        if exact != manifest["owned_namespace_path"]:
            return False
        result = transport.request(post_op)
        observations.append(_obs(len(operations), post_op, result, _assert(result, post_op["oracle"])))
        return result.status == 404
    primary = None
    try:
        for sequence, operation in enumerate(operations[:-2], 1):
            result = transport.request(operation)
            budget.consume_action()
            observations.append(_obs(sequence, operation, result, _assert(result, operation["oracle"])))
            if sequence == (5 if case["planning_requirement_id"] == "tiny-agent-media" else 7):
                ledger.register(owner_run_id=run_id, resource_type="base-semantic-namespace", resource_id=manifest["owned_namespace_path"], cleanup=cleanup, postcondition=postcondition)
    except BaseException as exc:
        primary = exc
    finally:
        if ledger.active_count:
            try:
                if not ledger.cleanup():
                    primary = primary or ExecutorError("cleanup_failed")
            except BaseException as exc:
                primary = primary or exc
    if primary:
        if isinstance(primary, ExecutorError):
            raise primary
        raise ExecutorError("cleanup_failed" if isinstance(primary, common.EvidenceCommonError) else "oracle_failed") from primary
    observations.sort(key=lambda row: row["sequence"])
    if budget.requests != case["max_requests"] or budget.actions != case["max_actions"]:
        raise ExecutorError("oracle_failed")
    receipt = {"schema_version": 1, "package_id": contract["package_id"], "mode": "bounded-http-candidate", "status": "candidate_evidence_complete_non_promoting", "promotion_eligible": False, "planning_requirement_id": case["planning_requirement_id"], "capability_id": case["capability_id"], "oracle_id": case["oracle_id"], "contract_sha256": plan["contract_sha256"], "manifest_sha256": hashlib.sha256(common.canonical_bytes(manifest)).hexdigest(), "target_origin_sha256": hashlib.sha256(target.origin.encode()).hexdigest(), "identity": identity.evidence(), "budget": budget.evidence(), "observations": observations, "cleanup": {"owned_namespace_sha256": hashlib.sha256(manifest["owned_namespace_path"].encode()).hexdigest(), "preexisting_absent": observations[0]["response_status"] == 404, "delete_exact_owned_only": True, "postcondition_absent": observations[-1]["response_status"] == 404, "foreign_resources_mutated": False}, "canonical_state_advanced": False}
    validate_receipt(receipt)
    return receipt


def validate_receipt(receipt):
    _validate(receipt, _json(RECEIPT_SCHEMA), "invalid_receipt")
    required = {"schema_version", "package_id", "mode", "status", "promotion_eligible", "planning_requirement_id", "capability_id", "oracle_id", "contract_sha256", "manifest_sha256", "target_origin_sha256", "identity", "budget", "observations", "cleanup", "canonical_state_advanced"}
    if not isinstance(receipt, dict) or set(receipt) != required or receipt["schema_version"] != 1 or receipt["package_id"] != "base-semantic-runtime-evidence" or receipt["status"] != "candidate_evidence_complete_non_promoting" or receipt["promotion_eligible"] is not False or receipt["canonical_state_advanced"] is not False:
        raise ExecutorError("invalid_receipt")
    case = _one(_contract()["cases"], "planning_requirement_id", receipt["planning_requirement_id"])
    expected_budget = {"actions": case["max_actions"], "max_actions": case["max_actions"], "requests": case["max_requests"], "max_requests": case["max_requests"]}
    expected_mode = "manual-browser-candidate" if case["adapter"] == "manual-browser-receipt" else "bounded-http-candidate"
    if not PLAIN.fullmatch(receipt["identity"].get("run_id", "")) or receipt["contract_sha256"] != hashlib.sha256(_read(CONTRACT)).hexdigest() or receipt["capability_id"] != case["capability_id"] or receipt["oracle_id"] != case["oracle_id"] or receipt["budget"] != expected_budget or receipt["mode"] != expected_mode:
        raise ExecutorError("invalid_receipt")
    expected_steps = [x["id"] for x in case["workflow"]]
    if [x.get("sequence") for x in receipt["observations"]] != list(range(1, case["max_actions"] + 1)) or [x.get("step_id") for x in receipt["observations"]] != expected_steps:
        raise ExecutorError("invalid_receipt")
    if any(row.get("status") != "pass" or row.get("result_code") != step.replace("-", "_") + "_verified" for row, step in zip(receipt["observations"], expected_steps, strict=True)):
        raise ExecutorError("invalid_receipt")
    cleanup = receipt["cleanup"]
    if cleanup.get("preexisting_absent") is not True or cleanup.get("delete_exact_owned_only") is not True or cleanup.get("postcondition_absent") is not True or cleanup.get("foreign_resources_mutated") is not False:
        raise ExecutorError("invalid_receipt")
    return {"schema_version": 1, "package_id": "base-semantic-runtime-evidence", "status": "candidate_receipt_valid_non_promoting", "planning_requirement_id": case["planning_requirement_id"], "promotion_eligible": False, "canonical_state_advanced": False, "receipt_sha256": hashlib.sha256(common.canonical_bytes(receipt)).hexdigest()}


def main(argv: Sequence[str] | None = None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("plan")
    execute = sub.add_parser("execute-http")
    execute.add_argument("--manifest", type=Path, required=True); execute.add_argument("--run-id", required=True); execute.add_argument("--acknowledgement", required=True); execute.add_argument("--origin", default="http://127.0.0.1:8000")
    validate = sub.add_parser("validate-receipt"); validate.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = execute_http(manifest=_json(args.manifest, "invalid_manifest"), run_id=args.run_id, acknowledgement=args.acknowledgement, origin=args.origin) if args.command == "execute-http" else validate_receipt(_json(args.receipt, "invalid_receipt")) if args.command == "validate-receipt" else compile_plan()
        print(json.dumps(result, sort_keys=True, indent=2)); return 0
    except ExecutorError as exc:
        print(json.dumps({"status": "error", "code": exc.code}), file=sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
