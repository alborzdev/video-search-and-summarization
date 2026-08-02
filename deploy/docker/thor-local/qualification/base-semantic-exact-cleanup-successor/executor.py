#!/usr/bin/env python3
"""Exact per-report cleanup successor for the Thor-local Base agent."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from typing import Any, Callable, Sequence
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4].resolve(strict=True)
CONTRACT = HERE / "contract.json"
MANIFEST_SCHEMA = HERE / "request-manifest.schema.json"
RECEIPT_SCHEMA = HERE / "receipt.schema.json"
SHA = re.compile(r"[0-9a-f]{64}\Z")
PLAIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
KEY = re.compile(
    r"(?:[A-Za-z0-9][A-Za-z0-9_.-]{0,127}/)?"
    r"(?:(?:agent_report_[0-9]{8}_[0-9]{6})|"
    r"(?:vss_report_[A-Za-z0-9_.-]{1,192}_[0-9]{8}_[0-9]{6}))\.(?:md|pdf)\Z"
)
ABSOLUTE_URL = re.compile(r"https?://[^\s<>\"'()\[\]{}]+")
RELATIVE_URL = re.compile(r"(?<![A-Za-z0-9])(/static/[A-Za-z0-9_.~/-]+)")


class CleanupError(RuntimeError):
    CODES = {
        "authorization_required",
        "cleanup_failed",
        "configuration_error",
        "invalid_manifest",
        "invalid_receipt",
        "oracle_failed",
        "transport_error",
    }

    def __init__(self, code: str):
        self.code = code if code in self.CODES else "configuration_error"
        super().__init__(self.code)


def _load_predecessor():
    path = HERE.parent / "base-semantic-runtime-evidence" / "executor.py"
    spec = importlib.util.spec_from_file_location(
        "base_semantic_frozen_predecessor", path
    )
    if spec is None or spec.loader is None:
        raise CleanupError("configuration_error")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


base = _load_predecessor()
common = base.common


def _raw(path: Path) -> bytes:
    try:
        return base._read(path)
    except base.ExecutorError as exc:
        raise CleanupError("configuration_error") from exc


def _json(path: Path, code: str = "configuration_error") -> dict[str, Any]:
    try:
        return base._json(path, code)
    except base.ExecutorError as exc:
        raise CleanupError(code) from exc


def _validate(value: Any, schema_path: Path, code: str) -> None:
    try:
        schema = _json(schema_path)
        Draft202012Validator.check_schema(schema)
        if list(Draft202012Validator(schema).iter_errors(value)):
            raise CleanupError(code)
    except CleanupError:
        raise
    except Exception as exc:
        raise CleanupError("configuration_error") from exc


def _repo_path(relative: str) -> Path:
    try:
        return base._path(relative)
    except base.ExecutorError as exc:
        raise CleanupError("configuration_error") from exc


def _contract() -> dict[str, Any]:
    value = _json(CONTRACT)
    required = {
        "schema_version",
        "package_id",
        "mode",
        "predecessor",
        "authorization",
        "transport",
        "generation",
        "cleanup",
        "source_locks",
        "full_workflow_envelope_analysis",
        "warehouse_sample_bundle",
        "promotion_eligible",
    }
    if set(value) != required or value["schema_version"] != 1:
        raise CleanupError("configuration_error")
    return value


def compile_plan() -> dict[str, Any]:
    contract = _contract()
    for lock in contract["source_locks"]:
        if set(lock) != {"path", "sha256"} or not SHA.fullmatch(lock["sha256"]):
            raise CleanupError("configuration_error")
        if hashlib.sha256(_raw(_repo_path(lock["path"]))).hexdigest() != lock["sha256"]:
            raise CleanupError("configuration_error")

    expected = _json(
        _repo_path("deploy/docker/thor-local/qualification/expected/agent.json")
    )
    static_ops = {
        (row.get("method"), row.get("path"))
        for row in expected.get("operations", [])
        if isinstance(row, dict)
    }
    if not {
        ("GET", "/static/{file_path:path}"),
        ("DELETE", "/static/{file_path:path}"),
        ("POST", "/generate/stream"),
    }.issubset(static_ops):
        raise CleanupError("configuration_error")

    selected = _json(
        _repo_path(
            "deploy/docker/thor-local/qualification/live-metadata-500-migration/"
            "post-state-capability-oracles.json"
        )
    )
    if selected.get("schema_version") != 2 or len(selected.get("oracles", [])) != 500:
        raise CleanupError("configuration_error")
    by_capability = {
        row.get("capability_id"): row
        for row in selected["oracles"]
        if isinstance(row, dict)
    }
    expected_rows = {
        "runtime.workflow.base-chat-report": 8,
        "runtime.agent.base-hitl": 11,
    }
    for capability_id, max_requests in expected_rows.items():
        row = by_capability.get(capability_id)
        if not isinstance(row, dict):
            raise CleanupError("configuration_error")
        bounds = row.get("execution_bounds", {})
        cleanup = row.get("cleanup", {})
        if (
            row.get("current_state") != "open_unexecuted"
            or row.get("evidence") != []
            or row.get("acceptance_readiness", {}).get("classification")
            != "planning_index_only"
            or bounds.get("executor") is not None
            or bounds.get("max_requests") != max_requests
            or bounds.get("max_actions") != max_requests
            or cleanup.get("executor") is not None
        ):
            raise CleanupError("configuration_error")

    store = _raw(
        _repo_path("services/agent/src/vss_agents/tools/filesystem_object_store.py")
    ).decode()
    if (
        "if not await asyncio.to_thread(path.is_file)" not in store
        or "await asyncio.to_thread(path.unlink)" not in store
    ):
        raise CleanupError("configuration_error")
    for relative in (
        "services/agent/src/vss_agents/tools/report_gen.py",
        "services/agent/src/vss_agents/tools/video_report_gen.py",
        "services/agent/src/vss_agents/tools/template_report_gen.py",
    ):
        source = _raw(_repo_path(relative)).decode()
        if "agent_report_" not in source and "vss_report_" not in source:
            raise CleanupError("configuration_error")

    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "mode": "inert-plan",
        "status": "pass",
        "runtime_actions": 0,
        "static_api_semantics": "exact_object_key",
        "namespace_delete_supported": False,
        "report_artifact_cardinality": 2,
        "exact_cleanup_request_count": 7,
        "frozen_base_envelopes": contract["full_workflow_envelope_analysis"]["frozen"],
        "required_exact_cleanup_success_envelopes": contract[
            "full_workflow_envelope_analysis"
        ]["required_exact_cleanup_success"],
        "canonical_envelope_binding": False,
        "canonical_metadata": "deploy/docker/thor-local/qualification/live-metadata-500-migration/post-state-capability-oracles.json",
        "promotion_eligible": False,
        "warehouse_sample_bundle": "excluded",
        "contract_sha256": hashlib.sha256(_raw(CONTRACT)).hexdigest(),
    }


def _normalize_report_origin(value: str) -> tuple[str, str]:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise CleanupError("invalid_manifest") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"/static", "/static/"}
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise CleanupError("invalid_manifest")
    return parsed.scheme, parsed.netloc.lower()


def _manifest(value: dict[str, Any], run_id: str) -> set[tuple[str, str]]:
    _validate(value, MANIFEST_SCHEMA, "invalid_manifest")
    if value["run_id"] != run_id or not PLAIN.fullmatch(run_id):
        raise CleanupError("invalid_manifest")
    operation = value["generation"]
    if operation["headers"].get("Conversation-Id") != run_id:
        raise CleanupError("invalid_manifest")
    try:
        body = common.canonical_bytes(operation["body"])
    except common.EvidenceCommonError as exc:
        raise CleanupError("invalid_manifest") from exc
    if run_id.encode() not in body:
        raise CleanupError("invalid_manifest")
    oracle = operation["oracle"]
    if set(oracle["required_literals"]) & set(oracle["forbidden_literals"]):
        raise CleanupError("invalid_manifest")
    return {_normalize_report_origin(item) for item in value["reported_static_origins"]}


def _assert_generation(result: Any, oracle: dict[str, Any]) -> None:
    if result.status not in oracle["allowed_statuses"] or not result.body:
        raise CleanupError("oracle_failed")
    try:
        text = result.body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CleanupError("oracle_failed") from exc
    if oracle["response_mode"] == "sse" and "data:" not in text:
        raise CleanupError("oracle_failed")
    if oracle["response_mode"] == "json":
        try:
            base._decode(result.body, "oracle_failed")
        except base.ExecutorError as exc:
            raise CleanupError("oracle_failed") from exc
    if any(item not in text for item in oracle["required_literals"]):
        raise CleanupError("oracle_failed")
    if any(item in text for item in oracle["forbidden_literals"]):
        raise CleanupError("oracle_failed")


def extract_exact_report_pair(
    raw: bytes, allowed_origins: set[tuple[str, str]]
) -> tuple[str, str]:
    """Extract one source-bound MD/PDF report pair; never infer a namespace."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CleanupError("oracle_failed") from exc
    paths: set[str] = set()
    absolute_spans: list[tuple[int, int]] = []
    for match in ABSOLUTE_URL.finditer(text):
        parsed = urlsplit(match.group(0).rstrip(".,;:"))
        if (
            parsed.query
            or parsed.fragment
            or (parsed.scheme, parsed.netloc.lower()) not in allowed_origins
        ):
            continue
        if not parsed.path.startswith("/static/"):
            continue
        key = parsed.path.removeprefix("/static/")
        if "%" in key or "\\" in key or not KEY.fullmatch(key):
            continue
        paths.add("/static/" + key)
        absolute_spans.append(match.span())
    for match in RELATIVE_URL.finditer(text):
        if any(start <= match.start() < end for start, end in absolute_spans):
            continue
        path = match.group(1).rstrip(".,;:")
        key = path.removeprefix("/static/")
        if KEY.fullmatch(key):
            paths.add(path)
    if len(paths) != 2:
        raise CleanupError("oracle_failed")
    ordered = sorted(paths, key=lambda item: (Path(item).suffix != ".md", item))
    if [Path(item).suffix for item in ordered] != [".md", ".pdf"]:
        raise CleanupError("oracle_failed")
    stems = [item.rsplit(".", 1)[0] for item in ordered]
    if stems[0] != stems[1]:
        raise CleanupError("oracle_failed")
    return ordered[0], ordered[1]


