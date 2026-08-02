#!/usr/bin/env python3
"""Compile the current selected-500 semantic-executor status registry.

This compiler is deliberately inert: it reads bounded repository files,
validates source locks, and emits deterministic JSON.  It has no runtime or
canonical-write adapter.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any, Sequence

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4].resolve(strict=True)
CONTRACT_PATH = HERE / "contract.json"
SCHEMA_PATH = HERE / "registry.schema.json"
ARTIFACT_PATH = HERE / "execution-status-registry.json"
MAX_BYTES = 32 * 1024 * 1024


class RegistryError(RuntimeError):
    """Fail closed without exposing source content."""


def _read(path: Path, maximum: int = MAX_BYTES) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise RegistryError("cannot read bounded source") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum:
            raise RegistryError("source is not a bounded regular file")
        chunks: list[bytes] = []
        total = 0
        while total <= maximum:
            chunk = os.read(descriptor, min(131072, maximum + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        stable = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if len(raw) != before.st_size or any(
            getattr(before, key) != getattr(after, key) for key in stable
        ):
            raise RegistryError("source changed during read")
        return raw
    finally:
        os.close(descriptor)


def _decode(raw: bytes) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise RegistryError("duplicate JSON key")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                RegistryError("non-finite JSON value")
            ),
        )
    except RegistryError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RegistryError("invalid JSON") from exc
    if not isinstance(value, dict):
        raise RegistryError("JSON root is not an object")
    return value


def _json(path: Path) -> dict[str, Any]:
    return _decode(_read(path))


def _path(relative: str) -> Path:
    item = Path(relative)
    if item.is_absolute() or not item.parts or ".." in item.parts:
        raise RegistryError("invalid repository path")
    current = ROOT
    for part in item.parts:
        current /= part
        try:
            if stat.S_ISLNK(current.lstat().st_mode):
                raise RegistryError("symlink source rejected")
        except OSError as exc:
            raise RegistryError("missing source path") from exc
    try:
        current.resolve(strict=True).relative_to(ROOT)
    except (OSError, ValueError) as exc:
        raise RegistryError("source escapes repository") from exc
    return current


def _sha_value(value: Any) -> str:
    try:
        raw = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise RegistryError("non-canonical value") from exc
    return hashlib.sha256(raw).hexdigest()


def _one(rows: Any, key: str, value: str) -> dict[str, Any]:
    if not isinstance(rows, list):
        raise RegistryError("row collection missing")
    matches = [row for row in rows if isinstance(row, dict) and row.get(key) == value]
    if len(matches) != 1:
        raise RegistryError("row identity is not unique")
    return matches[0]


def _verify_source_locks(contract: dict[str, Any]) -> int:
    locks = contract.get("source_locks")
    if not isinstance(locks, list) or len(locks) != 20:
        raise RegistryError("source-lock inventory is not exact")
    seen: set[str] = set()
    for lock in locks:
        if not isinstance(lock, dict) or set(lock) != {"path", "sha256"}:
            raise RegistryError("invalid source lock")
        relative = lock["path"]
        if relative in seen or not isinstance(lock["sha256"], str):
            raise RegistryError("duplicate source lock")
        seen.add(relative)
        if hashlib.sha256(_read(_path(relative))).hexdigest() != lock["sha256"]:
            raise RegistryError("source lock mismatch")
    selected = contract["selected_metadata"]
    if (
        selected["path"] not in seen
        or selected["sha256"] != contract["source_locks"][0]["sha256"]
    ):
        raise RegistryError("selected metadata source lock missing")
    return len(seen)


def _verify_selected(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    selected_contract = contract["selected_metadata"]
    selected = _json(_path(selected_contract["path"]))
    if (
        selected.get("schema_version") != selected_contract["schema_version"]
        or not isinstance(selected.get("oracles"), list)
        or len(selected["oracles"]) != selected_contract["row_count"]
        or selected.get("target", {}).get("product_version")
        != selected_contract["product_version"]
        or selected.get("target", {}).get("main_commit")
        != selected_contract["main_commit"]
        or selected.get("policy", {}).get("warehouse_sample_bundle")
        != "excluded; custom-data fixtures remain in scope"
    ):
        raise RegistryError("selected metadata identity drift")
    found: dict[str, dict[str, Any]] = {}
    for expected in contract["canonical_rows"]:
        row = _one(selected["oracles"], "oracle_id", expected["oracle_id"])
        bounds = row.get("execution_bounds", {})
        cleanup = row.get("cleanup", {})
        materialization = row.get("fixture", {}).get("materialization", {})
        if (
            row.get("capability_id") != expected["capability_id"]
            or _sha_value(row) != expected["selected_row_sha256"]
            or row.get("current_state") != "open_unexecuted"
            or row.get("evidence") != []
            or row.get("acceptance_readiness", {}).get("classification")
            != "planning_index_only"
            or bounds.get("max_requests") != expected["max_requests"]
            or bounds.get("max_actions") != expected["max_actions"]
            or bounds.get("executor") is not None
            or bounds.get("collectors") != []
            or cleanup.get("executor") is not None
            or cleanup.get("postcondition_collectors") != []
            or materialization != {"generator": None, "path": None, "sha256": None}
        ):
            raise RegistryError("canonical row execution status drift")
        found[expected["oracle_id"]] = row
    if len(found) != 5:
        raise RegistryError("canonical row set is not exact-five")
    return found


def _load_candidate_contracts() -> dict[str, dict[str, Any]]:
    paths = {
        "base": "deploy/docker/thor-local/qualification/base-semantic-runtime-evidence/contract.json",
        "base_exact": "deploy/docker/thor-local/qualification/base-semantic-exact-cleanup-successor/contract.json",
        "lvs": "deploy/docker/thor-local/qualification/lvs-semantic-runtime-evidence/contract.json",
        "lvs_http": "deploy/docker/thor-local/qualification/lvs-semantic-runtime-http-successor/contract.json",
        "search": "deploy/docker/thor-local/qualification/search-semantic-runtime-evidence-successor/contract.json",
        "ui": "deploy/docker/thor-local/qualification/ui-runtime-contracts/contract.json",
    }
    return {key: _json(_path(path)) for key, path in paths.items()}


def _verify_candidates(candidates: dict[str, dict[str, Any]]) -> None:
    base = candidates["base"]
    base_cases = {
        row.get("planning_requirement_id"): row
        for row in base.get("cases", [])
        if isinstance(row, dict)
    }
    if (
        base.get("package_id") != "base-semantic-runtime-evidence"
        or base.get("default_execution_enabled") is not False
        or base.get("evidence", {}).get("promotion_eligible") is not False
        or (
            base_cases.get("tiny-agent-media", {}).get("adapter"),
            base_cases.get("tiny-agent-media", {}).get("max_requests"),
        )
        != ("bounded-http", 8)
        or (
            base_cases.get("hitl-state-transcript", {}).get("adapter"),
            base_cases.get("hitl-state-transcript", {}).get("max_requests"),
        )
        != ("bounded-http", 11)
        or (
            base_cases.get("ui-tiny-media", {}).get("adapter"),
            base_cases.get("ui-tiny-media", {}).get("max_requests"),
        )
        != ("manual-browser-receipt", 11)
    ):
        raise RegistryError("Base predecessor classification drift")
    base_source = _read(
        _path(
            "deploy/docker/thor-local/qualification/base-semantic-runtime-evidence/executor.py"
        )
    ).decode("utf-8")
    if (
        "owned_namespace_path" not in base_source
        or "cleanup_op" not in base_source
        or 'resource_type="base-semantic-namespace"' not in base_source
    ):
        raise RegistryError("Base predecessor cleanup shape drift")

    exact = candidates["base_exact"]
    analysis = exact.get("full_workflow_envelope_analysis", {})
    if (
        exact.get("package_id") != "base-semantic-exact-cleanup-successor"
        or exact.get("promotion_eligible") is not False
        or exact.get("predecessor")
        != "deploy/docker/thor-local/qualification/base-semantic-runtime-evidence"
        or exact.get("transport", {}).get("max_requests") != 7
        or exact.get("cleanup", {}).get("semantics") != "exact_object_key"
        or exact.get("cleanup", {}).get("namespace_delete_supported") is not False
        or analysis.get("frozen")
        != {"tiny-agent-media": 8, "hitl-state-transcript": 11}
        or analysis.get("required_exact_cleanup_success")
        != {"tiny-agent-media": 11, "hitl-state-transcript": 12}
        or analysis.get("canonical_update_reviewed") is not False
    ):
        raise RegistryError("Base exact-cleanup successor classification drift")

    lvs = candidates["lvs"]
    lvs_source = _read(
        _path(
            "deploy/docker/thor-local/qualification/lvs-semantic-runtime-evidence/executor.py"
        )
    ).decode("utf-8")
    if (
        lvs.get("package_id") != "thor-vss-lvs-semantic-runtime-evidence-v1"
        or lvs.get("mode") != "authorization-gated-injected-adapter-runtime"
        or lvs.get("default_execution_enabled") is not False
        or lvs.get("execution_bounds", {}).get("max_requests") != 14
        or "class SemanticAdapter(Protocol)" not in lvs_source
        or "def run_executor(" not in lvs_source
        or "BoundedHTTPTransport" in lvs_source
        or "LiveOpener" in lvs_source
    ):
        raise RegistryError("LVS injected-adapter classification drift")

    lvs_http = candidates["lvs_http"]
    coverage = lvs_http.get("predecessor_action_coverage", {})
    lvs_http_source = _read(
        _path(
            "deploy/docker/thor-local/qualification/lvs-semantic-runtime-http-successor/executor.py"
        )
    ).decode("utf-8")
    if (
        lvs_http.get("package_id") != "thor-vss-lvs-semantic-runtime-http-successor-v1"
        or lvs_http.get("mode")
        != "authorization-gated-bounded-numeric-loopback-http-candidate"
        or lvs_http.get("default_execution_enabled") is not False
        or lvs_http.get("predecessor_package")
        != "thor-vss-lvs-semantic-runtime-evidence-v1"
        or lvs_http.get("execution_bounds", {}).get("max_requests") != 14
        or lvs_http.get("execution_bounds", {}).get("max_actions") != 14
        or coverage.get("concrete_complete") != ["setup-owned-fixtures"]
        or len(coverage.get("concrete_partial", {})) != 5
        or len(coverage.get("residual_adapter_required", {})) != 8
        or lvs_http.get("evidence", {}).get("executor_ready") is not False
        or lvs_http.get("evidence", {}).get("promotion_eligible") is not False
        or "class LiveTransport" not in lvs_http_source
        or "ProxyHandler({})" not in lvs_http_source
        or "redirects_enabled = False" not in lvs_http_source
    ):
        raise RegistryError("LVS concrete partial HTTP classification drift")

    search = candidates["search"]
    if (
        search.get("package_id") != "search-semantic-runtime-evidence-successor"
        or search.get("mode") != "authorization-gated-bounded-numeric-loopback-http"
        or search.get("default_execution_enabled") is not False
        or search.get("evidence", {}).get("promotion_eligible") is not False
        or search.get("execution_bounds", {}).get("max_requests") != 14
        or search.get("execution_bounds", {}).get("max_actions") != 14
        or search.get("ownership", {}).get("registration_gate")
        != "operator run-ownership attestation plus exact _mget readback of six index/document/source-digest tuples"
        or "operator-attested pre-provisioned fixture"
        not in search.get("evidence", {}).get("reason", "")
    ):
        raise RegistryError("Search concrete-transport classification drift")

    ui = candidates["ui"]
    ui_case = _one(
        ui.get("requirements", []), "capability_id", "runtime.ui.video-management-tab"
    )
    if (
        ui.get("package_id") != "thor-ui-runtime-contracts-v1"
        or ui.get("policy", {}).get("runtime_executor_implemented") is not False
        or ui.get("policy", {}).get("browser_allowed") is not False
        or ui.get("policy", {}).get("runtime_evidence") != []
        or ui.get("future_execution_gate", {}).get("executor") is not None
        or ui.get("current_state", {}).get("live_state_advanced") is not False
        or ui.get("current_state", {}).get("runtime_evidence") != []
        or ui_case.get("planning_requirement_id") != "ui-tiny-media"
    ):
        raise RegistryError("UI manual-receipt classification drift")


def _layer(
    package_id: str,
    classification: str,
    transport_kind: str,
    scope: str,
    concrete: bool,
    exact_cleanup: bool,
    declared: int | None,
    corrected: int | None,
    note: str,
) -> dict[str, Any]:
    return {
        "package_id": package_id,
        "classification": classification,
        "transport_kind": transport_kind,
        "scope": scope,
        "concrete_transport": concrete,
        "exact_cleanup": exact_cleanup,
        "declared_request_bound": declared,
        "corrected_full_envelope_requests": corrected,
        "canonical_bound": False,
        "integrated": False,
        "runtime_receipts": 0,
        "promotion_eligible": False,
        "note": note,
    }


def _candidate(expected: dict[str, Any]) -> tuple[dict[str, Any], str]:
    classification = expected["classification"]
    if (
        classification
        == "base_concrete_predecessor_invalid_cleanup_exact_cleanup_partial_unbound"
    ):
        corrected = 11 if expected["max_requests"] == 8 else 12
        layers = [
            _layer(
                "base-semantic-runtime-evidence",
                "concrete_full_workflow_transport_invalid_namespace_cleanup",
                "numeric_loopback_http",
                "full_workflow",
                True,
                False,
                expected["max_requests"],
                None,
                "Concrete workflow transport exists, but deleting the namespace path does not remove timestamped report files.",
            ),
            _layer(
                "base-semantic-exact-cleanup-successor",
                "concrete_exact_file_cleanup_partial_slice_unbound",
                "numeric_loopback_http",
                "partial_exact_cleanup_slice",
                True,
                True,
                7,
                corrected,
                "Exact Markdown/PDF read-delete-404 cleanup is concrete; the corrected 11/12 full envelope is not canonically reviewed or integrated.",
            ),
        ]
        candidate = {
            "primary_classification": classification,
            "any_concrete_http_transport": True,
            "invalid_full_workflow_cleanup": True,
            "partial_exact_cleanup_transport": True,
            "exact_full_envelope_transport": False,
            "operator_preprovisioned_fixture": False,
            "injected_adapter_only": False,
            "injected_adapter_core": False,
            "concrete_partial_lvs_http_transport": False,
            "manual_receipt_only": False,
            "browser_executor": False,
            "canonical_bound": False,
            "fully_integrated": False,
            "runtime_receipts": 0,
            "promotion_eligible": False,
            "layers": layers,
        }
        boundary = "Review and bind corrected full 11/12 envelopes, then execute them with exact child cleanup and admit current runtime evidence."
    elif (
        classification
        == "injected_adapter_core_with_concrete_partial_http_successor_unbound"
    ):
        candidate = {
            "primary_classification": classification,
            "any_concrete_http_transport": True,
            "invalid_full_workflow_cleanup": False,
            "partial_exact_cleanup_transport": True,
            "exact_full_envelope_transport": False,
            "operator_preprovisioned_fixture": False,
            "injected_adapter_only": False,
            "injected_adapter_core": True,
            "concrete_partial_lvs_http_transport": True,
            "manual_receipt_only": False,
            "browser_executor": False,
            "canonical_bound": False,
            "fully_integrated": False,
            "runtime_receipts": 0,
            "promotion_eligible": False,
            "layers": [
                _layer(
                    "thor-vss-lvs-semantic-runtime-evidence-v1",
                    "abstract_semantic_adapter_envelope",
                    "injected_semantic_adapter",
                    "abstract_envelope",
                    False,
                    True,
                    14,
                    None,
                    "The core validates facts and cleanup from an injected adapter but provides no deployed HTTP transport.",
                ),
                _layer(
                    "thor-vss-lvs-semantic-runtime-http-successor-v1",
                    "concrete_bounded_partial_lvs_http_action_coverage",
                    "numeric_loopback_http",
                    "partial_http_action_slice",
                    True,
                    True,
                    14,
                    None,
                    "The reviewed HTTP successor completes fixture setup and partially observes five actions; eight Agent/session/stream actions still require adapters.",
                ),
            ],
        }
        boundary = "Integrate the remaining eight Agent/session/stream adapters and five partial observations into one reviewed full oracle transport, then collect and admit runtime evidence."
    elif (
        classification
        == "concrete_exact_transport_operator_preprovisioned_fixture_unbound"
    ):
        candidate = {
            "primary_classification": classification,
            "any_concrete_http_transport": True,
            "invalid_full_workflow_cleanup": False,
            "partial_exact_cleanup_transport": False,
            "exact_full_envelope_transport": True,
            "operator_preprovisioned_fixture": True,
            "injected_adapter_only": False,
            "injected_adapter_core": False,
            "concrete_partial_lvs_http_transport": False,
            "manual_receipt_only": False,
            "browser_executor": False,
            "canonical_bound": False,
            "fully_integrated": False,
            "runtime_receipts": 0,
            "promotion_eligible": False,
            "layers": [
                _layer(
                    "search-semantic-runtime-evidence-successor",
                    "concrete_exact_14_http_envelope_operator_fixture_attested",
                    "numeric_loopback_http",
                    "full_workflow",
                    True,
                    True,
                    14,
                    None,
                    "Exact Search/Elasticsearch transport and delayed cleanup exist; fixture creation is outside the envelope and operator-attested.",
                )
            ],
        }
        boundary = "Collect and review a deployed receipt, retain the pre-provisioned-fixture limitation, and bind only through a separate canonical integration step."
    elif classification == "manual_receipt_only_no_browser_executor":
        candidate = {
            "primary_classification": classification,
            "any_concrete_http_transport": False,
            "invalid_full_workflow_cleanup": False,
            "partial_exact_cleanup_transport": False,
            "exact_full_envelope_transport": False,
            "operator_preprovisioned_fixture": False,
            "injected_adapter_only": False,
            "injected_adapter_core": False,
            "concrete_partial_lvs_http_transport": False,
            "manual_receipt_only": True,
            "browser_executor": False,
            "canonical_bound": False,
            "fully_integrated": False,
            "runtime_receipts": 0,
            "promotion_eligible": False,
            "layers": [
                _layer(
                    "base-semantic-runtime-evidence",
                    "strict_manual_browser_receipt_shape_only",
                    "manual_receipt",
                    "manual_ui_evidence",
                    False,
                    False,
                    11,
                    None,
                    "The Base package validates a supplied manual UI receipt; it does not drive a browser.",
                ),
                _layer(
                    "thor-ui-runtime-contracts-v1",
                    "future_browser_receipt_validator_only",
                    "receipt_validator_only",
                    "manual_ui_evidence",
                    False,
                    True,
                    None,
                    None,
                    "The UI contract has no execute command, browser driver, API client, or runtime evidence.",
                ),
            ],
        }
        boundary = "Implement and authorize a bounded browser executor, collect correlated DOM/trace/screenshot/API evidence, and complete exact-owned cleanup."
    else:
        raise RegistryError("unknown candidate classification")
    return candidate, boundary


def compile_registry() -> dict[str, Any]:
    contract = _json(CONTRACT_PATH)
    if (
        contract.get("schema_version") != 1
        or contract.get("package_id") != "semantic-executor-bindings-current"
        or contract.get("mode") != "selected-500-static-execution-status-registry"
        or contract.get("default_execution_enabled") is not False
        or contract.get("warehouse_sample_bundle") != "excluded"
        or [row.get("ordinal") for row in contract.get("canonical_rows", [])]
        != [1, 2, 3, 4, 5]
        or len({row.get("oracle_id") for row in contract.get("canonical_rows", [])})
        != 5
    ):
        raise RegistryError("registry contract identity drift")
    lock_count = _verify_source_locks(contract)
    selected = _verify_selected(contract)
    candidates = _load_candidate_contracts()
    _verify_candidates(candidates)
    rows = []
    for expected in contract["canonical_rows"]:
        row = selected[expected["oracle_id"]]
        bounds = row["execution_bounds"]
        candidate, boundary = _candidate(expected)
        rows.append(
            {
                "ordinal": expected["ordinal"],
                "capability_id": expected["capability_id"],
                "oracle_id": expected["oracle_id"],
                "canonical": {
                    "selected_row_sha256": expected["selected_row_sha256"],
                    "current_state": "open_unexecuted",
                    "acceptance_classification": "planning_index_only",
                    "max_requests": bounds["max_requests"],
                    "max_actions": bounds["max_actions"],
                    "executor": None,
                    "collectors": [],
                    "cleanup_executor": None,
                    "postcondition_collectors": [],
                    "fixture_materialized": False,
                    "runtime_evidence_count": 0,
                    "executor_ready": False,
                    "fully_integrated": False,
                    "promoted": False,
                },
                "candidate": candidate,
                "remaining_boundary": boundary,
            }
        )
    summary = {
        "canonical_row_count": len(rows),
        "canonical_executor_ready_count": sum(
            row["canonical"]["executor_ready"] for row in rows
        ),
        "canonical_fully_integrated_count": sum(
            row["canonical"]["fully_integrated"] for row in rows
        ),
        "canonical_runtime_evidence_count": sum(
            row["canonical"]["runtime_evidence_count"] for row in rows
        ),
        "canonical_promotion_count": sum(row["canonical"]["promoted"] for row in rows),
        "candidate_rows_with_any_concrete_http_transport": sum(
            row["candidate"]["any_concrete_http_transport"] for row in rows
        ),
        "candidate_rows_with_invalid_full_workflow_cleanup": sum(
            row["candidate"]["invalid_full_workflow_cleanup"] for row in rows
        ),
        "candidate_rows_with_partial_exact_cleanup_transport": sum(
            row["candidate"]["partial_exact_cleanup_transport"] for row in rows
        ),
        "candidate_rows_with_exact_full_envelope_transport": sum(
            row["candidate"]["exact_full_envelope_transport"] for row in rows
        ),
        "candidate_rows_with_operator_preprovisioned_fixture": sum(
            row["candidate"]["operator_preprovisioned_fixture"] for row in rows
        ),
        "candidate_rows_with_injected_adapter_only": sum(
            row["candidate"]["injected_adapter_only"] for row in rows
        ),
        "candidate_rows_with_injected_adapter_core": sum(
            row["candidate"]["injected_adapter_core"] for row in rows
        ),
        "candidate_rows_with_concrete_partial_lvs_http_transport": sum(
            row["candidate"]["concrete_partial_lvs_http_transport"] for row in rows
        ),
        "candidate_rows_with_manual_receipt_only": sum(
            row["candidate"]["manual_receipt_only"] for row in rows
        ),
        "candidate_rows_with_browser_executor": sum(
            row["candidate"]["browser_executor"] for row in rows
        ),
        "candidate_runtime_receipt_count": sum(
            row["candidate"]["runtime_receipts"] for row in rows
        ),
        "candidate_promotion_count": sum(
            row["candidate"]["promotion_eligible"] for row in rows
        ),
        "concrete_http_executor_package_count": 4,
    }
    if summary != contract["expected_summary"]:
        raise RegistryError("derived summary differs from contract")
    artifact = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "status": "selected_500_execution_status_verified_non_promoting",
        "valid": True,
        "promotion_eligible": False,
        "runtime_activity_performed": False,
        "canonical_state_mutated": False,
        "selected_metadata": contract["selected_metadata"],
        "source_locks_verified": lock_count,
        "rows": rows,
        "summary": summary,
    }
    schema = _json(SCHEMA_PATH)
    try:
        Draft202012Validator.check_schema(schema)
        errors = list(Draft202012Validator(schema).iter_errors(artifact))
    except Exception as exc:
        raise RegistryError("registry schema invalid") from exc
    if errors:
        raise RegistryError("compiled registry violates schema")
    return artifact


def check_artifact() -> dict[str, Any]:
    compiled = compile_registry()
    checked = _json(ARTIFACT_PATH)
    if checked != compiled:
        raise RegistryError("checked registry artifact is stale")
    return {
        "schema_version": 1,
        "package_id": "semantic-executor-bindings-current",
        "status": "checked_artifact_current_non_promoting",
        "valid": True,
        "runtime_activity_performed": False,
        "canonical_state_mutated": False,
        "artifact_sha256": _sha_value(checked),
        "canonical_executor_ready_count": 0,
        "canonical_fully_integrated_count": 0,
        "canonical_runtime_evidence_count": 0,
        "canonical_promotion_count": 0,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", nargs="?", choices=("compile", "check"), default="check"
    )
    args = parser.parse_args(argv)
    try:
        result = compile_registry() if args.command == "compile" else check_artifact()
    except RegistryError as exc:
        print(
            json.dumps({"status": "error", "error": str(exc)}, sort_keys=True),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
