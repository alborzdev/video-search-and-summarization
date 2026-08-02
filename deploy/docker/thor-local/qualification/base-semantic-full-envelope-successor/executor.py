#!/usr/bin/env python3
"""Execute complete Base/HITL semantic envelopes with exact report cleanup."""

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
CONTRACT = HERE / "contract.json"
CONTRACT_SCHEMA = HERE / "contract.schema.json"
MANIFEST_SCHEMA = HERE / "request-manifest.schema.json"
RECEIPT_SCHEMA = HERE / "receipt.schema.json"
PLAIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
INTERACTION = re.compile(
    r"/executions/[A-Za-z0-9_.-]{1,128}/interactions/"
    r"[A-Za-z0-9_.-]{1,128}/response\Z"
)


class EnvelopeError(RuntimeError):
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


def _load(name: str, relative: str):
    path = HERE.parent / relative / "executor.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise EnvelopeError("configuration_error")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


base = _load("base_full_envelope_predecessor", "base-semantic-runtime-evidence")
exact = _load(
    "base_full_envelope_exact_cleanup",
    "base-semantic-exact-cleanup-successor",
)
common = base.common


def _raw(path: Path) -> bytes:
    try:
        return base._read(path)
    except base.ExecutorError as exc:
        raise EnvelopeError("configuration_error") from exc


def _json(path: Path, code: str = "configuration_error") -> dict[str, Any]:
    try:
        return base._json(path, code)
    except base.ExecutorError as exc:
        raise EnvelopeError(code) from exc


def _repo_path(relative: str) -> Path:
    try:
        return base._path(relative)
    except base.ExecutorError as exc:
        raise EnvelopeError("configuration_error") from exc


def _validate(value: Any, schema_path: Path, code: str) -> None:
    try:
        schema = _json(schema_path)
        Draft202012Validator.check_schema(schema)
        if list(Draft202012Validator(schema).iter_errors(value)):
            raise EnvelopeError(code)
    except EnvelopeError:
        raise
    except Exception as exc:
        raise EnvelopeError("configuration_error") from exc


def _contract() -> dict[str, Any]:
    value = _json(CONTRACT)
    _validate(value, CONTRACT_SCHEMA, "configuration_error")
    expected_predecessors = [
        "deploy/docker/thor-local/qualification/base-semantic-runtime-evidence",
        "deploy/docker/thor-local/qualification/base-semantic-exact-cleanup-successor",
    ]
    expected_source_paths = {
        "deploy/docker/thor-local/qualification/live-metadata-500-migration/post-state-capability-oracles.json",
        "deploy/docker/thor-local/qualification/base-semantic-runtime-evidence/contract.json",
        "deploy/docker/thor-local/qualification/base-semantic-runtime-evidence/executor.py",
        "deploy/docker/thor-local/qualification/base-semantic-exact-cleanup-successor/contract.json",
        "deploy/docker/thor-local/qualification/base-semantic-exact-cleanup-successor/executor.py",
        "deploy/docker/thor-local/qualification/expected/agent.json",
        "services/agent/src/vss_agents/tools/filesystem_object_store.py",
        "services/agent/src/vss_agents/tools/report_gen.py",
        "services/agent/src/vss_agents/tools/video_report_gen.py",
        "services/agent/src/vss_agents/tools/template_report_gen.py",
        "services/agent/src/vss_agents/agents/report_agent.py",
    }
    expected_ownership = {
        "registration_gate": (
            "one exact same-stem Markdown/PDF pair parsed only from the case's "
            "source-locked report step response"
        ),
        "delete_only_report_step_response_derived_exact_keys": True,
        "namespace_delete_attempted": False,
        "recursive_delete_claimed": False,
        "cleanup_order": ("markdown_then_pdf_then_individual_404_postconditions"),
        "preexisting_absence_proven": False,
        "foreign_resource_policy": "never mutate",
    }
    source_paths = [row["path"] for row in value["source_locks"]]
    if (
        value["predecessors"] != expected_predecessors
        or [row["case_id"] for row in value["cases"]]
        != ["tiny-agent-media", "hitl-state-transcript"]
        or [row["report_step_id"] for row in value["cases"]]
        != ["generate-report", "restart-and-check-persistence"]
        or len(source_paths) != len(expected_source_paths)
        or set(source_paths) != expected_source_paths
        or value["ownership"] != expected_ownership
    ):
        raise EnvelopeError("configuration_error")
    return value


