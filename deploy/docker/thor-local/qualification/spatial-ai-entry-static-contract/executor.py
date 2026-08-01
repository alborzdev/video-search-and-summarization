#!/usr/bin/env python3
"""Validate the eight Spatial AI advertised-entry source-wiring contracts.

This executor is deliberately static and non-advancing.  It reads regular
repository files, verifies exact hashes plus AST/text assertions, and emits one
deterministic JSON result.  It does not import or execute reviewed product code.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4]
CONTRACT_PATH = HERE / "contract.json"
CONTRACT_SCHEMA_PATH = HERE / "contract.schema.json"
RESULT_SCHEMA_PATH = HERE / "result.schema.json"
MAX_INPUT_BYTES = 2_000_000
EXPECTED_CONTRACT_SHA256 = (
    "8709d97192997b41f68fcc12a57cfba821e1503c54e58dea9f8562c58167368b"
)

EXPECTED_POLICY = {
    "candidate_only": True,
    "can_mutate_live_ledgers": False,
    "can_mark_passed_current": False,
    "official_capability_effect": "none_static_contract_only",
    "runtime_evidence": [],
    "network_allowed": False,
    "docker_allowed": False,
    "subprocess_allowed": False,
    "downloads_allowed": False,
    "credentials_allowed": False,
    "service_lifecycle_allowed": False,
    "file_writes_allowed": False,
    "warehouse_sample_bundle": "excluded",
}

EXPECTED_ENTRIES = (
    (
        "/features/29/advertised/0",
        "calibration and camera grouping",
        "manifest-gap.spatial-ai-utils.00-calibration-and-camera-grouping",
        "manifest-entry.spatial-ai-utils.00-calibration-and-camera-grouping",
        "tooling",
        "alternate_local_lane",
        "wired",
        "not_qualified",
        "oracle.manifest-entry.spatial-ai-utils.00-calibration-and-camera-grouping",
        "offline_tool_execution",
        "open_unexecuted",
        5,
    ),
    (
        "/features/29/advertised/1",
        "3D/2D geometry",
        "manifest-gap.spatial-ai-utils.01-3d-2d-geometry",
        "manifest-entry.spatial-ai-utils.01-3d-2d-geometry",
        "tooling",
        "alternate_local_lane",
        "wired",
        "not_qualified",
        "oracle.manifest-entry.spatial-ai-utils.01-3d-2d-geometry",
        "offline_tool_execution",
        "open_unexecuted",
        3,
    ),
    (
        "/features/29/advertised/2",
        "multiview visualization",
        "manifest-gap.spatial-ai-utils.02-multiview-visualization",
        "manifest-entry.spatial-ai-utils.02-multiview-visualization",
        "tooling",
        "alternate_local_lane",
        "wired",
        "not_qualified",
        "oracle.manifest-entry.spatial-ai-utils.02-multiview-visualization",
        "offline_tool_execution",
        "open_unexecuted",
        3,
    ),
    (
        "/features/29/advertised/3",
        "detection mAP",
        "manifest-gap.spatial-ai-utils.03-detection-map",
        "manifest-entry.spatial-ai-utils.03-detection-map",
        "evaluation",
        "alternate_local_lane",
        "wired",
        "not_qualified",
        "oracle.manifest-entry.spatial-ai-utils.03-detection-map",
        "offline_tool_execution",
        "open_unexecuted",
        5,
    ),
    (
        "/features/29/advertised/4",
        "tracking HOTA/CLEAR/identity/count",
        "manifest-gap.spatial-ai-utils.04-tracking-hota-clear-identity-count",
        "manifest-entry.spatial-ai-utils.04-tracking-hota-clear-identity-count",
        "evaluation",
        "alternate_local_lane",
        "wired",
        "not_qualified",
        "oracle.manifest-entry.spatial-ai-utils.04-tracking-hota-clear-identity-count",
        "offline_tool_execution",
        "open_unexecuted",
        7,
    ),
    (
        "/features/29/advertised/5",
        "NVSchema conversion",
        "manifest-gap.spatial-ai-utils.05-nvschema-conversion",
        "manifest-entry.spatial-ai-utils.05-nvschema-conversion",
        "tooling",
        "alternate_local_lane",
        "wired",
        "not_qualified",
        "oracle.manifest-entry.spatial-ai-utils.05-nvschema-conversion",
        "offline_tool_execution",
        "open_unexecuted",
        3,
    ),
    (
        "/features/29/advertised/6",
        "video/frame tools",
        "manifest-gap.spatial-ai-utils.06-video-frame-tools",
        "manifest-entry.spatial-ai-utils.06-video-frame-tools",
        "tooling",
        "alternate_local_lane",
        "wired",
        "not_qualified",
        "oracle.manifest-entry.spatial-ai-utils.06-video-frame-tools",
        "offline_tool_execution",
        "open_unexecuted",
        4,
    ),
    (
        "/features/29/advertised/7",
        "AWS/GCS validation",
        "manifest-gap.spatial-ai-utils.07-aws-gcs-validation",
        "manifest-entry.spatial-ai-utils.07-aws-gcs-validation",
        "tooling",
        "external_optional",
        "external_optional",
        "not_applicable",
        "oracle.manifest-entry.spatial-ai-utils.07-aws-gcs-validation",
        "external_optional_boundary",
        "external_boundary_unexecuted",
        4,
    ),
)


class QualificationError(RuntimeError):
    """A contract, source lock, or non-advancing boundary did not match."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _strict_json_bytes(data: bytes, label: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise QualificationError(f"duplicate JSON key in {label}: {key!r}")
            value[key] = item
        return value

    try:
        return json.loads(data, object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"invalid JSON in {label}") from exc


