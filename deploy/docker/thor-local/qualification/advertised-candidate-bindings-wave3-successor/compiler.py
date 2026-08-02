#!/usr/bin/env python3
"""Compile the inert advertised-entry candidate binding overlay."""

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
SCHEMA = HERE / "binding-overlay.schema.json"
ARTIFACT = HERE / "binding-overlay.json"
MAX_BYTES = 32 * 1024 * 1024

EXPECTED_LOCK_PATHS = {
    "deploy/docker/thor-local/qualification/candidate-approval-mapping-rebase-successor-v2/mapping.json",
    "deploy/docker/thor-local/qualification/remaining-advertised-entry-candidates/candidate.json",
    "deploy/docker/thor-local/qualification/semantic-executor-bindings-wave2-successor/execution-status-registry.json",
    "deploy/docker/thor-local/qualification/base-semantic-full-envelope-successor/contract.json",
    "deploy/docker/thor-local/qualification/base-semantic-full-envelope-successor/executor.py",
    "deploy/docker/thor-local/qualification/lvs-semantic-runtime-agent-session-successor/contract.json",
    "deploy/docker/thor-local/qualification/lvs-semantic-runtime-agent-session-successor/executor.py",
    "deploy/docker/thor-local/qualification/search-semantic-fixture-provisioning-blocker-successor/contract.json",
    "deploy/docker/thor-local/qualification/search-semantic-fixture-provisioning-blocker-successor/compiler.py",
    "deploy/docker/thor-local/qualification/ui-video-management-playwright-successor/contract.json",
    "deploy/docker/thor-local/qualification/ui-video-management-playwright-successor/executor.py",
    "deploy/docker/thor-local/qualification/ui-video-management-playwright-successor/harness.mjs",
}