def _one(rows: list[dict[str, Any]], key: str, value: str) -> dict[str, Any]:
    found = [row for row in rows if isinstance(row, dict) and row.get(key) == value]
    if len(found) != 1:
        raise EnvelopeError("configuration_error")
    return found[0]


def compile_plan() -> dict[str, Any]:
    contract = _contract()
    for lock in contract["source_locks"]:
        if hashlib.sha256(_raw(_repo_path(lock["path"]))).hexdigest() != lock["sha256"]:
            raise EnvelopeError("configuration_error")

    selected = _json(
        _repo_path(
            "deploy/docker/thor-local/qualification/live-metadata-500-migration/"
            "post-state-capability-oracles.json"
        )
    )
    if selected.get("schema_version") != 2 or len(selected.get("oracles", [])) != 500:
        raise EnvelopeError("configuration_error")
    selected_rows = {
        row.get("capability_id"): row
        for row in selected["oracles"]
        if isinstance(row, dict)
    }

    predecessor = base._contract()
    predecessor_cases = {
        row["planning_requirement_id"]: row
        for row in predecessor["cases"]
        if row["adapter"] == "bounded-http"
    }
    cleanup_contract = exact._contract()
    required_bounds = cleanup_contract["full_workflow_envelope_analysis"][
        "required_exact_cleanup_success"
    ]
    removable = {
        "capture-pre-state",
        "render-markdown",
        "render-pdf",
        "restore-owned-state",
        "verify-postconditions",
    }

    expected_ops = {
        (row.get("method"), row.get("path"))
        for row in _json(
            _repo_path("deploy/docker/thor-local/qualification/expected/agent.json")
        )["operations"]
        if isinstance(row, dict)
    }
    required_ops = {
        ("POST", "/chat/stream"),
        ("POST", "/generate/stream"),
        (
            "POST",
            "/executions/{execution_id}/interactions/{interaction_id}/response",
        ),
        ("GET", "/static/{file_path:path}"),
        ("DELETE", "/static/{file_path:path}"),
    }
    if not required_ops.issubset(expected_ops):
        raise EnvelopeError("configuration_error")

    store = _raw(
        _repo_path("services/agent/src/vss_agents/tools/filesystem_object_store.py")
    ).decode()
    report_agent = _raw(
        _repo_path("services/agent/src/vss_agents/agents/report_agent.py")
    ).decode()
    if (
        "if not await asyncio.to_thread(path.is_file)" not in store
        or "await asyncio.to_thread(path.unlink)" not in store
        or "[Markdown Report]" not in report_agent
        or "[PDF Report]" not in report_agent
    ):
        raise EnvelopeError("configuration_error")
    for relative in (
        "services/agent/src/vss_agents/tools/report_gen.py",
        "services/agent/src/vss_agents/tools/video_report_gen.py",
        "services/agent/src/vss_agents/tools/template_report_gen.py",
    ):
        source = _raw(_repo_path(relative)).decode()
        if "agent_report_" not in source and "vss_report_" not in source:
            raise EnvelopeError("configuration_error")

    compiled_cases = []
    for case in contract["cases"]:
        case_id = case["case_id"]
        prior = predecessor_cases[case_id]
        prior_ids = [
            row["id"] for row in prior["workflow"] if row["id"] not in removable
        ]
        successor_ids = [row["id"] for row in case["semantic_steps"]]
        report_steps = [
            row for row in case["semantic_steps"] if row["id"] == case["report_step_id"]
        ]
        row = selected_rows.get(case["capability_id"])
        bounds = row.get("execution_bounds", {}) if isinstance(row, dict) else {}
        cleanup = row.get("cleanup", {}) if isinstance(row, dict) else {}
        if (
            prior_ids != successor_ids
            or len(report_steps) != 1
            or report_steps[0]["path"] != "/generate/stream"
            or prior["capability_id"] != case["capability_id"]
            or prior["oracle_id"] != case["oracle_id"]
            or prior["max_requests"] != case["canonical_predecessor_max_requests"]
            or required_bounds.get(case_id) != case["max_requests"]
            or case["max_requests"] != case["max_actions"]
            or case["max_requests"] != len(successor_ids) + 6
            or not isinstance(row, dict)
            or row.get("current_state") != "open_unexecuted"
            or row.get("evidence") != []
            or row.get("acceptance_readiness", {}).get("classification")
            != "planning_index_only"
            or bounds.get("executor") is not None
            or bounds.get("max_requests") != case["canonical_predecessor_max_requests"]
            or bounds.get("max_actions") != case["canonical_predecessor_max_requests"]
            or cleanup.get("executor") is not None
        ):
            raise EnvelopeError("configuration_error")
        compiled_cases.append(
            {
                "case_id": case_id,
                "capability_id": case["capability_id"],
                "oracle_id": case["oracle_id"],
                "semantic_steps": successor_ids,
                "report_step_id": case["report_step_id"],
                "artifact_steps": contract["artifact_workflow"],
                "max_requests": case["max_requests"],
                "max_actions": case["max_actions"],
            }
        )

    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "mode": "inert-plan",
        "status": "pass",
        "runtime_actions": 0,
        "default_execution_enabled": False,
        "concrete_http_executor_ready": True,
        "full_envelope_integrated": True,
        "cleanup_semantics": "source_locked_report_step_exact_object_keys",
        "canonical_binding": False,
        "promotion_eligible": False,
        "warehouse_sample_bundle": "excluded",
        "contract_sha256": hashlib.sha256(_raw(CONTRACT)).hexdigest(),
        "cases": compiled_cases,
    }


