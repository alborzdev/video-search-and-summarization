#!/usr/bin/env python3
"""Compile the inert current semantic-closure advertised binding overlay."""

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
CONTRACT = HERE / "contract.json"
CONTRACT_SCHEMA = HERE / "contract.schema.json"
SCHEMA = HERE / "binding-overlay.schema.json"
ARTIFACT = HERE / "binding-overlay.json"
MAX_BYTES = 32 * 1024 * 1024

MAPPING_PATH = (
    "deploy/docker/thor-local/qualification/"
    "candidate-approval-mapping-rebase-successor-v2/mapping.json"
)
ADVERTISED_PATH = (
    "deploy/docker/thor-local/qualification/"
    "remaining-advertised-entry-candidates/candidate.json"
)
BASE_DIR = (
    "deploy/docker/thor-local/qualification/base-semantic-owned-fixture-successor"
)
LVS_DIR = (
    "deploy/docker/thor-local/qualification/lvs-semantic-runtime-closure-successor"
)
LVS_PREDECESSOR_DIR = (
    "deploy/docker/thor-local/qualification/"
    "lvs-semantic-runtime-agent-session-successor"
)
SEARCH_DIR = (
    "deploy/docker/thor-local/qualification/"
    "search-semantic-exact-fixture-provisioner-successor"
)
SEARCH_EXECUTOR_DIR = (
    "deploy/docker/thor-local/qualification/search-semantic-runtime-evidence-successor"
)
UI_DIR = (
    "deploy/docker/thor-local/qualification/ui-video-management-playwright-successor"
)

EXPECTED_LOCK_PATHS = {
    MAPPING_PATH,
    ADVERTISED_PATH,
    f"{BASE_DIR}/contract.json",
    f"{BASE_DIR}/contract.schema.json",
    f"{BASE_DIR}/executor.py",
    f"{BASE_DIR}/request-manifest.schema.json",
    f"{BASE_DIR}/receipt.schema.json",
    f"{LVS_DIR}/contract.json",
    f"{LVS_DIR}/executor.py",
    f"{LVS_DIR}/manifest.schema.json",
    f"{LVS_DIR}/receipt.schema.json",
    f"{LVS_PREDECESSOR_DIR}/contract.json",
    f"{LVS_PREDECESSOR_DIR}/executor.py",
    f"{LVS_PREDECESSOR_DIR}/manifest.schema.json",
    f"{LVS_PREDECESSOR_DIR}/receipt.schema.json",
    f"{SEARCH_DIR}/contract.json",
    f"{SEARCH_DIR}/executor.py",
    f"{SEARCH_DIR}/receipt.schema.json",
    f"{SEARCH_EXECUTOR_DIR}/contract.json",
    f"{SEARCH_EXECUTOR_DIR}/contract.schema.json",
    f"{SEARCH_EXECUTOR_DIR}/executor.py",
    f"{SEARCH_EXECUTOR_DIR}/manifest.schema.json",
    f"{SEARCH_EXECUTOR_DIR}/receipt.schema.json",
    f"{UI_DIR}/contract.json",
    f"{UI_DIR}/executor.py",
    f"{UI_DIR}/harness.mjs",
    f"{UI_DIR}/manifest.schema.json",
    f"{UI_DIR}/receipt.schema.json",
}

BASE_REF = (
    (
        "base-semantic-owned-fixture-successor",
        f"{BASE_DIR}/executor.py",
        "semantic-executor",
    ),
)
LVS_REFS = (
    (
        "thor-vss-lvs-semantic-runtime-agent-session-successor-v1",
        f"{LVS_PREDECESSOR_DIR}/executor.py",
        "semantic-executor",
    ),
    (
        "thor-vss-lvs-semantic-runtime-closure-successor-v1",
        f"{LVS_DIR}/executor.py",
        "identity-and-live-caption-supplement",
    ),
)
SEARCH_REFS = (
    (
        "search-semantic-exact-fixture-provisioner-successor",
        f"{SEARCH_DIR}/executor.py",
        "exact-fixture-lifecycle",
    ),
    (
        "search-semantic-runtime-evidence-successor",
        f"{SEARCH_EXECUTOR_DIR}/executor.py",
        "semantic-executor-requiring-adapter",
    ),
)
SEARCH_ARCHIVE_REF = (SEARCH_REFS[0],)
UI_REF = (
    (
        "thor-ui-video-management-playwright-successor-v1",
        f"{UI_DIR}/executor.py",
        "rendered-semantic-executor",
    ),
)

