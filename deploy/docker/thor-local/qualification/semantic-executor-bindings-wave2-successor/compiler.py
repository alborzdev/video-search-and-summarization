#!/usr/bin/env python3
"""Compile the additive wave-2 selected-five candidate status registry.

The compiler is deliberately inert.  It reads bounded source-locked repository
files and emits deterministic JSON; it has no runtime or canonical-write path.
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
            getattr(before, field) != getattr(after, field) for field in stable
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
    if not isinstance(locks, list) or len(locks) != 22:
        raise RegistryError("source-lock inventory is not exact")
    seen: set[str] = set()
    for lock in locks:
        if not isinstance(lock, dict) or set(lock) != {"path", "sha256"}:
            raise RegistryError("invalid source lock")
        relative = lock["path"]
        digest = lock["sha256"]
        if (
            relative in seen
            or not isinstance(relative, str)
            or not isinstance(digest, str)
        ):
            raise RegistryError("duplicate or invalid source lock")
        seen.add(relative)
        if hashlib.sha256(_read(_path(relative))).hexdigest() != digest:
            raise RegistryError("source lock mismatch")
    published = contract["published_registry"]
    if published["path"] not in seen or published["sha256"] != locks[1]["sha256"]:
        raise RegistryError("published registry lock missing")
    package_prefixes = {
        "base-semantic-full-envelope-successor": 5,
        "search-semantic-fixture-provisioning-blocker-successor": 4,
        "ui-video-management-playwright-successor": 5,
        "lvs-semantic-runtime-agent-session-successor": 4,
    }
    for package, expected in package_prefixes.items():
        prefix = f"deploy/docker/thor-local/qualification/{package}/"
        if sum(path.startswith(prefix) for path in seen) != expected:
            raise RegistryError("wave-2 package lock inventory drift")
    return len(seen)


def _verify_published(
    contract: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    published_contract = contract["published_registry"]
    published = _json(_path(published_contract["path"]))
    summary = published.get("summary", {})
    if (
        published.get("package_id") != published_contract["package_id"]
        or published.get("status")
        != "selected_500_execution_status_verified_non_promoting"
        or published.get("runtime_activity_performed") is not False
        or published.get("canonical_state_mutated") is not False
        or published.get("promotion_eligible") is not False
        or summary.get("canonical_row_count")
        != published_contract["canonical_row_count"]
        or summary.get("canonical_executor_ready_count")
        != published_contract["canonical_executor_ready_count"]
        or summary.get("canonical_fully_integrated_count")
        != published_contract["canonical_fully_integrated_count"]
        or summary.get("canonical_runtime_evidence_count")
        != published_contract["canonical_runtime_evidence_count"]
        or summary.get("canonical_promotion_count")
        != published_contract["canonical_promotion_count"]
    ):
        raise RegistryError("published registry boundary drift")

    found: dict[str, dict[str, Any]] = {}
    for expected in contract["canonical_rows"]:
        row = _one(published.get("rows"), "oracle_id", expected["oracle_id"])
        canonical = row.get("canonical", {})
        if (
            row.get("ordinal") != expected["ordinal"]
            or row.get("capability_id") != expected["capability_id"]
            or canonical.get("selected_row_sha256") != expected["selected_row_sha256"]
            or canonical.get("max_requests") != expected["max_requests"]
            or canonical.get("max_actions") != expected["max_actions"]
            or canonical.get("current_state") != "open_unexecuted"
            or canonical.get("acceptance_classification") != "planning_index_only"
            or canonical.get("executor") is not None
            or canonical.get("collectors") != []
            or canonical.get("cleanup_executor") is not None
            or canonical.get("postcondition_collectors") != []
            or canonical.get("fixture_materialized") is not False
            or canonical.get("runtime_evidence_count") != 0
            or canonical.get("executor_ready") is not False
            or canonical.get("fully_integrated") is not False
            or canonical.get("promoted") is not False
        ):
            raise RegistryError("published canonical selected-five truth drift")
        found[expected["oracle_id"]] = canonical
    if len(found) != 5:
        raise RegistryError("published canonical row set is not exact-five")
    return published, found


def _candidate_contracts() -> dict[str, dict[str, Any]]:
    paths = {
        "base": "deploy/docker/thor-local/qualification/base-semantic-full-envelope-successor/contract.json",
        "search": "deploy/docker/thor-local/qualification/search-semantic-fixture-provisioning-blocker-successor/contract.json",
        "ui": "deploy/docker/thor-local/qualification/ui-video-management-playwright-successor/contract.json",
        "lvs": "deploy/docker/thor-local/qualification/lvs-semantic-runtime-agent-session-successor/contract.json",
    }
    return {key: _json(_path(path)) for key, path in paths.items()}


def _verify_candidates(candidates: dict[str, dict[str, Any]]) -> None:
    base = candidates["base"]
    base_cases = {case.get("capability_id"): case for case in base.get("cases", [])}
    base_chat = base_cases.get("runtime.workflow.base-chat-report", {})
    base_hitl = base_cases.get("runtime.agent.base-hitl", {})
    if (
        base.get("package_id") != "base-semantic-full-envelope-successor"
        or base.get("mode") != "authorization_gated_local_runtime_candidate"
        or base.get("canonical_binding") is not False
        or base.get("promotion_eligible") is not False
        or base.get("warehouse_sample_bundle") != "excluded"
        or (base_chat.get("max_requests"), base_chat.get("max_actions")) != (11, 11)
        or base_chat.get("report_step_id") != "generate-report"
        or (base_hitl.get("max_requests"), base_hitl.get("max_actions")) != (12, 12)
        or base_hitl.get("report_step_id") != "restart-and-check-persistence"
        or base.get("ownership", {}).get(
            "delete_only_report_step_response_derived_exact_keys"
        )
        is not True
        or base.get("ownership", {}).get("preexisting_absence_proven") is not False
    ):
        raise RegistryError("Base wave-2 candidate classification drift")
    base_source = _read(
        _path(
            "deploy/docker/thor-local/qualification/base-semantic-full-envelope-successor/executor.py"
        )
    ).decode("utf-8")
    if "def execute_http(" not in base_source or "report_step_id" not in base_source:
        raise RegistryError("Base concrete executor shape drift")

    search = candidates["search"]
    decision = search.get("decision", {})
    if (
        search.get("package_id")
        != "search-semantic-fixture-provisioning-blocker-successor"
        or search.get("kind") != "source-locked-blocker-and-adapter-contract"
        or search.get("default_execution_enabled") is not False
        or search.get("runtime_transport_implemented") is not False
        or search.get("warehouse_sample_bundle") != "excluded"
        or decision.get("safe_exact_full_fixture_creation_proven") is not False
        or decision.get("operator_preprovisioned_fixture_gap_closed") is not False
        or decision.get("predecessor_executor_binding_permitted") is not False
        or decision.get("promotion_eligible") is not False
        or decision.get("canonical_state_advanced") is not False
        or search.get("maximal_public_api_adapter", {}).get("status")
        != "design_only_blocked_before_runtime_binding"
    ):
        raise RegistryError("Search wave-2 blocker classification drift")
    search_source = _read(
        _path(
            "deploy/docker/thor-local/qualification/search-semantic-fixture-provisioning-blocker-successor/compiler.py"
        )
    ).decode("utf-8")
    if "def compile_plan(" not in search_source or "def execute" in search_source:
        raise RegistryError("Search blocker executable boundary drift")

    ui = candidates["ui"]
    browser = ui.get("browser_availability", {})
    boundary = ui.get("canonical_boundary", {})
    bounds = ui.get("bounds", {})
    if (
        ui.get("package_id") != "thor-ui-video-management-playwright-successor-v1"
        or ui.get("mode") != "authorization-gated-preexisting-cdp-playwright-candidate"
        or ui.get("default_execution_enabled") is not False
        or ui.get("warehouse_sample_bundle") != "excluded"
        or browser.get("codex_browser_plugin") != "absent"
        or browser.get("browser_launch_allowed") is not False
        or browser.get("browser_install_allowed") is not False
        or (bounds.get("max_api_exchanges"), bounds.get("max_browser_actions"))
        != (32, 40)
        or bounds.get("semantic_checkpoints") != 11
        or boundary.get("playwright_entry_files_pinned") is not True
        or boundary.get("playwright_transitive_graph_pinned") is not True
        or boundary.get("canonical_bound") is not False
        or boundary.get("executor_ready") is not False
        or boundary.get("promotion_eligible") is not False
    ):
        raise RegistryError("UI wave-2 candidate classification drift")
    harness = _read(
        _path(
            "deploy/docker/thor-local/qualification/ui-video-management-playwright-successor/harness.mjs"
        )
    ).decode("utf-8")
    ui_source = _read(
        _path(
            "deploy/docker/thor-local/qualification/ui-video-management-playwright-successor/executor.py"
        )
    ).decode("utf-8")
    if (
        "connectOverCDP" not in harness
        or ".launch(" in harness
        or "def execute(" not in ui_source
    ):
        raise RegistryError("UI concrete browser executor shape drift")

    lvs = candidates["lvs"]
    coverage = lvs.get("semantic_coverage", {})
    lvs_bounds = lvs.get("execution_bounds", {})
    evidence = lvs.get("evidence", {})
    if (
        lvs.get("package_id")
        != "thor-vss-lvs-semantic-runtime-agent-session-successor-v1"
        or lvs.get("mode")
        != "authorization-gated-bounded-numeric-loopback-nat-websocket-candidate"
        or lvs.get("default_execution_enabled") is not False
        or lvs.get("warehouse_sample_bundle") != "excluded"
        or (lvs_bounds.get("max_requests"), lvs_bounds.get("max_actions")) != (34, 34)
        or len(coverage.get("concrete_complete", [])) != 5
        or len(coverage.get("concrete_partial", {})) != 5
        or len(coverage.get("residual_adapter_required", {})) != 4
        or evidence.get("promotion_eligible") is not False
        or evidence.get("executor_ready") is not False
        or evidence.get("canonical_state_advanced") is not False
    ):
        raise RegistryError("LVS wave-2 candidate classification drift")
    lvs_source = _read(
        _path(
            "deploy/docker/thor-local/qualification/lvs-semantic-runtime-agent-session-successor/executor.py"
        )
    ).decode("utf-8")
    if (
        "class LiveTransport" not in lvs_source
        or "ProxyHandler({})" not in lvs_source
        or "def execute_agent_session(" not in lvs_source
    ):
        raise RegistryError("LVS concrete executor shape drift")


def _candidate(expected: dict[str, Any]) -> dict[str, Any]:
    key = expected["wave2_package_key"]
    common: dict[str, Any] = {
        "candidate_max_requests": expected["candidate_max_requests"],
        "candidate_max_actions": expected["candidate_max_actions"],
        "canonical_bound": False,
        "executor_ready": False,
        "runtime_receipts": 0,
        "promotion_eligible": False,
    }
    if key == "base":
        return common | {
            "package_id": "base-semantic-full-envelope-successor",
            "classification": "concrete_exact_full_envelope_candidate_unbound",
            "transport_kind": "numeric_loopback_http",
            "concrete_executor": True,
            "exact_full_envelope_candidate": True,
            "partial_transport": False,
            "browser_executor": False,
            "static_blocker_only": False,
            "exact_owned_cleanup": True,
            "unbound_reasons": [
                "candidate corrected request/action bound exceeds the frozen selected-row bound",
                "canonical executor and collectors remain null/empty",
                "report-object preexisting absence is not proven",
                "no live runtime receipt has been collected or admitted",
            ],
        }
    if key == "lvs":
        return common | {
            "package_id": "thor-vss-lvs-semantic-runtime-agent-session-successor-v1",
            "classification": "concrete_agent_session_partial_successor_unbound",
            "transport_kind": "numeric_loopback_nat_websocket_and_http",
            "concrete_executor": True,
            "exact_full_envelope_candidate": False,
            "partial_transport": True,
            "browser_executor": False,
            "static_blocker_only": False,
            "exact_owned_cleanup": True,
            "unbound_reasons": [
                "34-request/action successor is not the frozen selected 14-request/action envelope",
                "runtime five-tool discovery and dependency identity remain absent",
                "fixture digest readback, live captions, and disconnect/quiescence remain unproven",
                "report-object preexisting absence and complete unrelated Agent state restoration are not proven",
                "no live runtime receipt has been collected or admitted",
            ],
        }
    if key == "search":
        return common | {
            "package_id": "search-semantic-fixture-provisioning-blocker-successor",
            "classification": "static_exact_fixture_provisioning_blocker",
            "transport_kind": "none",
            "concrete_executor": False,
            "exact_full_envelope_candidate": False,
            "partial_transport": False,
            "browser_executor": False,
            "static_blocker_only": True,
            "exact_owned_cleanup": False,
            "unbound_reasons": [
                "public ingestion cannot request the predecessor's fixed selected-object identity",
                "RTVI-CV registration can be silently skipped and index bindings do not align",
                "public deletion is best-effort and cannot prove exact cross-system rollback",
                "the existing 14-action Search executor still requires an operator-preprovisioned fixture",
            ],
        }
    if key == "ui":
        return common | {
            "package_id": "thor-ui-video-management-playwright-successor-v1",
            "classification": "concrete_preexisting_cdp_browser_candidate_unbound",
            "transport_kind": "preexisting_cdp_playwright_and_numeric_loopback_http",
            "concrete_executor": True,
            "exact_full_envelope_candidate": False,
            "partial_transport": False,
            "browser_executor": True,
            "static_blocker_only": False,
            "exact_owned_cleanup": True,
            "unbound_reasons": [
                "Codex Browser plugin is absent; the candidate uses regular Playwright over preexisting CDP",
                "Playwright entry files and complete package trees are digest-pinned",
                "40 browser actions and 32 API exchanges exceed the frozen selected 11/11 bounds",
                "no rendered live runtime receipt has been collected or admitted",
            ],
        }
    raise RegistryError("unknown wave-2 package key")


def compile_registry() -> dict[str, Any]:
    contract = _json(CONTRACT_PATH)
    if (
        contract.get("schema_version") != 1
        or contract.get("package_id") != "semantic-executor-bindings-wave2-successor"
        or contract.get("mode")
        != "additive-selected-five-static-candidate-status-registry"
        or contract.get("default_execution_enabled") is not False
        or contract.get("warehouse_sample_bundle") != "excluded"
        or [row.get("ordinal") for row in contract.get("canonical_rows", [])]
        != [1, 2, 3, 4, 5]
        or len({row.get("oracle_id") for row in contract.get("canonical_rows", [])})
        != 5
    ):
        raise RegistryError("wave-2 registry contract identity drift")
    lock_count = _verify_source_locks(contract)
    published, canonical_rows = _verify_published(contract)
    candidates = _candidate_contracts()
    _verify_candidates(candidates)

    rows: list[dict[str, Any]] = []
    for expected in contract["canonical_rows"]:
        canonical = canonical_rows[expected["oracle_id"]]
        rows.append(
            {
                "ordinal": expected["ordinal"],
                "capability_id": expected["capability_id"],
                "oracle_id": expected["oracle_id"],
                "canonical": {
                    "selected_row_sha256": canonical["selected_row_sha256"],
                    "current_state": canonical["current_state"],
                    "acceptance_classification": canonical["acceptance_classification"],
                    "max_requests": canonical["max_requests"],
                    "max_actions": canonical["max_actions"],
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
                "wave2_candidate": _candidate(expected),
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
        "wave2_distinct_package_count": len(
            {row["wave2_candidate"]["package_id"] for row in rows}
        ),
        "wave2_concrete_executor_package_count": len(
            {
                row["wave2_candidate"]["package_id"]
                for row in rows
                if row["wave2_candidate"]["concrete_executor"]
            }
        ),
        "wave2_rows_with_concrete_executor": sum(
            row["wave2_candidate"]["concrete_executor"] for row in rows
        ),
        "wave2_rows_with_exact_full_envelope_candidate": sum(
            row["wave2_candidate"]["exact_full_envelope_candidate"] for row in rows
        ),
        "wave2_rows_with_partial_transport": sum(
            row["wave2_candidate"]["partial_transport"] for row in rows
        ),
        "wave2_rows_with_browser_executor": sum(
            row["wave2_candidate"]["browser_executor"] for row in rows
        ),
        "wave2_rows_with_static_blocker_only": sum(
            row["wave2_candidate"]["static_blocker_only"] for row in rows
        ),
        "wave2_runtime_receipt_count": sum(
            row["wave2_candidate"]["runtime_receipts"] for row in rows
        ),
        "wave2_canonical_binding_count": sum(
            row["wave2_candidate"]["canonical_bound"] for row in rows
        ),
        "wave2_promotion_count": sum(
            row["wave2_candidate"]["promotion_eligible"] for row in rows
        ),
    }
    if summary != contract["expected_summary"]:
        raise RegistryError("derived wave-2 summary differs from contract")

    artifact = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "status": "wave2_candidate_status_verified_non_promoting",
        "valid": True,
        "promotion_eligible": False,
        "runtime_activity_performed": False,
        "canonical_state_mutated": False,
        "warehouse_sample_bundle": "excluded",
        "published_registry": {
            "package_id": published["package_id"],
            "path": contract["published_registry"]["path"],
            "sha256": contract["published_registry"]["sha256"],
        },
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
        raise RegistryError("checked wave-2 registry artifact is stale")
    return {
        "schema_version": 1,
        "package_id": "semantic-executor-bindings-wave2-successor",
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