def _normalize_report_origin(value: str) -> tuple[str, str]:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise EnvelopeError("invalid_manifest") from exc
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
        raise EnvelopeError("invalid_manifest")
    return parsed.scheme, parsed.netloc.lower()


def _path_matches(template: str, path: str) -> bool:
    if template.startswith("/executions/"):
        return INTERACTION.fullmatch(path) is not None
    return path == template


def _manifest(
    value: dict[str, Any], case: dict[str, Any], run_id: str
) -> set[tuple[str, str]]:
    _validate(value, MANIFEST_SCHEMA, "invalid_manifest")
    if (
        value["run_id"] != run_id
        or not PLAIN.fullmatch(run_id)
        or value["case_id"] != case["case_id"]
        or len(value["operations"]) != len(case["semantic_steps"])
    ):
        raise EnvelopeError("invalid_manifest")
    for operation, expected in zip(
        value["operations"], case["semantic_steps"], strict=True
    ):
        oracle = operation["oracle"]
        try:
            body = common.canonical_bytes(operation["body"])
        except common.EvidenceCommonError as exc:
            raise EnvelopeError("invalid_manifest") from exc
        if (
            operation["step_id"] != expected["id"]
            or operation["method"] != expected["method"]
            or not _path_matches(expected["path"], operation["path"])
            or operation["headers"].get("Conversation-Id") != run_id
            or run_id.encode() not in body
            or any(300 <= status <= 399 for status in oracle["allowed_statuses"])
            or set(oracle["required_literals"]) & set(oracle["forbidden_literals"])
            or (
                oracle["response_mode"] == "empty"
                and (oracle["require_nonempty"] or oracle["required_literals"])
            )
        ):
            raise EnvelopeError("invalid_manifest")
        if operation["step_id"] == case["report_step_id"] and (
            oracle["response_mode"] != "sse"
            or oracle["require_nonempty"] is not True
            or not {"Markdown Report", "PDF Report"}.issubset(
                oracle["required_literals"]
            )
        ):
            raise EnvelopeError("invalid_manifest")
    normalized = [
        _normalize_report_origin(item) for item in value["reported_static_origins"]
    ]
    if len(set(normalized)) != len(normalized):
        raise EnvelopeError("invalid_manifest")
    return set(normalized)


