#!/usr/bin/env python3
"""Audit the immutable selected Metadata-500 set against current local overlays."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from typing import Any


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4].resolve(strict=True)
CONTRACT_PATH = HERE / "contract.json"
MAX_BYTES = 96_000_000

SELECTED_SET = "thor-vss-3.2.1-current-cancellation-search-500"
SELECTOR = "deploy/docker/thor-local/parity/metadata_sets/selector.json"
DESCRIPTOR = (
    "deploy/docker/thor-local/parity/metadata_sets/sets/"
    "thor-vss-3.2.1-current-cancellation-search-500.json"
)
LEDGER = (
    "deploy/docker/thor-local/qualification/"
    "metadata-500-current-cancellation-search-successor/"
    "post-state-official-capabilities.json"
)
ORACLES = (
    "deploy/docker/thor-local/qualification/"
    "metadata-500-current-cancellation-search-successor/"
    "post-state-capability-oracles.json"
)
METADATA_COMPILER = (
    "deploy/docker/thor-local/qualification/"
    "metadata-500-current-cancellation-search-successor/compiler.py"
)
METADATA_SCHEMAS = {
    "deploy/docker/thor-local/parity/metadata_sets/selector.schema.json",
    "deploy/docker/thor-local/parity/metadata_sets/metadata-set.schema.json",
    "deploy/docker/thor-local/parity/official-capabilities.schema.json",
    "deploy/docker/thor-local/qualification/live-metadata-500-migration-rebase-successor/"
    "post-state-capability-oracles.schema.json",
}
REBASE_CONTRACT = (
    "deploy/docker/thor-local/qualification/"
    "advertised-entry-executors-71-current-source-rebase-successor/contract.json"
)
REBASE_VALIDATOR = (
    "deploy/docker/thor-local/qualification/"
    "advertised-entry-executors-71-current-source-rebase-successor/validator.py"
)
BINDING_DIR = (
    "deploy/docker/thor-local/qualification/"
    "advertised-candidate-bindings-current-semantic-closure-successor"
)
BINDING_CONTRACT = f"{BINDING_DIR}/contract.json"
BINDING_COMPILER = f"{BINDING_DIR}/compiler.py"
BINDING_CONTRACT_SCHEMA = f"{BINDING_DIR}/contract.schema.json"
BINDING_OVERLAY_SCHEMA = f"{BINDING_DIR}/binding-overlay.schema.json"
BINDING_ARTIFACT = f"{BINDING_DIR}/binding-overlay.json"

EXPECTED_CHANGED_ROWS = {
    "services/agent/src/vss_agents/api/custom_fastapi_worker.py": {
        "metadata": {"manifest-entry.agent-and-mcp-apis.00-nat-generate-chat"},
        "rebase": {
            "manifest-gap.agent-and-mcp-apis.00-nat-generate-chat",
            "manifest-gap.agent-and-mcp-apis.01-health",
            "manifest-gap.agent-and-mcp-apis.02-upload-handshake-and-completion",
            "manifest-gap.agent-and-mcp-apis.03-video-delete",
            "manifest-gap.agent-and-mcp-apis.04-rtsp-add-delete",
        },
    },
    "services/agent/src/vss_agents/api/video_delete.py": {
        "metadata": {
            "manifest-entry.agent-and-mcp-apis.03-video-delete",
            "manifest-entry.semantic-search.07-file-and-rtsp-archive-management",
        },
        "rebase": {"manifest-gap.agent-and-mcp-apis.03-video-delete"},
    },
    "services/agent/src/vss_agents/api/video_ingest.py": {
        "metadata": {
            "manifest-entry.agent-and-mcp-apis.02-upload-handshake-and-completion",
            "manifest-entry.base-agent-workflow.00-short-video-retrieval",
            "manifest-entry.base-agent-workflow.04-large-file-chunked-upload",
        },
        "rebase": {
            "manifest-gap.agent-and-mcp-apis.02-upload-handshake-and-completion"
        },
    },
    "services/agent/src/vss_agents/api/rtsp_ingest.py": {
        "metadata": {
            "manifest-entry.semantic-search.07-file-and-rtsp-archive-management",
            "manifest-entry.agent-and-mcp-apis.04-rtsp-add-delete",
        },
        "rebase": {"manifest-gap.agent-and-mcp-apis.04-rtsp-add-delete"},
    },
    "services/agent/src/vss_agents/api/rtsp_delete.py": {
        "metadata": {"manifest-entry.agent-and-mcp-apis.04-rtsp-add-delete"},
        "rebase": {"manifest-gap.agent-and-mcp-apis.04-rtsp-add-delete"},
    },
    "services/agent/src/vss_agents/api/video_search_ingest.py": {
        "metadata": {
            "manifest-entry.semantic-search.07-file-and-rtsp-archive-management"
        },
        "rebase": set(),
    },
    "services/agent/src/vss_agents/tools/vst/utils.py": {
        "metadata": set(),
        "rebase": set(),
    },
}
EXPECTED_SUCCESSORS = {
    "base": {
        "package_id": "base-semantic-owned-fixture-successor",
        "capabilities": {
            "runtime.workflow.base-chat-report",
            "runtime.agent.base-hitl",
        },
    },
    "lvs": {
        "package_id": "thor-vss-lvs-semantic-runtime-closure-successor-v1",
        "capabilities": {"runtime.agent.lvs-profile"},
    },
    "search": {
        "package_id": "search-semantic-exact-fixture-provisioner-successor",
        "capabilities": {"runtime.agent.search-profile"},
    },
    "ui": {
        "package_id": "thor-ui-video-management-playwright-successor-v1",
        "capabilities": {"runtime.ui.video-management-tab"},
    },
}
EXPECTED_METADATA_INDICES = {
    "manifest-entry.base-agent-workflow.00-short-video-retrieval": 289,
    "manifest-entry.base-agent-workflow.04-large-file-chunked-upload": 293,
    "manifest-entry.semantic-search.07-file-and-rtsp-archive-management": 318,
    "manifest-entry.agent-and-mcp-apis.00-nat-generate-chat": 462,
    "manifest-entry.agent-and-mcp-apis.02-upload-handshake-and-completion": 464,
    "manifest-entry.agent-and-mcp-apis.03-video-delete": 465,
    "manifest-entry.agent-and-mcp-apis.04-rtsp-add-delete": 466,
}
EXPECTED_RUNTIME_INDICES = {
    "runtime.workflow.base-chat-report": 162,
    "runtime.agent.base-hitl": 163,
    "runtime.agent.lvs-profile": 164,
    "runtime.agent.search-profile": 165,
    "runtime.ui.video-management-tab": 172,
}
EXPECTED_BINDING_INDICES = {
    "manifest-entry.base-agent-workflow.01-visual-question-answering": 290,
    "manifest-entry.base-agent-workflow.02-vlm-report-generation": 291,
    "manifest-entry.video-summarization-file.02-multi-video-report": 298,
    "manifest-entry.video-summarization-file.04-object-event-scenario-focus": 300,
    "manifest-entry.semantic-search.00-natural-language-action-event-search": 311,
    "manifest-entry.semantic-search.01-cv-attribute-search": 312,
    "manifest-entry.semantic-search.02-multi-embedding-fusion": 313,
    "manifest-entry.semantic-search.03-search-by-image": 314,
    "manifest-entry.semantic-search.07-file-and-rtsp-archive-management": 318,
    "manifest-entry.main-ui.05-chunked-upload-and-rtsp-management": 440,
}
EXPECTED_POLICY = {
    "static_only": True,
    "default_execution_enabled": False,
    "runtime_evidence": [],
    "canonical_binding_changed": False,
    "canonical_runtime_state_advanced": False,
    "promotion_eligible": False,
    "selector_mutated": False,
    "warehouse_sample_bundle": "excluded",
}


class AuditError(RuntimeError):
    """An identity, semantic-boundary, or non-promotion invariant failed."""


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _strict_json(payload: bytes, label: str) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise AuditError(f"duplicate JSON key in {label}: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> Any:
        raise AuditError(f"non-finite JSON constant in {label}: {value}")

    if len(payload) > MAX_BYTES:
        raise AuditError(f"oversized JSON input: {label}")
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditError(f"invalid JSON input: {label}") from exc
    if not isinstance(value, dict):
        raise AuditError(f"JSON root is not an object: {label}")
    return value


def _repo_file(relative: str, *, repo_root: Path = REPO_ROOT) -> Path:
    pure = PurePosixPath(relative)
    if (
        pure.is_absolute()
        or not pure.parts
        or pure.as_posix() != relative
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise AuditError(f"unsafe repository path: {relative}")
    path = repo_root
    for index, part in enumerate(pure.parts):
        path /= part
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise AuditError(f"repository input unavailable: {relative}") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise AuditError(f"repository path contains a symlink: {relative}")
        if index < len(pure.parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
            raise AuditError(f"repository parent is not a directory: {relative}")
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_BYTES:
        raise AuditError(f"repository input is not a bounded regular file: {relative}")
    return path


def _read(relative: str, *, repo_root: Path = REPO_ROOT) -> bytes:
    path = _repo_file(relative, repo_root=repo_root)
    before = path.stat(follow_symlinks=False)
    payload = path.read_bytes()
    after = path.stat(follow_symlinks=False)
    identity = lambda row: (  # noqa: E731 - compact immutable identity tuple
        row.st_dev,
        row.st_ino,
        row.st_size,
        row.st_mtime_ns,
    )
    if identity(before) != identity(after) or len(payload) != before.st_size:
        raise AuditError(f"repository input changed while reading: {relative}")
    return payload


def _load_module(relative: str, name: str) -> Any:
    path = _repo_file(relative)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AuditError(f"cannot load static validator: {relative}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _source_locks(contract: dict[str, Any]) -> dict[str, str]:
    rows = contract.get("source_locks")
    if not isinstance(rows, list) or not rows:
        raise AuditError("source locks are missing")
    result: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"path", "sha256"}:
            raise AuditError("malformed source lock")
        path, digest = row["path"], row["sha256"]
        if (
            not isinstance(path, str)
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or path in result
        ):
            raise AuditError("duplicate or malformed source lock")
        if _sha(_read(path)) != digest:
            raise AuditError(f"source lock drift: {path}")
        result[path] = digest
    return result


def _authoritative_report() -> dict[str, Any]:
    parity = REPO_ROOT / "deploy/docker/thor-local/parity"
    inserted = str(parity) not in sys.path
    if inserted:
        sys.path.insert(0, str(parity))
    try:
        module = _load_module(
            "deploy/docker/thor-local/parity/verify_metadata_set.py",
            "metadata500_overlay_authoritative_verifier",
        )
        return module.verify_metadata_set()
    finally:
        if inserted:
            sys.path.remove(str(parity))


def _validate_metadata_boundary(
    contract: dict[str, Any], locks: dict[str, str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    boundary = contract.get("metadata_boundary")
    if boundary != {
        "selected_set": SELECTED_SET,
        "capabilities": 500,
        "oracles": 500,
        "feature_families": 55,
        "candidate_suffix_start": 289,
        "candidate_rows": 211,
        "local_python_hashes_are_metadata_source_claims": False,
        "source_claims_are_official_provenance": True,
        "canonical_documents_mutated": False,
    }:
        raise AuditError("metadata boundary contract drift")

    selector = _strict_json(_read(SELECTOR), SELECTOR)
    if selector.get("selected_set") != SELECTED_SET:
        raise AuditError("canonical selector no longer selects current Metadata-500")
    selected_rows = [
        row
        for row in selector.get("available_sets", [])
        if row.get("set_id") == SELECTED_SET
    ]
    if len(selected_rows) != 1 or selected_rows[0] != {
        "set_id": SELECTED_SET,
        "descriptor_path": DESCRIPTOR,
        "descriptor_raw_sha256": locks[DESCRIPTOR],
    }:
        raise AuditError("selected descriptor registry identity drift")

    descriptor = _strict_json(_read(DESCRIPTOR), DESCRIPTOR)
    if (
        descriptor.get("set_id") != SELECTED_SET
        or descriptor.get("lifecycle") != "live_ready"
        or descriptor.get("expected_counts")
        != {"capabilities": 500, "oracles": 500, "feature_families": 55}
        or descriptor.get("documents", {}).get("official_capabilities")
        != {
            "path": LEDGER,
            "raw_sha256": locks[LEDGER],
            "schema_version": 1,
            "schema_id": "official_capabilities_schema",
        }
        or descriptor.get("documents", {}).get("capability_oracles")
        != {
            "path": ORACLES,
            "raw_sha256": locks[ORACLES],
            "schema_version": 2,
            "schema_id": "capability_oracles_schema",
        }
    ):
        raise AuditError("selected Metadata-500 descriptor semantics drift")

    report = _authoritative_report()
    if (
        report.get("set_id") != SELECTED_SET
        or report.get("descriptor_raw_sha256") != locks[DESCRIPTOR]
        or report.get("counts")
        != {"capabilities": 500, "oracles": 500, "feature_families": 55}
        or report.get("official_validator_counts")
        != {
            "capabilities": 500,
            "discrepancies": 47,
            "feature_families": 55,
            "sources": 126,
        }
        or report.get("oracle_validator_counts")
        != {
            "candidate_evidence": 0,
            "candidate_executor_ready": 0,
            "candidate_protocol_bindings": 23,
            "candidate_workload_bindings": 60,
            "candidates": 211,
            "capabilities": 500,
            "oracles": 500,
            "preserved_v1": 289,
        }
    ):
        raise AuditError("authoritative selected Metadata-500 report drift")

    compiler = _load_module(METADATA_COMPILER, "metadata500_overlay_selected_compiler")
    if compiler.check() != {
        "available_sets": 2,
        "capabilities": 500,
        "candidate_evidence": 0,
        "candidate_executor_ready": 0,
        "candidates": 211,
        "collectors": 0,
        "discrepancies": 47,
        "executors": 0,
        "external_boundary_unexecuted": 36,
        "historical_admissions": 0,
        "historical_artifacts_locked": 5,
        "historical_authorities": 0,
        "historical_candidate_ids_aligned": 211,
        "open_unexecuted": 464,
        "oracles": 500,
        "promotable": 0,
        "runtime_evidence": 0,
        "selected_set": SELECTED_SET,
        "sources": 126,
    }:
        raise AuditError("selected Metadata-500 compiler report drift")
    return _strict_json(_read(LEDGER), LEDGER), _strict_json(_read(ORACLES), ORACLES)


def _validate_changed_sources(
    contract: dict[str, Any], ledger: dict[str, Any], oracles: dict[str, Any]
) -> None:
    rows = contract.get("changed_agent_sources")
    if not isinstance(rows, list) or len(rows) != 7:
        raise AuditError("changed Agent source denominator drift")
    declared: dict[str, dict[str, set[str]]] = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
            "path",
            "metadata_capability_ids",
            "current_source_rebase_entry_ids",
        }:
            raise AuditError("changed Agent source row malformed")
        path = row["path"]
        declared[path] = {
            "metadata": set(row["metadata_capability_ids"]),
            "rebase": set(row["current_source_rebase_entry_ids"]),
        }
    if declared != EXPECTED_CHANGED_ROWS:
        raise AuditError("changed Agent source-to-row mapping drift")

    capabilities = ledger.get("capabilities")
    oracle_rows = oracles.get("oracles")
    if not isinstance(capabilities, list) or not isinstance(oracle_rows, list):
        raise AuditError("selected metadata rows missing")
    if len(capabilities) != 500 or len(oracle_rows) != 500:
        raise AuditError("selected metadata denominator drift")
    by_oracle = {
        row.get("capability_id"): (index, row) for index, row in enumerate(oracle_rows)
    }
    if len(by_oracle) != 500:
        raise AuditError("selected oracle identity drift")

    for path, expected in EXPECTED_CHANGED_ROWS.items():
        observed = {
            row.get("id")
            for row in capabilities
            if path in json.dumps(row, ensure_ascii=True, sort_keys=True)
        }
        if observed != expected["metadata"]:
            raise AuditError(f"selected metadata source-impact drift: {path}")
        for capability_id in observed:
            index, oracle = by_oracle[capability_id]
            capability = capabilities[index]
            if (
                index != EXPECTED_METADATA_INDICES[capability_id]
                or capability.get("id") != capability_id
                or capability.get("runtime_state") != "not_qualified"
                or oracle.get("current_state") != "open_unexecuted"
                or oracle.get("runtime_state") != "not_qualified"
                or oracle.get("evidence") != []
                or oracle.get("execution_bounds", {}).get("executor") is not None
                or oracle.get("can_promote_runtime_state") is not False
            ):
                raise AuditError(
                    f"changed-source row was promoted without evidence: {capability_id}"
                )

    tagged = [
        row
        for row in ledger.get("sources", [])
        if row.get("id") == "tagged-repository-3.2.1"
    ]
    if len(tagged) != 1 or {
        key: tagged[0].get(key) for key in ("kind", "uri", "version")
    } != {
        "kind": "tagged_repository",
        "uri": "https://github.com/NVIDIA-AI-Blueprints/video-search-and-summarization/tree/v3.2.1",
        "version": "7640d917047cf7b0fd3085eefb8282754b56bc94",
    }:
        raise AuditError("official tagged-repository provenance drift")
    if any(key in tagged[0] for key in ("path", "raw_sha256", "sha256")):
        raise AuditError("official provenance was conflated with local source bytes")


def _validate_current_source_rebase(contract: dict[str, Any]) -> None:
    expected = {
        "contract_path": REBASE_CONTRACT,
        "validator_path": REBASE_VALIDATOR,
        "retained_candidate_rows": 71,
        "unchanged_rows": 40,
        "rebased_rows": 31,
        "overlay_paths": 14,
        "source_lock_references": 182,
    }
    if contract.get("current_source_rebase") != expected:
        raise AuditError("current-source rebase contract drift")
    module = _load_module(REBASE_VALIDATOR, "metadata500_overlay_source_rebase")
    report = module.validate()
    if {
        key: report.get(key)
        for key in (
            "retained_candidate_rows",
            "unchanged_rows",
            "rebased_rows",
            "current_source_overlay_paths",
            "current_source_lock_references",
        )
    } != {
        "retained_candidate_rows": 71,
        "unchanged_rows": 40,
        "rebased_rows": 31,
        "current_source_overlay_paths": 14,
        "current_source_lock_references": 182,
    } or any(
        (
            report.get("runtime_evidence") != [],
            report.get("can_mark_passed_current") is not False,
            report.get("official_capability_effect") != "none_candidate_only",
        )
    ):
        raise AuditError("current-source rebase validation drift")

    source_contract = _strict_json(_read(REBASE_CONTRACT), REBASE_CONTRACT)
    overlay = {
        row.get("path"): row.get("sha256")
        for row in source_contract.get("current_source_overlay", [])
    }
    for path, expected in EXPECTED_CHANGED_ROWS.items():
        if expected["rebase"]:
            if overlay.get(path) != _sha(_read(path)):
                raise AuditError(
                    f"changed Agent source is absent from current overlay: {path}"
                )
        elif path in overlay:
            raise AuditError(
                f"unreferenced Agent source entered current overlay: {path}"
            )

    predecessor = source_contract["immutable_predecessor"]
    inventory = _strict_json(
        _read(predecessor["inventory_path"]), predecessor["inventory_path"]
    )
    historical_cases: dict[str, dict[str, Any]] = {}
    for wave in inventory["historical_waves"]:
        wave_inventory = _strict_json(
            _read(wave["inventory_path"]), wave["inventory_path"]
        )
        for case in wave_inventory["cases"]:
            historical_cases[case["entry_id"]] = case
    for path, expected in EXPECTED_CHANGED_ROWS.items():
        observed = {
            row["entry_id"]
            for row in inventory["rows"]
            if row.get("disposition") == "candidate"
            and any(
                lock.get("path") == path
                for lock in historical_cases[row["entry_id"]]["source_locks"]
            )
        }
        if observed != expected["rebase"]:
            raise AuditError(f"current-source rebase row-impact drift: {path}")


def _validate_runtime_successors(
    contract: dict[str, Any], oracles: dict[str, Any], locks: dict[str, str]
) -> None:
    rows = contract.get("runtime_successors")
    if not isinstance(rows, list) or len(rows) != 4:
        raise AuditError("runtime successor denominator drift")
    declared: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
            "name",
            "package_id",
            "contract_path",
            "implementation_paths",
            "canonical_capability_ids",
        }:
            raise AuditError("runtime successor row malformed")
        name = row["name"]
        if name in declared:
            raise AuditError("duplicate runtime successor name")
        declared[name] = row
    if set(declared) != set(EXPECTED_SUCCESSORS):
        raise AuditError("runtime successor identity drift")

    by_oracle = {
        row.get("capability_id"): (index, row)
        for index, row in enumerate(oracles["oracles"])
    }
    for name, expected in EXPECTED_SUCCESSORS.items():
        row = declared[name]
        if (
            row["package_id"] != expected["package_id"]
            or set(row["canonical_capability_ids"]) != expected["capabilities"]
            or row["contract_path"] not in locks
            or any(path not in locks for path in row["implementation_paths"])
        ):
            raise AuditError(f"runtime successor binding drift: {name}")
        successor = _strict_json(_read(row["contract_path"]), row["contract_path"])
        if successor.get("package_id") != expected["package_id"]:
            raise AuditError(f"runtime successor package id drift: {name}")
        for capability_id in expected["capabilities"]:
            indexed = by_oracle.get(capability_id)
            if not isinstance(indexed, tuple) or len(indexed) != 2:
                raise AuditError(f"canonical runtime row missing: {capability_id}")
            index, oracle = indexed
            if (
                index != EXPECTED_RUNTIME_INDICES[capability_id]
                or oracle.get("current_state") != "open_unexecuted"
                or oracle.get("evidence") != []
                or oracle.get("execution_bounds", {}).get("executor") is not None
            ):
                raise AuditError(
                    f"canonical runtime row advanced without receipt: {capability_id}"
                )

        if name == "base" and not (
            successor.get("canonical_binding") is False
            and successor.get("promotion_eligible") is False
            and isinstance(
                successor.get("authorization", {}).get("acknowledgement"), str
            )
        ):
            raise AuditError("Base successor non-promotion boundary drift")
        if name == "lvs" and successor.get("evidence") != {
            "records_raw_payloads": False,
            "records_raw_urls": False,
            "records_raw_resource_ids": False,
            "records_response_size_and_sha256": True,
            "promotion_eligible": False,
            "executor_ready": False,
            "canonical_state_advanced": False,
        }:
            raise AuditError("LVS successor non-promotion boundary drift")
        if name == "search" and {
            key: successor.get("decision", {}).get(key)
            for key in (
                "runtime_receipt_present",
                "promotion_eligible",
                "canonical_state_advanced",
            )
        } != {
            "runtime_receipt_present": False,
            "promotion_eligible": False,
            "canonical_state_advanced": False,
        }:
            raise AuditError("Search successor non-promotion boundary drift")
        if name == "ui" and {
            key: successor.get("canonical_boundary", {}).get(key)
            for key in ("canonical_bound", "executor_ready", "promotion_eligible")
        } != {
            "canonical_bound": False,
            "executor_ready": False,
            "promotion_eligible": False,
        }:
            raise AuditError("UI successor non-promotion boundary drift")


def _validate_current_candidate_binding(
    contract: dict[str, Any], oracles: dict[str, Any]
) -> None:
    expected_contract = {
        "package_id": "advertised-candidate-bindings-current-semantic-closure-successor",
        "contract_path": BINDING_CONTRACT,
        "compiler_path": BINDING_COMPILER,
        "contract_schema_path": BINDING_CONTRACT_SCHEMA,
        "overlay_schema_path": BINDING_OVERLAY_SCHEMA,
        "artifact_path": BINDING_ARTIFACT,
        "row_count": 10,
        "concrete_implementation_count": 4,
        "partial_implementation_count": 6,
        "executor_ready_count": 0,
        "canonical_binding_change_count": 0,
        "runtime_receipt_count": 0,
        "promotion_count": 0,
    }
    if contract.get("current_candidate_binding_successor") != expected_contract:
        raise AuditError("current candidate-binding successor contract drift")

    module = _load_module(BINDING_COMPILER, "metadata500_current_candidate_binding")
    compiled = module.compile_overlay()
    artifact = _strict_json(_read(BINDING_ARTIFACT), BINDING_ARTIFACT)
    if compiled != artifact:
        raise AuditError("current candidate-binding artifact is stale")
    summary = artifact.get("summary")
    if summary != {
        "row_count": 10,
        "concrete_implementation_count": 4,
        "partial_implementation_count": 6,
        "executor_ready_count": 0,
        "required_cloud_inference_count": 0,
        "warehouse_sample_dependency_count": 0,
        "concrete_full_binding_count": 0,
        "canonical_binding_change_count": 0,
        "admitted_count": 0,
        "executable_count": 0,
        "runtime_receipt_count": 0,
        "promotion_count": 0,
    }:
        raise AuditError("current candidate-binding summary drift")

    oracle_rows = oracles["oracles"]
    if not isinstance(oracle_rows, list) or len(oracle_rows) != 500:
        raise AuditError("selected oracle rows unavailable to candidate binding")
    observed: set[str] = set()
    for row in artifact.get("rows", []):
        capability_id = row.get("capability_id")
        index = row.get("oracle_index")
        if (
            capability_id not in EXPECTED_BINDING_INDICES
            or index != EXPECTED_BINDING_INDICES[capability_id]
            or capability_id in observed
        ):
            raise AuditError("current candidate-binding row identity drift")
        observed.add(capability_id)
        oracle = oracle_rows[index]
        if (
            oracle.get("capability_id") != capability_id
            or oracle.get("current_state") != "open_unexecuted"
            or oracle.get("runtime_state") != "not_qualified"
            or oracle.get("evidence") != []
            or oracle.get("execution_bounds", {}).get("executor") is not None
            or oracle.get("can_promote_runtime_state") is not False
            or row.get("executor_ready") is not False
            or row.get("canonical_effect")
            != {
                "admitted": False,
                "binding_kind_changed": False,
                "executable": False,
                "promoted": False,
                "runtime_evidence": [],
            }
        ):
            raise AuditError(
                f"candidate binding advanced canonical state: {capability_id}"
            )
    if observed != set(EXPECTED_BINDING_INDICES):
        raise AuditError("current candidate-binding exact-ten denominator drift")


def validate(contract: dict[str, Any] | None = None) -> dict[str, Any]:
    if contract is None:
        contract = _strict_json(CONTRACT_PATH.read_bytes(), str(CONTRACT_PATH))
    if (
        contract.get("schema_version") != 1
        or contract.get("package_id") != "metadata-500-current-overlay-audit-successor"
        or contract.get("mode")
        != "additive_static_selected_metadata_and_current_overlay_audit"
    ):
        raise AuditError("contract identity drift")
    if contract.get("policy") != EXPECTED_POLICY:
        raise AuditError("static non-promotion policy drift")
    locks = _source_locks(contract)
    required_paths = {
        SELECTOR,
        DESCRIPTOR,
        LEDGER,
        ORACLES,
        METADATA_COMPILER,
        *METADATA_SCHEMAS,
        "deploy/docker/thor-local/parity/metadata_sets/resolver.py",
        "deploy/docker/thor-local/parity/verify_metadata_set.py",
        *EXPECTED_CHANGED_ROWS,
        REBASE_CONTRACT,
        REBASE_VALIDATOR,
        BINDING_CONTRACT,
        BINDING_COMPILER,
        BINDING_CONTRACT_SCHEMA,
        BINDING_OVERLAY_SCHEMA,
        BINDING_ARTIFACT,
        *(row["contract_path"] for row in contract["runtime_successors"]),
        *(
            path
            for row in contract["runtime_successors"]
            for path in row["implementation_paths"]
        ),
    }
    if set(locks) != required_paths:
        raise AuditError("exact source-lock path set drift")
    ledger, oracles = _validate_metadata_boundary(contract, locks)
    _validate_changed_sources(contract, ledger, oracles)
    _validate_current_source_rebase(contract)
    _validate_runtime_successors(contract, oracles, locks)
    _validate_current_candidate_binding(contract, oracles)
    return {
        "schema_version": 1,
        "status": "pass_selected_metadata_current_overlay_static_audit",
        "selected_set": SELECTED_SET,
        "capabilities": 500,
        "oracles": 500,
        "candidate_rows": 211,
        "changed_agent_sources": 7,
        "changed_source_metadata_rows": 7,
        "current_source_rebased_rows": 31,
        "runtime_successor_packages": 4,
        "runtime_successor_canonical_rows": 5,
        "current_candidate_binding_rows": 10,
        "current_candidate_concrete_implementations": 4,
        "current_candidate_partial_implementations": 6,
        "runtime_evidence": 0,
        "canonical_state_advanced": False,
        "selector_mutated": False,
        "warehouse_sample_bundle": "excluded",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="run the static audit")
    parser.add_argument(
        "--json", action="store_true", help="emit the exact audit result"
    )
    args = parser.parse_args(argv)
    if not args.check:
        parser.error("--check is required")
    try:
        report = validate()
    except (AuditError, ImportError, KeyError, OSError, TypeError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            "PASS: selected Metadata-500 remains exact; seven current Agent "
            "sources and four runtime successors are overlay-bound; no promotion"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