# implementation_state describes implemented candidate code, not runtime proof,
# admission, canonical binding, or promotion.
EXPECTED_BINDINGS = {
    "manifest-entry.base-agent-workflow.01-visual-question-answering": (
        "concrete",
        "concrete_executor_candidate",
        BASE_REF,
    ),
    "manifest-entry.base-agent-workflow.02-vlm-report-generation": (
        "concrete",
        "concrete_executor_candidate",
        BASE_REF,
    ),
    "manifest-entry.video-summarization-file.02-multi-video-report": (
        "partial",
        "partial_executor_candidate",
        LVS_REFS,
    ),
    "manifest-entry.video-summarization-file.04-object-event-scenario-focus": (
        "partial",
        "partial_executor_candidate",
        LVS_REFS,
    ),
    "manifest-entry.semantic-search.00-natural-language-action-event-search": (
        "partial",
        "partial_executor_candidate",
        SEARCH_REFS,
    ),
    "manifest-entry.semantic-search.01-cv-attribute-search": (
        "partial",
        "partial_executor_candidate",
        SEARCH_REFS,
    ),
    "manifest-entry.semantic-search.02-multi-embedding-fusion": (
        "partial",
        "partial_executor_candidate",
        SEARCH_REFS,
    ),
    "manifest-entry.semantic-search.03-search-by-image": (
        "partial",
        "partial_executor_candidate",
        SEARCH_REFS,
    ),
    "manifest-entry.semantic-search.07-file-and-rtsp-archive-management": (
        "partial",
        "partial_executor_candidate",
        SEARCH_ARCHIVE_REF,
    ),
    "manifest-entry.main-ui.05-chunked-upload-and-rtsp-management": (
        "concrete",
        "concrete_executor_candidate",
        UI_REF,
    ),
}


class BindingError(RuntimeError):
    """Fail-closed validation error."""