def _candidate_pair(
    raw: bytes, allowed_origins: set[tuple[str, str]]
) -> tuple[str, str] | None:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EnvelopeError("oracle_failed") from exc
    candidates: set[str] = set()
    absolute_spans: list[tuple[int, int]] = []
    for match in exact.ABSOLUTE_URL.finditer(text):
        parsed = urlsplit(match.group(0).rstrip(".,;:"))
        if (
            parsed.query
            or parsed.fragment
            or (parsed.scheme, parsed.netloc.lower()) not in allowed_origins
            or not parsed.path.startswith("/static/")
        ):
            continue
        key = parsed.path.removeprefix("/static/")
        if "%" not in key and "\\" not in key and exact.KEY.fullmatch(key):
            candidates.add("/static/" + key)
            absolute_spans.append(match.span())
    for match in exact.RELATIVE_URL.finditer(text):
        if any(start <= match.start() < end for start, end in absolute_spans):
            continue
        path = match.group(1).rstrip(".,;:")
        if exact.KEY.fullmatch(path.removeprefix("/static/")):
            candidates.add(path)
    if not candidates:
        return None
    try:
        return exact.extract_exact_report_pair(raw, allowed_origins)
    except exact.CleanupError as exc:
        raise EnvelopeError("oracle_failed") from exc


def _assert_semantic(result: Any, oracle: dict[str, Any]) -> str:
    try:
        return base._assert(result, oracle)
    except base.ExecutorError as exc:
        raise EnvelopeError(exc.code) from exc


def _observation(
    sequence: int,
    step_id: str,
    result: Any,
    oracle_sha256: str,
    report_pair_observed: bool = False,
) -> dict[str, Any]:
    return {
        "sequence": sequence,
        "step_id": step_id,
        "status": "pass",
        "result_code": step_id.replace("-", "_") + "_verified",
        "response_status": result.status,
        "response_bytes": len(result.body),
        "response_sha256": hashlib.sha256(result.body).hexdigest(),
        "oracle_sha256": oracle_sha256,
        "report_pair_observed": report_pair_observed,
    }


def _artifact_oracle(method: str, extension: str, status: str) -> dict[str, Any]:
    return {"method": method, "extension": extension, "expected_status": status}


def _request_artifact(transport: Any, budget: Any, method: str, path: str) -> Any:
    try:
        result = transport.request(
            {"method": method, "path": path, "body": None, "headers": {}}
        )
        budget.consume_action()
        return result
    except (base.ExecutorError, common.EvidenceCommonError) as exc:
        raise EnvelopeError("transport_error") from exc


