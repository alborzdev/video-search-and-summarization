#!/usr/bin/env python3
"""Authorization-gated LVS semantic runtime executor.

The default command validates an inert plan. Runtime work is possible only via
``run_executor`` with an explicitly injected adapter and acknowledgement.
"""

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
from typing import Any, Mapping, Protocol

from jsonschema import Draft202012Validator

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4].resolve(strict=True)
CONTRACT_PATH = HERE / "contract.json"
RECEIPT_SCHEMA_PATH = HERE / "receipt.schema.json"
COMMON_PATH = HERE.parent / "runtime-evidence-common" / "common.py"
MAX_FILE_BYTES = 32 * 1024 * 1024
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
RESULT_CODE_RE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")


def _load_common() -> Any:
    spec = importlib.util.spec_from_file_location("lvs_semantic_runtime_common", COMMON_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("configuration_error")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


common = _load_common()


class ExecutorError(RuntimeError):
    """Stable public failure code; adapter details are never propagated."""

    CODES = {
        "authorization_required",
        "cleanup_failed",
        "configuration_error",
        "invalid_response",
        "oracle_failed",
    }

    def __init__(self, code: str) -> None:
        self.code = code if code in self.CODES else "configuration_error"
        super().__init__(self.code)


class SemanticAdapter(Protocol):
    """Operator-reviewed adapter for the already-deployed Thor LVS profile."""

    def invoke(self, *, run_id: str, action_id: str, request: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def cleanup_exact_owned(self, *, run_id: str, resource_id: str) -> Mapping[str, Any]: ...

    def verify_postcondition(self, *, run_id: str, resource_id: str) -> Mapping[str, Any]: ...


def _bounded_read(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ExecutorError("configuration_error") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= MAX_FILE_BYTES:
            raise ExecutorError("configuration_error")
        raw = bytearray()
        while len(raw) <= MAX_FILE_BYTES:
            chunk = os.read(descriptor, min(131072, MAX_FILE_BYTES + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
        after = os.fstat(descriptor)
        stable = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
        if len(raw) != before.st_size or any(getattr(before, key) != getattr(after, key) for key in stable):
            raise ExecutorError("configuration_error")
        return bytes(raw)
    finally:
        os.close(descriptor)


def _strict_json(raw: bytes) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ExecutorError("configuration_error")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda _token: (_ for _ in ()).throw(ExecutorError("configuration_error")),
        )
    except ExecutorError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExecutorError("configuration_error") from exc
    if not isinstance(value, dict):
        raise ExecutorError("configuration_error")
    return value


def _source_path(relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
        raise ExecutorError("configuration_error")
    current = REPO_ROOT
    for part in candidate.parts:
        current /= part
        try:
            if stat.S_ISLNK(current.lstat().st_mode):
                raise ExecutorError("configuration_error")
        except OSError as exc:
            raise ExecutorError("configuration_error") from exc
    return current


def _contract() -> dict[str, Any]:
    return _strict_json(_bounded_read(CONTRACT_PATH))


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(common.canonical_bytes(value)).hexdigest()


def _unique(items: list[dict[str, Any]], key: str, value: str) -> dict[str, Any]:
    matches = [item for item in items if isinstance(item, dict) and item.get(key) == value]
    if len(matches) != 1:
        raise ExecutorError("configuration_error")
    return matches[0]


def compile_plan() -> dict[str, Any]:
    """Validate exact source locks and the live 14-action oracle projection."""

    contract = _contract()
    if (
        contract.get("schema_version") != 1
        or contract.get("default_execution_enabled") is not False
        or contract.get("warehouse_sample_bundle") != "excluded"
        or len(contract.get("actions", [])) != 14
        or [item.get("order") for item in contract["actions"]] != list(range(1, 15))
        or contract.get("execution_bounds", {}).get("max_actions") != 14
        or contract.get("execution_bounds", {}).get("max_requests") != 14
    ):
        raise ExecutorError("configuration_error")
    paths: set[str] = set()
    for lock in contract.get("source_locks", []):
        if not isinstance(lock, dict) or set(lock) != {"path", "sha256"} or lock["path"] in paths:
            raise ExecutorError("configuration_error")
        paths.add(lock["path"])
        if hashlib.sha256(_bounded_read(_source_path(lock["path"]))).hexdigest() != lock["sha256"]:
            raise ExecutorError("configuration_error")

    lane_path = _source_path("deploy/docker/thor-local/qualification/runtime-lanes/runtime-lane-plan.json")
    lane = _strict_json(_bounded_read(lane_path))
    binding = _unique(lane.get("capability_bindings", []), "capability_id", contract["capability_id"])
    oracle_contract = binding["probe"]["fixture"]["input"]["contract"]
    bounds = binding["probe"]["execution_bounds"]
    if (
        binding.get("oracle_id") != contract["oracle_id"]
        or oracle_contract.get("tools") != contract["declared_tools"]
        or oracle_contract.get("uploaded_video_reports") != "one_or_multiple"
        or oracle_contract.get("latest_query_overwrites_shared_prompt") is not True
        or oracle_contract.get("cross_agent_prompt_visibility") is not False
        or bounds.get("max_actions") != 14
        or bounds.get("max_requests") != 14
        or bounds.get("workload", {}).get("phases") != contract["execution_bounds"]["phases"]
    ):
        raise ExecutorError("configuration_error")
    Draft202012Validator.check_schema(_strict_json(_bounded_read(RECEIPT_SCHEMA_PATH)))
    return {
        "package_id": contract["package_id"],
        "capability_id": contract["capability_id"],
        "oracle_id": contract["oracle_id"],
        "action_count": 14,
        "request_bound": 14,
        "tool_count": 5,
        "cleanup_proof_hooks": list(contract["cleanup_contract"]["required_cleanup_proof"]),
        "runtime_activity_performed": False,
        "runtime_evidence_created": False,
        "warehouse_sample_bundle": "excluded",
        "status": "inert_plan_valid",
    }


def _observation(adapter: SemanticAdapter, budget: Any, run_id: str, action_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
    budget.consume_request()
    try:
        result = adapter.invoke(run_id=run_id, action_id=action_id, request=request)
    except Exception as exc:
        raise ExecutorError("invalid_response") from exc
    if not isinstance(result, Mapping) or set(result) != {"status", "result_code", "facts"}:
        raise ExecutorError("invalid_response")
    result = dict(result)
    if (
        result["status"] not in {"pass", "fail"}
        or not isinstance(result["result_code"], str)
        or not RESULT_CODE_RE.fullmatch(result["result_code"])
    ):
        raise ExecutorError("invalid_response")
    if not isinstance(result["facts"], Mapping):
        raise ExecutorError("invalid_response")
    result["facts"] = dict(result["facts"])
    common.canonical_bytes(result)
    return result


def _true_fields(value: Mapping[str, Any], keys: list[str], *, exact: bool = False) -> bool:
    return (not exact or set(value) == set(keys)) and all(value.get(key) is True for key in keys)


def _semantic_pass(action_id: str, facts: Mapping[str, Any], *, contract: dict[str, Any], run_id: str, fixture_sha256: tuple[str, str]) -> bool:
    if action_id == "capture-pre-state":
        return (
            facts.get("owned_namespace_absent") is True
            and facts.get("artifact_identity_verified") is True
            and isinstance(facts.get("unrelated_state"), Mapping)
        )
    if action_id == "discover-five-tools":
        return facts == {"tools": contract["declared_tools"]}
    if action_id == "verify-local-dependencies":
        return _true_fields(
            facts,
            ["lvs_backend", "rtvi_vlm", "elasticsearch", "kafka", "logstash", "local_inference"],
        )
    if action_id == "setup-owned-fixtures":
        return (
            facts.get("owner_run_id") == run_id
            and isinstance(facts.get("resource_id"), str)
            and 1 <= len(facts["resource_id"]) <= 1024
            and facts.get("fixture_sha256") == list(fixture_sha256)
            and facts.get("warehouse_sample_bundle") is False
        )
    if action_id == "single-video-report":
        return _true_fields(facts, ["correlated", "nonempty_report"]) and facts.get("source_count") == 1
    if action_id == "multi-video-report":
        return _true_fields(facts, ["correlated", "nonempty_report", "distinct_sources"]) and facts.get("source_count") == 2
    if action_id == "start-live-caption":
        return _true_fields(facts, ["caption_started", "kafka_delivery", "logstash_delivery"], exact=True)
    if action_id == "retrieve-live-caption":
        return facts.get("correlated") is True and type(facts.get("caption_count")) is int and facts["caption_count"] > 0
    if action_id == "write-shared-prompt-first":
        return facts.get("writer_agent") == "agent-a" and facts.get("prompt_version") == 1 and facts.get("written") is True
    if action_id == "overwrite-shared-prompt-latest":
        return facts.get("prompt_version") == 2 and facts.get("previous_overwritten") is True and facts.get("latest_visible") is True
    if action_id == "reject-cross-agent-prompt-visibility":
        return facts == {"requesting_agent": "agent-b", "prompt_visible": False, "isolation_enforced": True}
    if action_id == "probe-disconnect-cancel-quiescence":
        return _true_fields(
            facts,
            ["disconnect_delivered_once", "exact_cancel_accepted", "quiescent", "sibling_unchanged", "ca_rag_cleanup_supported"],
        )
    return False


def run_executor(
    *,
    adapter: SemanticAdapter,
    run_id: str,
    acknowledgement: str,
    fixture_sha256: tuple[str, str],
) -> dict[str, Any]:
    """Run the exact semantic envelope against an injected deployed adapter."""

    compile_plan()
    contract = _contract()
    if (
        not isinstance(fixture_sha256, tuple)
        or len(fixture_sha256) != 2
        or len(set(fixture_sha256)) != 2
        or any(not isinstance(item, str) or not SHA256_RE.fullmatch(item) for item in fixture_sha256)
    ):
        raise ExecutorError("configuration_error")
    try:
        guard = common.RunAuthorizationGuard.from_token(
            run_id=run_id,
            authorization_id=contract["authorization"]["authorization_id"],
            authorization_token=contract["authorization"]["acknowledgement"],
        )
        identity = guard.admit(
            run_id=run_id,
            authorization_id=contract["authorization"]["authorization_id"],
            authorization_token=acknowledgement,
        )
    except common.EvidenceCommonError as exc:
        raise ExecutorError("authorization_required") from exc

    budget = common.ExecutionBudget(max_requests=14, max_actions=14)
    recorder = common.EvidenceRecorder(budget)
    ledger = common.ResourceLedger(identity, budget, max_resources=1)
    pre_state: Mapping[str, Any] | None = None
    post_state: Mapping[str, Any] | None = None
    cleanup_proof: dict[str, bool] = {}
    postcondition_proof: dict[str, bool] = {}
    semantic = {
        "five_tools": False,
        "single_video_report": False,
        "multi_video_report": False,
        "live_caption": False,
        "latest_prompt_overwrite": False,
        "cross_agent_isolation": False,
        "disconnect_cancel_quiescence": False,
    }

    def cleanup(resource_id: str) -> None:
        nonlocal cleanup_proof
        budget.consume_request()
        try:
            proof = adapter.cleanup_exact_owned(run_id=run_id, resource_id=resource_id)
        except Exception as exc:
            raise ExecutorError("cleanup_failed") from exc
        required = contract["cleanup_contract"]["required_cleanup_proof"]
        if not isinstance(proof, Mapping) or not _true_fields(proof, required, exact=True):
            raise ExecutorError("cleanup_failed")
        cleanup_proof = {key: True for key in required}

    def postcondition(resource_id: str) -> bool:
        nonlocal post_state, postcondition_proof
        budget.consume_request()
        try:
            proof = adapter.verify_postcondition(run_id=run_id, resource_id=resource_id)
        except Exception:
            return False
        required = contract["cleanup_contract"]["required_postcondition_proof"]
        if not isinstance(proof, Mapping):
            return False
        proof = dict(proof)
        post_state_value = proof.pop("unrelated_state", None)
        if not isinstance(post_state_value, Mapping) or not _true_fields(proof, required, exact=True):
            return False
        post_state = dict(post_state_value)
        postcondition_proof = {key: True for key in required}
        return pre_state is not None and common.digest_value(pre_state) == common.digest_value(post_state)

    action_requests: dict[str, Mapping[str, Any]] = {
        "capture-pre-state": {"scope": "exact-run-and-unrelated-digest"},
        "discover-five-tools": {"expected_tools": contract["declared_tools"]},
        "verify-local-dependencies": {"required": ["lvs_backend", "rtvi_vlm", "elasticsearch", "kafka", "logstash"]},
        "setup-owned-fixtures": {"fixture_sha256": list(fixture_sha256), "warehouse_sample_bundle": False},
        "single-video-report": {"fixture_sha256": [fixture_sha256[0]], "expected_source_count": 1},
        "multi-video-report": {"fixture_sha256": list(fixture_sha256), "expected_source_count": 2},
        "start-live-caption": {"owner_run_id": run_id, "requirements": ["kafka", "logstash"]},
        "retrieve-live-caption": {"owner_run_id": run_id, "minimum_caption_count": 1},
        "write-shared-prompt-first": {"writer_agent": "agent-a", "prompt_version": 1},
        "overwrite-shared-prompt-latest": {"writer_agent": "agent-a", "prompt_version": 2},
        "reject-cross-agent-prompt-visibility": {"requesting_agent": "agent-b", "expected_visible": False},
        "probe-disconnect-cancel-quiescence": {"owner_run_id": run_id, "preserve_sibling": True},
    }

    primary: BaseException | None = None
    try:
        for action in contract["actions"][:12]:
            action_id = action["id"]
            result = _observation(adapter, budget, run_id, action_id, action_requests[action_id])
            passed = result["status"] == "pass" and _semantic_pass(
                action_id,
                result["facts"],
                contract=contract,
                run_id=run_id,
                fixture_sha256=fixture_sha256,
            )
            recorder.record(
                action_id=action_id,
                kind=action["kind"],
                status="pass" if passed else "fail",
                payload=common.canonical_bytes(result),
                result_code=result["result_code"] if passed else "oracle_failed",
            )
            if not passed:
                raise ExecutorError("oracle_failed")
            facts = result["facts"]
            if action_id == "capture-pre-state":
                pre_state = dict(facts["unrelated_state"])
            elif action_id == "setup-owned-fixtures":
                ledger.register(
                    owner_run_id=run_id,
                    resource_type="lvs-semantic-run-namespace",
                    resource_id=facts["resource_id"],
                    cleanup=cleanup,
                    postcondition=postcondition,
                )
            elif action_id == "discover-five-tools":
                semantic["five_tools"] = True
            elif action_id == "single-video-report":
                semantic["single_video_report"] = True
            elif action_id == "multi-video-report":
                semantic["multi_video_report"] = True
            elif action_id == "retrieve-live-caption":
                semantic["live_caption"] = True
            elif action_id == "overwrite-shared-prompt-latest":
                semantic["latest_prompt_overwrite"] = True
            elif action_id == "reject-cross-agent-prompt-visibility":
                semantic["cross_agent_isolation"] = True
            elif action_id == "probe-disconnect-cancel-quiescence":
                semantic["disconnect_cancel_quiescence"] = True
    except BaseException as exc:
        primary = exc
    finally:
        if ledger.active_count:
            try:
                if not ledger.cleanup():
                    raise ExecutorError("cleanup_failed")
                ledger.assert_postconditions()
            except BaseException as exc:
                if primary is None:
                    primary = exc
    if primary is not None:
        if isinstance(primary, ExecutorError):
            raise primary
        raise ExecutorError("oracle_failed") from primary
    if pre_state is None or post_state is None:
        raise ExecutorError("cleanup_failed")
    comparison = common.DigestComparison.compare(
        "unrelated-state-restored", pre_state, post_state, expectation="equal"
    )
    common_evidence = recorder.build(identity=identity, ledger=ledger, comparisons=[comparison])
    if budget.requests != 14 or budget.actions != 14:
        raise ExecutorError("oracle_failed")
    receipt = {
        **common_evidence,
        "package_id": contract["package_id"],
        "contract_sha256": hashlib.sha256(_bounded_read(CONTRACT_PATH)).hexdigest(),
        "fixture_sha256": list(fixture_sha256),
        "semantic_observations": semantic,
        "cleanup_proof": cleanup_proof,
        "postcondition_proof": postcondition_proof,
    }
    schema = _strict_json(_bounded_read(RECEIPT_SCHEMA_PATH))
    errors = list(Draft202012Validator(schema).iter_errors(receipt))
    if errors:
        raise ExecutorError("configuration_error")
    if receipt["status"] != "pass" or not all(semantic.values()):
        raise ExecutorError("oracle_failed")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("plan",))
    args = parser.parse_args()
    if args.command != "plan":
        return 2
    try:
        print(json.dumps(compile_plan(), sort_keys=True))
    except ExecutorError as exc:
        print(json.dumps({"status": "error", "code": exc.code}, sort_keys=True))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