def _request(transport: Any, budget: Any, method: str, path: str) -> Any:
    operation = {"method": method, "path": path, "body": None, "headers": {}}
    try:
        result = transport.request(operation)
        budget.consume_action()
        return result
    except (base.ExecutorError, common.EvidenceCommonError) as exc:
        raise CleanupError("transport_error") from exc


def execute_http(
    *,
    manifest: dict[str, Any],
    run_id: str,
    acknowledgement: str,
    origin: str,
    opener_factory: Callable[[], Any] = base.LiveOpener,
) -> dict[str, Any]:
    plan, contract = compile_plan(), _contract()
    allowed_origins = _manifest(manifest, run_id)
    if acknowledgement != contract["authorization"]["acknowledgement"]:
        raise CleanupError("authorization_required")
    try:
        guard = common.RunAuthorizationGuard.from_token(
            run_id=run_id,
            authorization_id=contract["authorization"]["authorization_id"],
            authorization_token=acknowledgement,
        )
        identity = guard.admit(
            run_id=run_id,
            authorization_id=contract["authorization"]["authorization_id"],
            authorization_token=acknowledgement,
        )
        generation_target = common.LoopbackTarget.admit(origin, ["/generate/stream"])
    except common.EvidenceCommonError as exc:
        raise CleanupError("authorization_required") from exc

    bounds = contract["transport"]
    budget = common.ExecutionBudget(bounds["max_requests"], bounds["max_actions"])
    opener = opener_factory()
    generation_error: CleanupError | None = None
    try:
        generation_transport = base.Transport(generation_target, opener, budget, bounds)
        generation = manifest["generation"]
        generation_result = generation_transport.request(generation)
        budget.consume_action()
        try:
            _assert_generation(generation_result, generation["oracle"])
        except CleanupError as exc:
            # A report-producing response can fail a semantic assertion after
            # committing artifacts.  Capture an exact pair first and clean it
            # before returning the primary failure.
            generation_error = exc
        paths = extract_exact_report_pair(generation_result.body, allowed_origins)
        artifact_target = common.LoopbackTarget.admit(origin, list(paths))
        artifact_transport = base.Transport(artifact_target, opener, budget, bounds)
    except CleanupError:
        raise
    except (base.ExecutorError, common.EvidenceCommonError) as exc:
        raise CleanupError("transport_error") from exc

    rows: dict[str, dict[str, Any]] = {
        path: {
            "extension": path.rsplit(".", 1)[1],
            "path_sha256": hashlib.sha256(path.encode()).hexdigest(),
            "stem_sha256": hashlib.sha256(path.rsplit(".", 1)[0].encode()).hexdigest(),
        }
        for path in paths
    }
    primary: CleanupError | None = generation_error
    try:
        for path in paths:
            result = _request(artifact_transport, budget, "GET", path)
            if not 200 <= result.status <= 299 or not result.body:
                raise CleanupError("oracle_failed")
            rows[path].update(
                read_status=result.status,
                read_bytes=len(result.body),
                read_sha256=hashlib.sha256(result.body).hexdigest(),
            )
    except CleanupError as exc:
        primary = exc
    finally:
        for path in paths:
            try:
                result = _request(artifact_transport, budget, "DELETE", path)
                rows[path]["delete_status"] = result.status
                if result.status not in {200, 204}:
                    primary = primary or CleanupError("cleanup_failed")
            except CleanupError:
                primary = primary or CleanupError("cleanup_failed")
        for path in paths:
            try:
                result = _request(artifact_transport, budget, "GET", path)
                rows[path]["post_status"] = result.status
                if result.status != 404:
                    primary = primary or CleanupError("cleanup_failed")
            except CleanupError:
                primary = primary or CleanupError("cleanup_failed")
    if primary is not None:
        raise primary
    if budget.evidence() != {
        "actions": 7,
        "max_actions": 7,
        "requests": 7,
        "max_requests": 7,
    }:
        raise CleanupError("oracle_failed")

    path_hashes = sorted(row["path_sha256"] for row in rows.values())
    stem = paths[0].rsplit(".", 1)[0]
    receipt = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "mode": "bounded-http-candidate",
        "status": "exact_report_cleanup_complete_non_promoting",
        "promotion_eligible": False,
        "contract_sha256": plan["contract_sha256"],
        "manifest_sha256": hashlib.sha256(common.canonical_bytes(manifest)).hexdigest(),
        "target_origin_sha256": hashlib.sha256(
            generation_target.origin.encode()
        ).hexdigest(),
        "generation_response_sha256": hashlib.sha256(
            generation_result.body
        ).hexdigest(),
        "identity": identity.evidence(),
        "budget": budget.evidence(),
        "artifacts": [rows[path] for path in paths],
        "cleanup": {
            "semantics": "exact_object_key",
            "artifact_count": 2,
            "artifact_set_sha256": hashlib.sha256(
                common.canonical_bytes(path_hashes)
            ).hexdigest(),
            "pair_stem_sha256": hashlib.sha256(stem.encode()).hexdigest(),
            "all_paths_from_generation_response": True,
            "delete_each_exact_key": True,
            "postcondition_each_404": True,
            "namespace_delete_attempted": False,
            "recursive_delete_claimed": False,
            "foreign_resources_mutated": False,
            "preexisting_absence_proven": False,
        },
        "canonical_state_advanced": False,
    }
    validate_receipt(receipt)
    return receipt