def execute_http(
    *,
    manifest: dict[str, Any],
    run_id: str,
    acknowledgement: str,
    origin: str,
    opener_factory: Callable[[], Any] = base.LiveOpener,
) -> dict[str, Any]:
    plan, contract = compile_plan(), _contract()
    matching_cases = [
        row
        for row in contract["cases"]
        if row.get("case_id") == manifest.get("case_id")
    ]
    if len(matching_cases) != 1:
        raise EnvelopeError("invalid_manifest")
    case = matching_cases[0]
    allowed_origins = _manifest(manifest, case, run_id)
    if acknowledgement != contract["authorization"]["acknowledgement"]:
        raise EnvelopeError("authorization_required")
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
        semantic_paths = list(
            dict.fromkeys(row["path"] for row in manifest["operations"])
        )
        semantic_target = common.LoopbackTarget.admit(origin, semantic_paths)
    except common.EvidenceCommonError as exc:
        raise EnvelopeError("authorization_required") from exc

    budget = common.ExecutionBudget(case["max_requests"], case["max_actions"])
    opener = opener_factory()
    try:
        semantic_transport = base.Transport(
            semantic_target, opener, budget, contract["transport"]
        )
    except base.ExecutorError as exc:
        raise EnvelopeError("configuration_error") from exc

    observations: list[dict[str, Any]] = []
    pair: tuple[str, str] | None = None
    primary: EnvelopeError | None = None
    artifact_transport = None
    rows: dict[str, dict[str, Any]] = {}

    try:
        for sequence, operation in enumerate(manifest["operations"], 1):
            try:
                result = semantic_transport.request(operation)
                budget.consume_action()
            except (base.ExecutorError, common.EvidenceCommonError) as exc:
                raise EnvelopeError("transport_error") from exc
            observed = (
                _candidate_pair(result.body, allowed_origins)
                if operation["step_id"] == case["report_step_id"]
                else None
            )
            if observed is not None:
                if pair is not None and pair != observed:
                    raise EnvelopeError("oracle_failed")
                pair = observed
            oracle_sha = _assert_semantic(result, operation["oracle"])
            observations.append(
                _observation(
                    sequence,
                    operation["step_id"],
                    result,
                    oracle_sha,
                    observed is not None,
                )
            )
        if pair is None:
            raise EnvelopeError("oracle_failed")
        try:
            artifact_target = common.LoopbackTarget.admit(origin, list(pair))
            artifact_transport = base.Transport(
                artifact_target, opener, budget, contract["transport"]
            )
        except (base.ExecutorError, common.EvidenceCommonError) as exc:
            raise EnvelopeError("transport_error") from exc
        for extension, path in zip(("md", "pdf"), pair, strict=True):
            result = _request_artifact(artifact_transport, budget, "GET", path)
            if not 200 <= result.status <= 299 or not result.body:
                raise EnvelopeError("oracle_failed")
            if extension == "md":
                try:
                    result.body.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise EnvelopeError("oracle_failed") from exc
                if result.media_type not in {"text/markdown", "text/plain"}:
                    raise EnvelopeError("oracle_failed")
            elif result.media_type != "application/pdf" or not result.body.startswith(
                b"%PDF-"
            ):
                raise EnvelopeError("oracle_failed")
            step_id = "render-" + ("markdown" if extension == "md" else "pdf")
            oracle = _artifact_oracle("GET", extension, "2xx_valid_format")
            observations.append(
                _observation(
                    len(observations) + 1,
                    step_id,
                    result,
                    hashlib.sha256(common.canonical_bytes(oracle)).hexdigest(),
                )
            )
            rows[path] = {
                "extension": extension,
                "path_sha256": hashlib.sha256(path.encode()).hexdigest(),
                "stem_sha256": hashlib.sha256(
                    path.rsplit(".", 1)[0].encode()
                ).hexdigest(),
                "read_status": result.status,
                "read_bytes": len(result.body),
                "read_sha256": hashlib.sha256(result.body).hexdigest(),
            }
    except EnvelopeError as exc:
        primary = exc
    finally:
        if pair is not None:
            if artifact_transport is None:
                try:
                    artifact_target = common.LoopbackTarget.admit(origin, list(pair))
                    artifact_transport = base.Transport(
                        artifact_target, opener, budget, contract["transport"]
                    )
                except (base.ExecutorError, common.EvidenceCommonError):
                    primary = EnvelopeError("cleanup_failed")
            if artifact_transport is not None:
                for extension, path in zip(("md", "pdf"), pair, strict=True):
                    try:
                        result = _request_artifact(
                            artifact_transport, budget, "DELETE", path
                        )
                        if path in rows:
                            rows[path]["delete_status"] = result.status
                        if result.status not in {200, 204}:
                            primary = EnvelopeError("cleanup_failed")
                        if primary is None:
                            step_id = "delete-" + (
                                "markdown" if extension == "md" else "pdf"
                            )
                            oracle = _artifact_oracle("DELETE", extension, "200_or_204")
                            observations.append(
                                _observation(
                                    len(observations) + 1,
                                    step_id,
                                    result,
                                    hashlib.sha256(
                                        common.canonical_bytes(oracle)
                                    ).hexdigest(),
                                )
                            )
                    except EnvelopeError:
                        primary = EnvelopeError("cleanup_failed")
                for extension, path in zip(("md", "pdf"), pair, strict=True):
                    try:
                        result = _request_artifact(
                            artifact_transport, budget, "GET", path
                        )
                        if path in rows:
                            rows[path]["post_status"] = result.status
                        if result.status != 404:
                            primary = EnvelopeError("cleanup_failed")
                        if primary is None:
                            step_id = "verify-" + (
                                "markdown-absent" if extension == "md" else "pdf-absent"
                            )
                            oracle = _artifact_oracle("GET", extension, "404")
                            observations.append(
                                _observation(
                                    len(observations) + 1,
                                    step_id,
                                    result,
                                    hashlib.sha256(
                                        common.canonical_bytes(oracle)
                                    ).hexdigest(),
                                )
                            )
                    except EnvelopeError:
                        primary = EnvelopeError("cleanup_failed")

    if primary is not None:
        raise primary
    expected_budget = {
        "actions": case["max_actions"],
        "max_actions": case["max_actions"],
        "requests": case["max_requests"],
        "max_requests": case["max_requests"],
    }
    if budget.evidence() != expected_budget or pair is None:
        raise EnvelopeError("oracle_failed")

    path_hashes = sorted(rows[path]["path_sha256"] for path in pair)
    stem = pair[0].rsplit(".", 1)[0]
    receipt = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "mode": "bounded-http-full-envelope-candidate",
        "status": "full_envelope_candidate_evidence_complete_non_promoting",
        "promotion_eligible": False,
        "canonical_state_advanced": False,
        "case_id": case["case_id"],
        "capability_id": case["capability_id"],
        "oracle_id": case["oracle_id"],
        "contract_sha256": plan["contract_sha256"],
        "manifest_sha256": hashlib.sha256(common.canonical_bytes(manifest)).hexdigest(),
        "target_origin_sha256": hashlib.sha256(
            semantic_target.origin.encode()
        ).hexdigest(),
        "identity": identity.evidence(),
        "budget": budget.evidence(),
        "observations": observations,
        "artifacts": [rows[path] for path in pair],
        "cleanup": {
            "semantics": "source_locked_report_step_exact_object_keys",
            "artifact_count": 2,
            "artifact_set_sha256": hashlib.sha256(
                common.canonical_bytes(path_hashes)
            ).hexdigest(),
            "pair_stem_sha256": hashlib.sha256(stem.encode()).hexdigest(),
            "all_paths_from_report_step_response": True,
            "delete_each_exact_key": True,
            "postcondition_each_404": True,
            "namespace_delete_attempted": False,
            "recursive_delete_claimed": False,
            "foreign_resources_mutated": False,
            "preexisting_absence_proven": False,
        },
    }
    validate_receipt(receipt)
    return receipt