def _read(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise BindingError("cannot read bounded source") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= MAX_BYTES:
            raise BindingError("source is not a bounded regular file")
        chunks: list[bytes] = []
        size = 0
        while size <= MAX_BYTES:
            chunk = os.read(descriptor, min(131072, MAX_BYTES + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
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
            raise BindingError("source changed during read")
        return raw
    finally:
        os.close(descriptor)


def _decode(raw: bytes) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise BindingError("duplicate JSON key")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                BindingError("non-finite JSON value")
            ),
        )
    except BindingError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BindingError("invalid JSON") from exc
    if not isinstance(value, dict):
        raise BindingError("JSON root is not an object")
    return value


def _json(path: Path) -> dict[str, Any]:
    return _decode(_read(path))


def _path(relative: str) -> Path:
    item = Path(relative)
    if item.is_absolute() or not item.parts or ".." in item.parts:
        raise BindingError("invalid repository path")
    current = ROOT
    for part in item.parts:
        current /= part
        try:
            if stat.S_ISLNK(current.lstat().st_mode):
                raise BindingError("symlink source rejected")
        except OSError as exc:
            raise BindingError("missing source path") from exc
    try:
        current.resolve(strict=True).relative_to(ROOT)
    except (OSError, ValueError) as exc:
        raise BindingError("source escapes repository") from exc
    return current


def _one(rows: Any, key: str, value: str) -> dict[str, Any]:
    if not isinstance(rows, list):
        raise BindingError("row collection missing")
    found = [row for row in rows if isinstance(row, dict) and row.get(key) == value]
    if len(found) != 1:
        raise BindingError("row identity is not unique")
    return found[0]


def _verify_locks(contract: dict[str, Any]) -> None:
    locks = contract.get("source_locks")
    if not isinstance(locks, list) or len(locks) != len(EXPECTED_LOCK_PATHS):
        raise BindingError("source-lock inventory is not exact")
    seen: set[str] = set()
    for lock in locks:
        if not isinstance(lock, dict) or set(lock) != {"path", "sha256"}:
            raise BindingError("invalid source lock")
        path = lock["path"]
        digest = lock["sha256"]
        if (
            not isinstance(path, str)
            or path in seen
            or not isinstance(digest, str)
            or len(digest) != 64
        ):
            raise BindingError("duplicate or invalid source lock")
        seen.add(path)
        if hashlib.sha256(_read(_path(path))).hexdigest() != digest:
            raise BindingError("source lock mismatch")
    if seen != EXPECTED_LOCK_PATHS:
        raise BindingError("source-lock path set drift")
    lock_map = {row["path"]: row["sha256"] for row in locks}
    for source_key in ("mapping_source", "advertised_source"):
        source = contract.get(source_key, {})
        if lock_map.get(source.get("path")) != source.get("sha256"):
            raise BindingError("primary source lock reference drift")


def _verify_nested_locks(package: dict[str, Any]) -> None:
    declarations: list[Any] = []
    for key in ("source_locks", "implementation_locks"):
        value = package.get(key, [])
        if not isinstance(value, list):
            raise BindingError("nested source-lock inventory invalid")
        declarations.extend(value)
    seen: set[str] = set()
    for lock in declarations:
        if not isinstance(lock, dict) or set(lock) != {"path", "sha256"}:
            raise BindingError("nested source lock invalid")
        path = lock.get("path")
        digest = lock.get("sha256")
        if not isinstance(path, str) or path in seen or not isinstance(digest, str):
            raise BindingError("nested source lock duplicate or invalid")
        seen.add(path)
        if hashlib.sha256(_read(_path(path))).hexdigest() != digest:
            raise BindingError("nested source lock mismatch")


def _verify_packages() -> None:
    base = _json(_path(f"{BASE_DIR}/contract.json"))
    lvs = _json(_path(f"{LVS_DIR}/contract.json"))
    lvs_predecessor = _json(_path(f"{LVS_PREDECESSOR_DIR}/contract.json"))
    search = _json(_path(f"{SEARCH_DIR}/contract.json"))
    search_executor = _json(_path(f"{SEARCH_EXECUTOR_DIR}/contract.json"))
    ui = _json(_path(f"{UI_DIR}/contract.json"))
    for package in (base, lvs, lvs_predecessor, search, search_executor, ui):
        _verify_nested_locks(package)

    if (
        base.get("package_id") != "base-semantic-owned-fixture-successor"
        or base.get("canonical_binding") is not False
        or base.get("promotion_eligible") is not False
        or base.get("warehouse_sample_bundle") != "excluded"
        or base.get("object_store", {}).get("require_empty_report_object_prestate")
        is not True
        or set(
            base.get("fixture", {})
            .get("report_semantics", {})
            .get("required_sections", [])
        )
        != {"## Summary", "## Visual Timeline", "## Findings"}
    ):
        raise BindingError("Base candidate boundary drift")
    unavoidable = lvs.get("semantic_coverage", {}).get("still_unavoidable", {})
    if (
        lvs.get("package_id") != "thor-vss-lvs-semantic-runtime-closure-successor-v1"
        or lvs.get("predecessor_package")
        != "thor-vss-lvs-semantic-runtime-agent-session-successor-v1"
        or lvs.get("warehouse_sample_bundle") != "excluded"
        or lvs.get("evidence", {}).get("executor_ready") is not False
        or lvs.get("evidence", {}).get("promotion_eligible") is not False
        or set(unavoidable)
        != {
            "ca-rag-answer-semantic-correlation",
            "disconnect-cancel-quiescence-live-receipt",
            "report-object-preexisting-absence",
            "complete-unrelated-agent-state-fingerprint",
            "exact-kafka-logstash-process-identity",
            "canonical-fourteen-request-bound",
        }
        or lvs_predecessor.get("package_id")
        != "thor-vss-lvs-semantic-runtime-agent-session-successor-v1"
        or lvs_predecessor.get("evidence", {}).get("executor_ready") is not False
    ):
        raise BindingError("LVS candidate boundary drift")
    if (
        search.get("package_id")
        != "search-semantic-exact-fixture-provisioner-successor"
        or search.get("warehouse_sample_bundle") != "excluded"
        or search.get("decision", {}).get(
            "safe_exact_full_fixture_creation_implemented"
        )
        is not True
        or search.get("decision", {}).get("runtime_receipt_present") is not False
        or search.get("decision", {}).get("promotion_eligible") is not False
        or search_executor.get("package_id")
        != "search-semantic-runtime-evidence-successor"
        or search_executor.get("evidence", {}).get("promotion_eligible") is not False
        or search_executor.get("evidence", {}).get("canonical_state_advanced")
        is not False
    ):
        raise BindingError("Search candidate boundary drift")
    canonical = ui.get("canonical_boundary", {})
    if (
        ui.get("package_id") != "thor-ui-video-management-playwright-successor-v1"
        or ui.get("warehouse_sample_bundle") != "excluded"
        or canonical.get("playwright_transitive_graph_pinned") is not True
        or ui.get("ownership", {}).get(
            "agent_delete_requires_exact_success_and_identity"
        )
        is not True
        or ui.get("ownership", {}).get("empty_vst_sensor_identity_preserved")
        is not True
        or ui.get("ownership", {}).get(
            "destructive_dialog_irreversible_warning_observed"
        )
        is not True
        or len(ui.get("source_locks", [])) != 22
        or canonical.get("canonical_bound") is not False
        or canonical.get("executor_ready") is not False
        or canonical.get("promotion_eligible") is not False
    ):
        raise BindingError("UI candidate boundary drift")


def _expected_references(expected: tuple[Any, ...]) -> list[dict[str, Any]]:
    return [
        {
            "package_id": package_id,
            "path": path,
            "role": role,
            "authorization_gated": True,
            "executor_ready": False,
        }
        for package_id, path, role in expected
    ]


def compile_overlay(contract_path: Path = CONTRACT) -> dict[str, Any]:
    contract = _json(contract_path)
    contract_errors = sorted(
        Draft202012Validator(_json(CONTRACT_SCHEMA)).iter_errors(contract),
        key=lambda error: list(error.path),
    )
    if contract_errors:
        raise BindingError(f"contract schema failure: {contract_errors[0].message}")
    if (
        contract.get("package_id")
        != "advertised-candidate-bindings-current-semantic-closure-successor"
        or contract.get("default_execution_enabled") is not False
        or contract.get("warehouse_sample_bundle") != "excluded"
        or contract.get("canonical_mapping_mutated") is not False
        or contract.get("runtime_evidence_inputs") != []
        or contract.get("admission_inputs") != []
    ):
        raise BindingError("contract boundary drift")
    _verify_locks(contract)
    _verify_packages()

    mapping = _json(_path(contract["mapping_source"]["path"]))
    advertised = _json(_path(contract["advertised_source"]["path"]))
    bindings = contract.get("bindings")
    if not isinstance(bindings, list) or len(bindings) != 10:
        raise BindingError("binding set is not exact-ten")
    ids = [row.get("capability_id") for row in bindings if isinstance(row, dict)]
    if len(ids) != 10 or len(set(ids)) != 10 or set(ids) != set(EXPECTED_BINDINGS):
        raise BindingError("binding identities are not exact and unique")

    rows: list[dict[str, Any]] = []
    for binding in bindings:
        capability_id = binding.get("capability_id")
        expected_state, expected_relationship, expected_refs = EXPECTED_BINDINGS[
            capability_id
        ]
        if (
            binding.get("implementation_state") != expected_state
            or binding.get("relationship_kind") != expected_relationship
            or binding.get("executor_ready") is not False
            or binding.get("executor_references") != _expected_references(expected_refs)
            or binding.get("coverage_status") != "incomplete_no_live_receipt"
        ):
            raise BindingError("candidate classification drift")
        mapped = _one(mapping.get("mappings"), "capability_id", capability_id)
        matches = [
            candidate
            for candidate in advertised.get("entries", [])
            if isinstance(candidate, dict)
            and isinstance(candidate.get("proposed_capability"), dict)
            and candidate["proposed_capability"].get("id") == capability_id
        ]
        if len(matches) != 1:
            raise BindingError("advertised entry identity is not unique")
        entry = matches[0]
        proposed = entry["proposed_capability"]
        if (
            mapped.get("binding_kind") != "none"
            or mapped.get("approval_state") != "no_receipt_not_admitted_not_executable"
            or mapped.get("required_cloud_inference") is not False
            or mapped.get("warehouse_sample_bundle") is not False
            or proposed.get("runtime_state") != "not_qualified"
            or not isinstance(binding.get("retained_gaps"), list)
            or not binding["retained_gaps"]
        ):
            raise BindingError("canonical candidate boundary drift")
        canonical_effect = {
            "admitted": False,
            "binding_kind_changed": False,
            "executable": False,
            "promoted": False,
            "runtime_evidence": [],
        }
        if binding.get("canonical_effect") != canonical_effect:
            raise BindingError("canonical no-effect boundary drift")
        rows.append(
            {
                "capability_id": capability_id,
                "oracle_id": mapped.get("oracle_id"),
                "oracle_index": mapped.get("oracle_index"),
                "candidate_record_canonical_sha256": mapped.get(
                    "candidate_record_canonical_sha256"
                ),
                "advertised_literal": entry.get("advertised"),
                "required_semantics": proposed.get("contract", {}).get(
                    "required_semantics"
                ),
                "adjacent_negative": entry.get("oracle_plan", {}).get(
                    "adjacent_negative"
                ),
                "required_cloud_inference": False,
                "warehouse_sample_bundle": False,
                "implementation_state": binding["implementation_state"],
                "relationship_kind": binding["relationship_kind"],
                "executor_ready": False,
                "executor_references": binding["executor_references"],
                "coverage_status": binding["coverage_status"],
                "retained_gaps": binding["retained_gaps"],
                "canonical_effect": canonical_effect,
            }
        )

    concrete = sum(row["implementation_state"] == "concrete" for row in rows)
    partial = sum(row["implementation_state"] == "partial" for row in rows)
    if concrete != 3 or partial != 7:
        raise BindingError("implementation classification split drift")
    result = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "status": "current_semantic_candidate_links_verified_non_promoting",
        "default_execution_enabled": False,
        "warehouse_sample_bundle": "excluded",
        "canonical_mapping_mutated": False,
        "rows": rows,
        "summary": {
            "row_count": 10,
            "concrete_implementation_count": concrete,
            "partial_implementation_count": partial,
            "executor_ready_count": 0,
            "required_cloud_inference_count": 0,
            "warehouse_sample_dependency_count": 0,
            "concrete_full_binding_count": 0,
            "canonical_binding_change_count": 0,
            "admitted_count": 0,
            "executable_count": 0,
            "runtime_receipt_count": 0,
            "promotion_count": 0,
        },
    }
    errors = sorted(
        Draft202012Validator(_json(SCHEMA)).iter_errors(result),
        key=lambda error: list(error.path),
    )
    if errors:
        raise BindingError(f"compiled overlay schema failure: {errors[0].message}")
    return result


def _canonical(value: dict[str, Any]) -> str:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", choices=("compile", "check"), nargs="?", default="check"
    )
    args = parser.parse_args(argv)
    try:
        result = compile_overlay()
        rendered = _canonical(result)
        if args.command == "compile":
            sys.stdout.write(rendered)
        else:
            if _read(ARTIFACT) != rendered.encode("utf-8"):
                raise BindingError("checked-in overlay is stale")
            print(
                "PASS: current semantic candidate links verified "
                "(3 concrete, 7 partial, 0 ready/admitted/evidenced/promoted)"
            )
        return 0
    except BindingError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
