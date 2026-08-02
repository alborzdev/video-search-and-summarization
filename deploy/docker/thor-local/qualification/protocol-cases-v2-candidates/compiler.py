#!/usr/bin/env python3
"""Compile the isolated candidate-only protocol-v2 contract.

This compiler is static and inert. It reads checked-in files, validates exact
source locks, and writes only its deterministic candidate output when explicitly
invoked with ``--write``. It has no runtime, network, Docker, or host probes.
"""

from __future__ import annotations

import argparse
from collections import Counter
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any

from jsonschema import Draft202012Validator


sys.dont_write_bytecode = True

PACKAGE = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE.parents[4]
OUTPUT = PACKAGE / "protocol-cases-v2-candidate.json"
SCHEMA = PACKAGE / "protocol-cases-v2-candidate.schema.json"
DESIGN = PACKAGE / "design.json"

SOURCE_PATHS = {
    "live_contract": "deploy/docker/thor-local/qualification/protocol-cases/protocol-cases.json",
    "live_schema": "deploy/docker/thor-local/qualification/protocol-cases/protocol-cases.schema.json",
    "live_validator": "deploy/docker/thor-local/qualification/protocol-cases/validate_protocol_cases.py",
    "live_executor": "deploy/docker/thor-local/qualification/protocol-cases/protocol_case_executor.py",
    "candidate_input": "deploy/docker/thor-local/qualification/remaining-advertised-entry-candidates/candidate.json",
    "candidate_schema": "deploy/docker/thor-local/qualification/remaining-advertised-entry-candidates/candidate.schema.json",
    "candidate_compiler": "deploy/docker/thor-local/qualification/remaining-advertised-entry-candidates/compiler.py",
    "v2_design": "deploy/docker/thor-local/qualification/protocol-cases-v2-candidates/design.json",
}
PINNED_RAW_SHA256 = {
    "live_contract": "28cbcabef1bf1f3ed41ebf398de3e2387548b2ec6de72b5a51d8c5f30a59a7a6",
    "live_schema": "1f5d7d8a93591400acb3ac19a9d4336ba9f920ddb388d655e34a820bc8e75065",
    "live_validator": "9c847f9c777d785fd66d131198ba920b1ab21e0e4ef1c91cbaf4e7c8ff44cf40",
    "live_executor": "c615c2d9760219f5b0f7313ce244f3524b3b08ecb3193a8f7f61c00943fae963",
    "candidate_input": "a3c1b793f976fa384fb4ea588602f225e21c9d2d1fd563f12c0aadfa9d1a56fd",
    "candidate_schema": "e3f09d7c86c46e236b9786f5eb3aa60868e67363224922ce04cfab3d60cd12a8",
    "candidate_compiler": "c16021d6ca7e07afb1d207d5921b01286467a00798dabb8768a347c61384a132",
}

LIVE_COMPONENTS = {
    "protocol.agent.websocket": ["websocket"],
    "protocol.alert.websocket": ["redis-streams", "websocket"],
    "protocol.rt-vlm.sse": ["http", "sse"],
    "protocol.kafka.nvschema": ["kafka", "protobuf-nvschema"],
    "protocol.redis.events": ["redis-streams"],
    "protocol.vios.webrtc-live": ["http", "webrtc"],
    "protocol.vios.webrtc-replay": ["http", "webrtc"],
}
LIVE_EXECUTOR_READY = {
    "protocol.alert.websocket",
    "protocol.rt-vlm.sse",
    "protocol.redis.events",
    "protocol.vios.webrtc-live",
    "protocol.vios.webrtc-replay",
}
LIVE_BLOCKED = {"protocol.agent.websocket", "protocol.kafka.nvschema"}
EXCLUDED_WAREHOUSE_MARKERS = (
    "warehouse-4cams-20mx20m-synthetic",
    "warehouse-loading-dock-3cams-synthetic",
)
SSE_MCP_CAPABILITY_ID = "manifest-entry.video-summarization-live.05-sse-mcp-server"
SSE_MCP_DEPLOYMENT_SURFACES = (
    "deploy/docker/thor-local/Dockerfile.video-summarization",
    "services/video-summarization/src/lvs_mcp_sse.py",
)