def validate_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    _validate(receipt, RECEIPT_SCHEMA, "invalid_receipt")
    plan, contract = compile_plan(), _contract()
    case = _one(contract["cases"], "case_id", receipt["case_id"])
    expected_steps = [row["id"] for row in case["semantic_steps"]] + contract[
        "artifact_workflow"
    ]
    expected_budget = {
        "actions": case["max_actions"],
        "max_actions": case["max_actions"],
        "requests": case["max_requests"],
        "max_requests": case["max_requests"],
    }
    observations = receipt["observations"]
    artifacts = receipt["artifacts"]
    path_hashes = sorted(row["path_sha256"] for row in artifacts)
    if (
        receipt["contract_sha256"] != plan["contract_sha256"]
        or receipt["capability_id"] != case["capability_id"]
        or receipt["oracle_id"] != case["oracle_id"]
        or receipt["budget"] != expected_budget
        or [row["sequence"] for row in observations]
        != list(range(1, case["max_actions"] + 1))
        or [row["step_id"] for row in observations] != expected_steps
        or any(
            row["result_code"] != step.replace("-", "_") + "_verified"
            for row, step in zip(observations, expected_steps, strict=True)
        )
        or [
            row["step_id"]
            for row in observations[: len(case["semantic_steps"])]
            if row["report_pair_observed"]
        ]
        != [case["report_step_id"]]
        or any(
            row["report_pair_observed"]
            for row in observations[len(case["semantic_steps"]) :]
        )
        or [row["extension"] for row in artifacts] != ["md", "pdf"]
        or len(set(path_hashes)) != 2
        or receipt["cleanup"]["artifact_set_sha256"]
        != hashlib.sha256(common.canonical_bytes(path_hashes)).hexdigest()
        or {row["stem_sha256"] for row in artifacts}
        != {receipt["cleanup"]["pair_stem_sha256"]}
    ):
        raise EnvelopeError("invalid_receipt")
    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
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
    except EnvelopeError as exc:
        print(json.dumps({"status": "error", "code": exc.code}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