def _validate_schema(value: Any, schema_path: Path, label: str) -> None:
    schema = _strict_json_bytes(schema_path.read_bytes(), schema_path.name)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise QualificationError(f"invalid schema: {schema_path.name}") from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        first = errors[0]
        where = "/" + "/".join(str(part) for part in first.absolute_path)
        raise QualificationError(
            f"{label} schema validation failed at {where}: {first.message}"
        )


def _repo_file(relative: str, *, required_prefix: str) -> Path:
    pure = PurePosixPath(relative)
    if (
        pure.is_absolute()
        or not pure.parts
        or ".." in pure.parts
        or not relative.startswith(required_prefix)
    ):
        raise QualificationError(f"unsafe repository path: {relative}")
    candidate = REPO_ROOT.joinpath(*pure.parts)
    try:
        metadata = candidate.lstat()
    except OSError as exc:
        raise QualificationError(f"repository input unavailable: {relative}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise QualificationError(
            f"repository input must be a regular non-symlink: {relative}"
        )
    resolved = candidate.resolve()
    try:
        resolved.relative_to(REPO_ROOT.resolve())
    except ValueError as exc:
        raise QualificationError(f"repository input escaped root: {relative}") from exc
    if metadata.st_size > MAX_INPUT_BYTES:
        raise QualificationError(f"repository input exceeds size bound: {relative}")
    return candidate


def _read_repo_bytes(relative: str, *, required_prefix: str) -> bytes:
    data = _repo_file(relative, required_prefix=required_prefix).read_bytes()
    if len(data) > MAX_INPUT_BYTES:
        raise QualificationError(f"repository input exceeds size bound: {relative}")
    return data


def _resolve_pointer(document: Any, pointer: str) -> Any:
    if not pointer.startswith("/"):
        raise QualificationError(f"invalid JSON pointer: {pointer}")
    value = document
    try:
        for raw in pointer.split("/")[1:]:
            token = raw.replace("~1", "/").replace("~0", "~")
            value = value[int(token)] if isinstance(value, list) else value[token]
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        raise QualificationError(f"unresolved JSON pointer: {pointer}") from exc
    return value