BASE_EXECUTOR = (
    "base-semantic-full-envelope-successor",
    "deploy/docker/thor-local/qualification/base-semantic-full-envelope-successor/executor.py",
)
LVS_EXECUTOR = (
    "thor-vss-lvs-semantic-runtime-agent-session-successor-v1",
    "deploy/docker/thor-local/qualification/lvs-semantic-runtime-agent-session-successor/executor.py",
)
UI_EXECUTOR = (
    "thor-ui-video-management-playwright-successor-v1",
    "deploy/docker/thor-local/qualification/ui-video-management-playwright-successor/executor.py",
)
SEARCH_BLOCKER = ("search-semantic-fixture-provisioning-blocker-successor", None)
EXPECTED_BINDINGS = {
    "manifest-entry.base-agent-workflow.01-visual-question-answering": (
        "partial",
        "partial_executor_candidate",
        *BASE_EXECUTOR,
    ),
    "manifest-entry.base-agent-workflow.02-vlm-report-generation": (
        "partial",
        "partial_executor_candidate",
        *BASE_EXECUTOR,
    ),
    "manifest-entry.video-summarization-file.02-multi-video-report": (
        "partial",
        "partial_executor_candidate",
        *LVS_EXECUTOR,
    ),
    "manifest-entry.video-summarization-file.04-object-event-scenario-focus": (
        "partial",
        "partial_executor_candidate",
        *LVS_EXECUTOR,
    ),
    "manifest-entry.semantic-search.00-natural-language-action-event-search": (
        "blocker",
        "static_blocker_link",
        *SEARCH_BLOCKER,
    ),
    "manifest-entry.semantic-search.01-cv-attribute-search": (
        "blocker",
        "static_blocker_link",
        *SEARCH_BLOCKER,
    ),
    "manifest-entry.semantic-search.02-multi-embedding-fusion": (
        "blocker",
        "static_blocker_link",
        *SEARCH_BLOCKER,
    ),
    "manifest-entry.semantic-search.03-search-by-image": (
        "blocker",
        "static_blocker_link",
        *SEARCH_BLOCKER,
    ),
    "manifest-entry.semantic-search.07-file-and-rtsp-archive-management": (
        "blocker",
        "static_blocker_link",
        *SEARCH_BLOCKER,
    ),
    "manifest-entry.main-ui.05-chunked-upload-and-rtsp-management": (
        "partial",
        "partial_executor_candidate",
        *UI_EXECUTOR,
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
        raw = b""
        while len(raw) <= MAX_BYTES:
            chunk = os.read(descriptor, min(131072, MAX_BYTES + 1 - len(raw)))
            if not chunk:
                break
            raw += chunk
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
    if not isinstance(locks, list) or len(locks) != 12:
        raise BindingError("source-lock inventory is not exact")
    seen: set[str] = set()
    for lock in locks:
        if not isinstance(lock, dict) or set(lock) != {"path", "sha256"}:
            raise BindingError("invalid source lock")
        path = lock["path"]
        digest = lock["sha256"]
        if not isinstance(path, str) or path in seen or not isinstance(digest, str):
            raise BindingError("duplicate or invalid source lock")
        seen.add(path)
        if hashlib.sha256(_read(_path(path))).hexdigest() != digest:
            raise BindingError("source lock mismatch")
    if seen != EXPECTED_LOCK_PATHS:
        raise BindingError("source-lock path set drift")
    lock_map = {lock["path"]: lock["sha256"] for lock in locks}
    for source_key in ("mapping_source", "advertised_source"):
        source = contract.get(source_key, {})
        if lock_map.get(source.get("path")) != source.get("sha256"):
            raise BindingError("primary source lock reference drift")


def _verify_packages() -> None:
    wave2 = _json(
        _path(
            "deploy/docker/thor-local/qualification/semantic-executor-bindings-wave2-successor/execution-status-registry.json"
        )
    )
    if (
        wave2.get("status") != "wave2_candidate_status_verified_non_promoting"
        or wave2.get("summary", {}).get("wave2_canonical_binding_count") != 0
        or wave2.get("summary", {}).get("wave2_runtime_receipt_count") != 0
        or wave2.get("summary", {}).get("wave2_promotion_count") != 0
    ):
        raise BindingError("wave-2 non-promotion boundary drift")

    base = _json(
        _path(
            "deploy/docker/thor-local/qualification/base-semantic-full-envelope-successor/contract.json"
        )
    )
    lvs = _json(
        _path(
            "deploy/docker/thor-local/qualification/lvs-semantic-runtime-agent-session-successor/contract.json"
        )
    )
    search = _json(
        _path(
            "deploy/docker/thor-local/qualification/search-semantic-fixture-provisioning-blocker-successor/contract.json"
        )
    )
    ui = _json(
        _path(
            "deploy/docker/thor-local/qualification/ui-video-management-playwright-successor/contract.json"
        )
    )
    if (
        base.get("canonical_binding") is not False
        or base.get("promotion_eligible") is not False
        or base.get("ownership", {}).get("preexisting_absence_proven") is not False
        or lvs.get("evidence", {}).get("executor_ready") is not False
        or lvs.get("evidence", {}).get("promotion_eligible") is not False
        or search.get("runtime_transport_implemented") is not False
        or search.get("decision", {}).get("safe_exact_full_fixture_creation_proven")
        is not False
        or search.get("decision", {}).get("predecessor_executor_binding_permitted")
        is not False
        or ui.get("canonical_boundary", {}).get("canonical_bound") is not False
        or ui.get("canonical_boundary", {}).get("promotion_eligible") is not False
    ):
        raise BindingError("candidate package boundary drift")


def compile_overlay(contract_path: Path = CONTRACT) -> dict[str, Any]:
    contract = _json(contract_path)
    if (
        contract.get("package_id") != "advertised-candidate-bindings-wave3-successor"
        or contract.get("default_execution_enabled") is not False
        or contract.get("warehouse_sample_bundle") != "excluded"
        or contract.get("canonical_mapping_mutated") is not False
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
    if len(set(ids)) != 10 or set(ids) != set(EXPECTED_BINDINGS):
        raise BindingError("binding identities are not unique")

    rows: list[dict[str, Any]] = []
    for binding in bindings:
        capability_id = binding.get("capability_id")
        mapped = _one(mapping.get("mappings"), "capability_id", capability_id)
        # Nested identity lookup is intentionally explicit rather than accepting a
        # broad feature-family match.
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
        expected = EXPECTED_BINDINGS[capability_id]
        executor = binding.get("executor_reference")
        executor_path = executor.get("path") if isinstance(executor, dict) else None
        if (
            binding.get("binding_strength"),
            binding.get("relationship_kind"),
            binding.get("source_package_id"),
            executor_path,
        ) != expected:
            raise BindingError("binding relationship drift")
        if (
            mapped.get("oracle_index") != binding.get("oracle_index")
            or mapped.get("oracle_id") != binding.get("oracle_id")
            or mapped.get("candidate_record_canonical_sha256")
            != binding.get("candidate_record_canonical_sha256")
            or mapped.get("binding_kind") != "none"
            or mapped.get("approval_state") != "no_receipt_not_admitted_not_executable"
            or mapped.get("required_cloud_inference") is not False
            or mapped.get("warehouse_sample_bundle") is not False
            or entry.get("advertised") != binding.get("advertised_literal")
            or proposed.get("runtime_state") != "not_qualified"
            or proposed.get("contract", {}).get("required_semantics")
            != binding.get("required_semantics")
            or entry.get("oracle_plan", {}).get("adjacent_negative")
            != [binding.get("adjacent_negative")]
        ):
            raise BindingError("candidate mapping or advertised contract drift")
        rows.append(binding)

    strengths = [row["binding_strength"] for row in rows]
    if strengths.count("partial") != 5 or strengths.count("blocker") != 5:
        raise BindingError("binding-strength split drift")
    if any(
        row.get("canonical_effect")
        != {
            "admitted": False,
            "binding_kind_changed": False,
            "executable": False,
            "promoted": False,
            "runtime_evidence": [],
        }
        for row in rows
    ):
        raise BindingError("canonical no-effect boundary drift")
    if any(
        row["executor_reference"] is not None
        for row in rows
        if row["binding_strength"] == "blocker"
    ):
        raise BindingError("blocker row cannot reference an executor")

    result = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "status": "advertised_candidate_links_verified_non_promoting",
        "default_execution_enabled": False,
        "warehouse_sample_bundle": "excluded",
        "canonical_mapping_mutated": False,
        "rows": rows,
        "summary": {
            "row_count": 10,
            "partial_executor_link_count": 5,
            "static_blocker_link_count": 5,
            "concrete_full_binding_count": 0,
            "canonical_binding_change_count": 0,
            "admitted_count": 0,
            "executable_count": 0,
            "runtime_receipt_count": 0,
            "promotion_count": 0,
        },
    }
    errors = sorted(Draft202012Validator(_json(SCHEMA)).iter_errors(result), key=str)
    if errors:
        raise BindingError("compiled overlay violates schema")
    return result


def _canonical(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("compile", "check"))
    args = parser.parse_args(argv)
    try:
        rendered = _canonical(compile_overlay())
        if args.mode == "check":
            if _read(ARTIFACT).decode("utf-8") != rendered:
                raise BindingError("checked overlay drift")
        else:
            sys.stdout.write(rendered)
    except BindingError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