class CandidateError(RuntimeError):
    """A source lock, candidate invariant, or deterministic output failed."""


def _sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _sha_json(value: Any) -> str:
    return _sha_bytes(_canonical_bytes(value))


def _encoded(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _strict_json(payload: bytes, label: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise CandidateError(f"{label}: duplicate JSON key {key!r}")
            value[key] = item
        return value

    try:
        return json.loads(payload.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CandidateError(f"{label}: invalid UTF-8 JSON: {exc}") from exc


def _regular_bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise CandidateError(f"not a regular non-symlink file: {path}")
    return path.read_bytes()


def _load_source(name: str) -> tuple[Any, dict[str, str]]:
    relative = SOURCE_PATHS[name]
    payload = _regular_bytes(REPO_ROOT / relative)
    digest = _sha_bytes(payload)
    expected = PINNED_RAW_SHA256.get(name)
    if expected is not None and digest != expected:
        raise CandidateError(f"{name}: pinned raw SHA-256 drift")
    return _strict_json(payload, name), {"path": relative, "raw_sha256": digest}


def _load_non_json_source(name: str) -> dict[str, str]:
    relative = SOURCE_PATHS[name]
    payload = _regular_bytes(REPO_ROOT / relative)
    digest = _sha_bytes(payload)
    expected = PINNED_RAW_SHA256[name]
    if digest != expected:
        raise CandidateError(f"{name}: pinned raw SHA-256 drift")
    return {"path": relative, "raw_sha256": digest}


def _resolve_surface(relative_text: str) -> Path:
    path_text = relative_text.split("#", 1)[0]
    relative = Path(path_text)
    if not path_text or relative.is_absolute() or ".." in relative.parts:
        raise CandidateError(f"unsafe implementation surface: {relative_text!r}")
    path = REPO_ROOT / relative
    current = REPO_ROOT
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise CandidateError(f"surface traverses symlink: {relative_text}")
    try:
        path.resolve(strict=True).relative_to(REPO_ROOT.resolve(strict=True))
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise CandidateError(f"surface escapes or is missing: {relative_text}") from exc
    if not path.is_file() or path.is_symlink():
        raise CandidateError(
            f"surface is not a regular non-symlink file: {relative_text}"
        )
    return path


def _surface_hashes(surfaces: list[str]) -> list[dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for surface in surfaces:
        path_text = surface.split("#", 1)[0]
        path = _resolve_surface(surface)
        result[path_text] = {
            "path": path_text,
            "raw_sha256": _sha_bytes(path.read_bytes()),
        }
    return [result[path] for path in sorted(result)]


def _candidate_case_id(capability_id: str) -> str:
    return f"protocol-v2-case.{capability_id}"


def _binding(case: dict[str, Any]) -> dict[str, Any]:
    if case["origin"] == "live_v1":
        payload = case["legacy_case"]
        vector_projection = {
            "kind": "executable_vectors",
            "positive_vector_id": payload["positive_vector"]["id"],
            "adjacent_negative_vector_ids": [
                vector["id"] for vector in payload["adjacent_negative_vectors"]
            ],
        }
        source_hashes = [
            {"path": source["path"], "raw_sha256": source["content_sha256"]}
            for source in payload["sources"]
        ]
    else:
        payload = case["candidate_contract"]
        vector_projection = {
            "kind": "planning_only",
            "contract": copy.deepcopy(payload["oracle_plan"]),
        }
        surfaces = list(payload["implementation_surfaces"])
        if case["capability_id"] == SSE_MCP_CAPABILITY_ID:
            surfaces.extend(SSE_MCP_DEPLOYMENT_SURFACES)
        source_hashes = _surface_hashes(surfaces)

    projection = {
        "capability_id": case["capability_id"],
        "case_id": case["case_id"],
        "case_payload_sha256": _sha_json(payload),
        "transport_components": copy.deepcopy(case["transport_components"]),
        "boundary": case["boundary"],
        "readiness": case["readiness"],
        "activation_supported": case["activation"]["supported"],
        "vector_projection": vector_projection,
        "source_hashes": source_hashes,
    }
    projection["binding_sha256"] = _sha_json(projection)
    return projection


def _candidate_contract(entry: dict[str, Any]) -> dict[str, Any]:
    capability = entry["proposed_capability"]
    contract = capability["contract"]
    return {
        "manifest_pointer": entry["manifest_pointer"],
        "advertised_literal": entry["advertised"],
        "acceptance_class": capability["acceptance_class"],
        "thor_state": capability["thor_state"],
        "runtime_state": capability["runtime_state"],
        "implementation_surfaces": copy.deepcopy(contract["implementation_surfaces"]),
        "required_semantics": copy.deepcopy(contract["required_semantics"]),
        "oracle_plan": copy.deepcopy(entry["oracle_plan"]),
    }


def compile_candidate() -> dict[str, Any]:
    live, live_lock = _load_source("live_contract")
    candidate, candidate_lock = _load_source("candidate_input")
    design, design_lock = _load_source("v2_design")
    source_locks = [
        live_lock,
        _load_source("live_schema")[1],
        _load_non_json_source("live_validator"),
        _load_non_json_source("live_executor"),
        candidate_lock,
        _load_source("candidate_schema")[1],
        _load_non_json_source("candidate_compiler"),
        design_lock,
    ]

    protocol_entries = [
        entry
        for entry in candidate["entries"]
        if entry["proposed_capability"]["kind"] == "protocol"
    ]
    if (
        set(design) != {"schema_version", "candidate_cases"}
        or design["schema_version"] != 1
    ):
        raise CandidateError("v2 design top-level contract drift")
    candidate_by_id = {
        entry["proposed_capability"]["id"]: entry for entry in protocol_entries
    }
    design_by_id: dict[str, dict[str, Any]] = {}
    for item in design.get("candidate_cases", []):
        capability_id = item.get("capability_id")
        if not isinstance(capability_id, str) or capability_id in design_by_id:
            raise CandidateError(
                f"missing or duplicate design capability: {capability_id!r}"
            )
        design_by_id[capability_id] = item
    if len(candidate_by_id) != 23 or set(design_by_id) != set(candidate_by_id):
        raise CandidateError("design must exactly partition the 23 protocol candidates")

    cases: list[dict[str, Any]] = []
    live_ids = [case["capability_id"] for case in live["cases"]]
    if set(live_ids) != set(LIVE_COMPONENTS) or len(live_ids) != 7:
        raise CandidateError("live seven-case denominator drift")
    for live_case in live["cases"]:
        capability_id = live_case["capability_id"]
        ready = capability_id in LIVE_EXECUTOR_READY
        if not ready and capability_id not in LIVE_BLOCKED:
            raise CandidateError(f"unclassified live readiness: {capability_id}")
        cases.append(
            {
                "origin": "live_v1",
                "capability_id": capability_id,
                "case_id": live_case["case_id"],
                "transport_components": LIVE_COMPONENTS[capability_id],
                "boundary": "local",
                "readiness": "executor_ready" if ready else "blocked",
                "activation": {
                    "supported": ready,
                    "executor_binding": live_case["case_id"] if ready else None,
                    "reason": (
                        "Existing live v1 executor binding is preserved."
                        if ready
                        else "Existing live v1 executor explicitly blocks this case."
                    ),
                },
                "runtime_evidence": [],
                "warehouse_sample_bundle": "excluded",
                "legacy_case": copy.deepcopy(live_case),
            }
        )

    for entry in protocol_entries:
        capability = entry["proposed_capability"]
        capability_id = capability["id"]
        item = design_by_id[capability_id]
        if set(item) != {
            "capability_id",
            "transport_components",
            "proposed_runner_family",
        }:
            raise CandidateError(f"{capability_id}: design keys drift")
        components = item["transport_components"]
        if (
            not isinstance(components, list)
            or not components
            or len(components) != len(set(components))
            or not all(isinstance(value, str) and value for value in components)
        ):
            raise CandidateError(f"{capability_id}: invalid transport components")
        boundary = entry["oracle_plan"]["execution_boundary"]
        expected_boundary = {
            "required_local": "local",
            "alternate_local_lane": "alternate_local",
            "external_optional": "external",
        }[capability["acceptance_class"]]
        if boundary != expected_boundary:
            raise CandidateError(f"{capability_id}: candidate boundary drift")
        reason = (
            "External candidate remains non-activating and requires separate authorized attestation."
            if boundary == "external"
            else "No protocol-v2 executor binding exists; the runner family is descriptive planning metadata only."
        )
        cases.append(
            {
                "origin": "candidate_manifest",
                "capability_id": capability_id,
                "case_id": _candidate_case_id(capability_id),
                "transport_components": copy.deepcopy(components),
                "boundary": boundary,
                "readiness": "planning_only",
                "activation": {
                    "supported": False,
                    "executor_binding": None,
                    "reason": reason,
                },
                "runtime_evidence": [],
                "warehouse_sample_bundle": "excluded",
                "proposed_runner_family": item["proposed_runner_family"],
                "candidate_contract": _candidate_contract(entry),
            }
        )

    bindings = [_binding(case) for case in cases]
    boundaries = Counter(case["boundary"] for case in cases)
    readiness = Counter(case["readiness"] for case in cases)
    document: dict[str, Any] = {
        "schema_version": 2,
        "candidate_id": "vss-thor-protocol-cases-v2-23-candidate-extension",
        "target": {
            "live_protocol_target_commit": live["target_commit"],
            "candidate_main_commit": candidate["target"]["main_commit"],
            "candidate_base_commit": candidate["target"]["base_commit"],
            "product_version": candidate["target"]["product_version"],
        },
        "policy": {
            "candidate_only": True,
            "live_integration": False,
            "runtime_evidence": [],
            "can_promote_runtime_state": False,
            "external_activation": False,
            "warehouse_sample_bundle": "excluded",
            "custom_data_warehouse_capability": "planning_only",
        },
        "source_locks": sorted(source_locks, key=lambda item: item["path"]),
        "summary": {
            "total_cases": len(cases),
            "preserved_live_v1_cases": 7,
            "candidate_protocol_cases": len(protocol_entries),
            "boundary_counts": dict(sorted(boundaries.items())),
            "readiness_counts": dict(sorted(readiness.items())),
            "runtime_evidence_records": 0,
            "activating_external_cases": 0,
            "warehouse_sample_bundle_entries": 0,
        },
        "cases": cases,
        "bindings": bindings,
    }
    document["candidate_payload_sha256"] = _sha_json(document)
    validate_candidate(document, live=live, candidate_input=candidate)
    return document


def validate_candidate(
    document: dict[str, Any],
    *,
    live: dict[str, Any] | None = None,
    candidate_input: dict[str, Any] | None = None,
) -> None:
    schema = _strict_json(_regular_bytes(SCHEMA), "v2 schema")
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(document),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = "/".join(str(item) for item in error.absolute_path) or "<root>"
        raise CandidateError(f"schema validation failed at {location}: {error.message}")

    payload = copy.deepcopy(document)
    claimed = payload.pop("candidate_payload_sha256")
    if claimed != _sha_json(payload):
        raise CandidateError("candidate_payload_sha256 mismatch")

    if live is None:
        live = _load_source("live_contract")[0]
    if candidate_input is None:
        candidate_input = _load_source("candidate_input")[0]
    expected_candidates = {
        entry["proposed_capability"]["id"]: entry
        for entry in candidate_input["entries"]
        if entry["proposed_capability"]["kind"] == "protocol"
    }
    cases = document["cases"]
    if len(cases) != 30 or len({case["capability_id"] for case in cases}) != 30:
        raise CandidateError("cases must contain 30 unique capability IDs")
    legacy_cases = [case for case in cases if case["origin"] == "live_v1"]
    candidate_cases = [case for case in cases if case["origin"] == "candidate_manifest"]
    if len(legacy_cases) != 7 or len(candidate_cases) != 23:
        raise CandidateError("case origin partition must be exactly 7 + 23")
    for wrapper, source_case in zip(legacy_cases, live["cases"], strict=True):
        if _canonical_bytes(wrapper["legacy_case"]) != _canonical_bytes(source_case):
            raise CandidateError(
                f"{wrapper['capability_id']}: live v1 case is not byte-semantically preserved"
            )
        if wrapper["capability_id"] != source_case["capability_id"]:
            raise CandidateError("legacy case order or identity drift")
    if {case["capability_id"] for case in candidate_cases} != set(expected_candidates):
        raise CandidateError("candidate protocol ID denominator drift")

    for case in candidate_cases:
        source = expected_candidates[case["capability_id"]]
        if case["candidate_contract"] != _candidate_contract(source):
            raise CandidateError(f"{case['capability_id']}: candidate contract drift")
        if case["readiness"] != "planning_only" or case["activation"] != {
            "supported": False,
            "executor_binding": None,
            "reason": case["activation"]["reason"],
        }:
            raise CandidateError(
                f"{case['capability_id']}: candidate activation overclaim"
            )
        if case["boundary"] == "external" and case["activation"]["supported"]:
            raise CandidateError(
                f"{case['capability_id']}: external activation is forbidden"
            )

    if any(case["runtime_evidence"] for case in cases):
        raise CandidateError("candidate package must carry zero runtime evidence")
    serialized = json.dumps(document, sort_keys=True).lower()
    if any(marker in serialized for marker in EXCLUDED_WAREHOUSE_MARKERS):
        raise CandidateError("Warehouse sample bundle is forbidden")

    bindings = document["bindings"]
    if len(bindings) != 30 or [item["capability_id"] for item in bindings] != [
        case["capability_id"] for case in cases
    ]:
        raise CandidateError("binding projection does not exactly cover cases in order")
    for case, binding in zip(cases, bindings, strict=True):
        expected = _binding(case)
        if binding != expected:
            raise CandidateError(f"{case['capability_id']}: binding projection drift")
        unhashed = copy.deepcopy(binding)
        binding_hash = unhashed.pop("binding_sha256")
        if binding_hash != _sha_json(unhashed):
            raise CandidateError(f"{case['capability_id']}: binding hash mismatch")

    lock_by_path = {lock["path"]: lock for lock in document["source_locks"]}
    if set(lock_by_path) != set(SOURCE_PATHS.values()):
        raise CandidateError("source lock denominator drift")
    for relative, lock in lock_by_path.items():
        if _sha_bytes(_regular_bytes(REPO_ROOT / relative)) != lock["raw_sha256"]:
            raise CandidateError(f"source lock drift: {relative}")


def _atomic_write(path: Path, payload: bytes) -> None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise CandidateError(f"unsafe output path: {path}")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            os.fchmod(handle.fileno(), 0o644)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="verify checked output")
    mode.add_argument("--write", action="store_true", help="replace checked output")
    args = parser.parse_args(argv)
    try:
        compiled = compile_candidate()
        payload = _encoded(compiled)
        if args.write:
            _atomic_write(OUTPUT, payload)
            print(f"WROTE {OUTPUT.relative_to(REPO_ROOT)} {_sha_bytes(payload)}")
            return 0
        if not OUTPUT.is_file() or OUTPUT.is_symlink():
            raise CandidateError("checked candidate output is missing or unsafe")
        if OUTPUT.read_bytes() != payload:
            raise CandidateError(
                "checked candidate output differs from deterministic compile"
            )
        print(
            "PASS protocol-v2 candidate: 7 preserved + 23 planning candidates, "
            f"30 bindings, sha256={_sha_bytes(payload)}"
        )
        return 0
    except CandidateError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