def _load_contract(
    contract_path: Path = CONTRACT_PATH,
    expected_sha256: str | None = EXPECTED_CONTRACT_SHA256,
) -> tuple[dict[str, Any], bytes]:
    raw = contract_path.read_bytes()
    if expected_sha256 is not None and _sha256(raw) != expected_sha256:
        raise QualificationError("contract raw digest mismatch")
    contract = _strict_json_bytes(raw, contract_path.name)
    _validate_schema(contract, CONTRACT_SCHEMA_PATH, "contract")
    return contract, raw


def _verify_contract_semantics(contract: dict[str, Any]) -> None:
    if contract["policy"] != EXPECTED_POLICY:
        raise QualificationError("non-advancing policy drift")
    if contract["manifest_binding"] != {
        "path": "deploy/docker/thor-local/parity/manifest.json",
        "feature_id": "spatial-ai-utils",
        "feature_index": 29,
        "feature_pointer": "/features/29",
        "advertised_entry_count": 8,
    }:
        raise QualificationError("manifest binding drift")

    observed: list[tuple[Any, ...]] = []
    for entry in contract["entries"]:
        capability = entry["capability"]
        oracle = entry["oracle"]
        observed.append(
            (
                entry["manifest_pointer"],
                entry["advertised"],
                entry["entry_id"],
                capability["id"],
                capability["kind"],
                capability["acceptance_class"],
                capability["thor_state"],
                capability["runtime_state"],
                oracle["id"],
                oracle["type"],
                oracle["current_state"],
                len(entry["source_reviews"]),
            )
        )
        if oracle["runtime_evidence"] != []:
            raise QualificationError("runtime evidence must remain empty")
        if oracle["static_contract_is_full_semantic_proof"] is not False:
            raise QualificationError("static contract cannot claim semantic proof")
    if tuple(observed) != EXPECTED_ENTRIES:
        raise QualificationError("exact eight-entry identity/state binding drift")

    source_paths = [
        review["path"]
        for entry in contract["entries"]
        for review in entry["source_reviews"]
    ]
    if len(source_paths) != 34 or len(set(source_paths)) != 34:
        raise QualificationError("expected exactly 34 unique reviewed source files")


def _verify_manifest(contract: dict[str, Any]) -> dict[str, Any]:
    binding = contract["manifest_binding"]
    raw = _read_repo_bytes(binding["path"], required_prefix="deploy/docker/")
    manifest = _strict_json_bytes(raw, binding["path"])
    feature = _resolve_pointer(manifest, binding["feature_pointer"])
    if not isinstance(feature, dict) or feature.get("id") != binding["feature_id"]:
        raise QualificationError("Spatial AI manifest feature binding drift")
    if feature.get("advertised") != [row[1] for row in EXPECTED_ENTRIES]:
        raise QualificationError("Spatial AI advertised literal/order drift")
    for entry in contract["entries"]:
        if _resolve_pointer(manifest, entry["manifest_pointer"]) != entry["advertised"]:
            raise QualificationError(
                f"manifest literal drift: {entry['manifest_pointer']}"
            )
    return {
        "path": binding["path"],
        "raw_sha256": _sha256(raw),
        "feature_canonical_sha256": _sha256(_canonical_bytes(feature)),
        "feature_id": feature["id"],
        "feature_index": binding["feature_index"],
        "advertised_entry_count": len(feature["advertised"]),
    }


def _top_level_symbols(raw: bytes, path: str) -> set[str]:
    try:
        tree = ast.parse(raw, filename=path)
    except SyntaxError as exc:
        raise QualificationError(f"reviewed Python source is invalid: {path}") from exc
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }


def _verify_sources(contract: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    per_entry: list[dict[str, Any]] = []
    unique_locks: dict[str, str] = {}
    for entry in contract["entries"]:
        assertion_count = 0
        entry_locks: list[dict[str, str]] = []
        for review in entry["source_reviews"]:
            path = review["path"]
            raw = _read_repo_bytes(
                path, required_prefix="libs/analytics/spatialai-data-utils/"
            )
            actual = _sha256(raw)
            if actual != review["sha256"]:
                raise QualificationError(f"source digest mismatch: {path}")
            if path in unique_locks and unique_locks[path] != actual:
                raise QualificationError(f"inconsistent duplicate source lock: {path}")
            unique_locks[path] = actual
            if review["ast_symbols"]:
                if path.endswith(".toml"):
                    raise QualificationError(f"AST symbols declared for non-Python file: {path}")
                symbols = _top_level_symbols(raw, path)
                missing = sorted(set(review["ast_symbols"]) - symbols)
                if missing:
                    raise QualificationError(
                        f"missing reviewed AST symbols in {path}: {missing}"
                    )
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise QualificationError(f"reviewed source is not UTF-8: {path}") from exc
            missing_fragments = [
                fragment for fragment in review["text_fragments"] if fragment not in text
            ]
            if missing_fragments:
                raise QualificationError(
                    f"missing reviewed text fragments in {path}: {missing_fragments}"
                )
            assertion_count += len(review["ast_symbols"]) + len(
                review["text_fragments"]
            )
            entry_locks.append({"path": path, "sha256": actual})
        per_entry.append(
            {
                "source_lock_count": len(entry_locks),
                "source_assertion_count": assertion_count,
                "source_set_sha256": _sha256(_canonical_bytes(entry_locks)),
            }
        )
    source_set = [
        {"path": path, "sha256": unique_locks[path]} for path in sorted(unique_locks)
    ]
    return per_entry, _sha256(_canonical_bytes(source_set))


def execute(
    contract_path: Path = CONTRACT_PATH,
    expected_contract_sha256: str | None = EXPECTED_CONTRACT_SHA256,
) -> dict[str, Any]:
    contract, contract_raw = _load_contract(contract_path, expected_contract_sha256)
    _verify_contract_semantics(contract)
    manifest_observation = _verify_manifest(contract)
    source_observations, source_set_sha256 = _verify_sources(contract)

    entries = []
    for contract_entry, source_observation in zip(
        contract["entries"], source_observations, strict=True
    ):
        capability = contract_entry["capability"]
        oracle = contract_entry["oracle"]
        entries.append(
            {
                "manifest_pointer": contract_entry["manifest_pointer"],
                "advertised": contract_entry["advertised"],
                "entry_id": contract_entry["entry_id"],
                "capability_id": capability["id"],
                "capability_kind": capability["kind"],
                "acceptance_class": capability["acceptance_class"],
                "thor_state": capability["thor_state"],
                "runtime_state": capability["runtime_state"],
                "oracle_id": oracle["id"],
                "oracle_type": oracle["type"],
                "oracle_current_state": oracle["current_state"],
                **source_observation,
                "observation": "observed_canonical_source_wiring",
                "runtime_evidence": [],
                "can_mark_passed_current": False,
            }
        )

    result = {
        "schema_version": 1,
        "package_id": "thor-spatial-ai-entry-static-contract-v1",
        "mode": "candidate_only_canonical_source_wiring",
        "candidate_only": True,
        "official_capability_effect": "none_static_contract_only",
        "contract_sha256": _sha256(contract_raw),
        "manifest_observation": manifest_observation,
        "summary": {
            "entry_count": 8,
            "local_wired_not_qualified_count": 7,
            "external_optional_not_applicable_count": 1,
            "open_offline_oracle_count": 7,
            "open_external_oracle_count": 1,
            "unique_source_lock_count": 34,
            "unique_source_set_sha256": source_set_sha256,
            "runtime_evidence_count": 0,
        },
        "entries": entries,
        "runtime_evidence": [],
        "can_mark_passed_current": False,
        "limitations": [
            "source wiring and exact canonical entry contracts only",
            "reviewed product functions and CLIs are not executed",
            "offline tool semantics, codecs, and external providers are not qualified",
            "no live parity ledger, oracle registry, gap plan, runtime plan, or wrapper is mutated",
        ],
    }
    _validate_schema(result, RESULT_SCHEMA_PATH, "result")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate and emit JSON")
    args = parser.parse_args()
    del args
    print(json.dumps(execute(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