def validate_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    _validate(receipt, RECEIPT_SCHEMA, "invalid_receipt")
    plan = compile_plan()
    if receipt["contract_sha256"] != plan["contract_sha256"]:
        raise CleanupError("invalid_receipt")
    if receipt["identity"].get(
        "authorization_id"
    ) != "base-semantic-exact-cleanup" or not PLAIN.fullmatch(
        receipt["identity"].get("run_id", "")
    ):
        raise CleanupError("invalid_receipt")
    artifacts = receipt["artifacts"]
    if [row["extension"] for row in artifacts] != ["md", "pdf"]:
        raise CleanupError("invalid_receipt")
    path_hashes = sorted(row["path_sha256"] for row in artifacts)
    expected_set = hashlib.sha256(common.canonical_bytes(path_hashes)).hexdigest()
    if (
        len(set(path_hashes)) != 2
        or receipt["cleanup"]["artifact_set_sha256"] != expected_set
    ):
        raise CleanupError("invalid_receipt")
    stem_hashes = {row["stem_sha256"] for row in artifacts}
    if stem_hashes != {receipt["cleanup"]["pair_stem_sha256"]}:
        raise CleanupError("invalid_receipt")
    if any(
        row["post_status"] != 404 or row["delete_status"] not in {200, 204}
        for row in artifacts
    ):
        raise CleanupError("invalid_receipt")
    return {
        "schema_version": 1,
        "package_id": "base-semantic-exact-cleanup-successor",
        "status": "candidate_receipt_valid_non_promoting",
        "promotion_eligible": False,
        "canonical_state_advanced": False,
        "receipt_sha256": hashlib.sha256(common.canonical_bytes(receipt)).hexdigest(),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("plan")
    execute = sub.add_parser("execute-http")
    execute.add_argument("--manifest", type=Path, required=True)
    execute.add_argument("--run-id", required=True)
    execute.add_argument("--acknowledgement", required=True)
    execute.add_argument("--origin", default="http://127.0.0.1:8000")
    validate = sub.add_parser("validate-receipt")
    validate.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "execute-http":
            result = execute_http(
                manifest=_json(args.manifest, "invalid_manifest"),
                run_id=args.run_id,
                acknowledgement=args.acknowledgement,
                origin=args.origin,
            )
        elif args.command == "validate-receipt":
            result = validate_receipt(_json(args.receipt, "invalid_receipt"))
        else:
            result = compile_plan()
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0
    except CleanupError as exc:
        print(json.dumps({"status": "error", "code": exc.code}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
