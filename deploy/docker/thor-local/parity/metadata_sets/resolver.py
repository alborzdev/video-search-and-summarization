#!/usr/bin/env python3
"""Resolve one complete, immutable Thor metadata set without side effects."""

from __future__ import annotations

import argparse
import copy
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
from types import MappingProxyType
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError


sys.dont_write_bytecode = True

PACKAGE = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE.parents[4].resolve(strict=True)
SELECTOR_PATH = "deploy/docker/thor-local/parity/metadata_sets/selector.json"
SELECTOR_SCHEMA_PATH = (
    "deploy/docker/thor-local/parity/metadata_sets/selector.schema.json"
)
SET_SCHEMA_PATH = (
    "deploy/docker/thor-local/parity/metadata_sets/metadata-set.schema.json"
)
SELECTOR_SCHEMA_RAW_SHA256 = (
    "16f22fc55e49f6b32d6053f585937688828f0e739ee56429da0bc2c0d5d5377b"
)
SET_SCHEMA_RAW_SHA256 = (
    "23019f9491d945243da785fab2c9ee007708ec1b2d910a9fd5ae625bd822eee4"
)
MAX_CONTROL_BYTES = 1_000_000
MAX_MEMBER_BYTES = 96_000_000
REQUIRED_DOCUMENTS = {
    "manifest",
    "official_capabilities",
    "capability_oracles",
    "acceptance_inventory",
}
REQUIRED_SCHEMAS = {
    "official_capabilities_schema",
    "capability_oracles_schema",
}
SPATIAL_AI_STAGE1_SET_IDS = {
    "thor-vss-3.2.1-current-spatial-ai-utils-core-289",
    "thor-vss-3.2.1-current-spatial-ai-utils-core-500",
}
SPATIAL_AI_STAGE1_IDS = {
    "manifest-entry.spatial-ai-utils.01-3d-2d-geometry",
    "manifest-entry.spatial-ai-utils.04-tracking-hota-clear-identity-count",
    "manifest-entry.spatial-ai-utils.05-nvschema-conversion",
}
SPATIAL_AI_STAGE1_GAP = (
    "No known gap: the committed target-bound offline SpatialAI runtime producer "
    "covers two positive runs, five named adjacent cases, deterministic output, "
    "exact cleanup, and observed imported-product calls without the Warehouse "
    "sample bundle. Runtime evidence remains a separate, non-promoting stage."
)


class MetadataSetError(ValueError):
    """The selector, immutable descriptor, or selected bundle is unsafe."""


@dataclass(frozen=True)
class _ReadRecord:
    path: str
    payload: bytes
    identity: tuple[int, int, int, int, int]


@dataclass(frozen=True)
class MetadataSnapshot:
    """One fully validated metadata-set snapshot.

    Parsed values are private. ``document`` and ``schema`` return deep copies so
    callers cannot mutate the validated snapshot shared with another consumer.
    """

    set_id: str
    descriptor_path: str
    descriptor_raw_sha256: str
    expected_counts: Mapping[str, int]
    _documents: Mapping[str, dict[str, Any]]
    _schemas: Mapping[str, dict[str, Any]]

    @property
    def document_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._documents))

    @property
    def schema_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._schemas))

    def document(self, document_id: str) -> dict[str, Any]:
        try:
            return copy.deepcopy(self._documents[document_id])
        except KeyError as exc:
            raise MetadataSetError(f"unknown document id: {document_id}") from exc

    def schema(self, schema_id: str) -> dict[str, Any]:
        try:
            return copy.deepcopy(self._schemas[schema_id])
        except KeyError as exc:
            raise MetadataSetError(f"unknown schema id: {schema_id}") from exc


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _safe_relative_path(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise MetadataSetError(f"{label}: path must be a non-empty string")
    if "\\" in value or "//" in value or value.endswith("/"):
        raise MetadataSetError(f"{label}: path is not canonical POSIX form")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != value
        or not value.startswith("deploy/docker/thor-local/")
    ):
        raise MetadataSetError(f"{label}: unsafe repository path")
    return value


def _identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _read_repo_regular(
    repo_root: Path,
    relative: Any,
    *,
    label: str,
    max_bytes: int,
) -> _ReadRecord:
    path_text = _safe_relative_path(relative, label)
    parts = PurePosixPath(path_text).parts
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | nofollow
    file_flags = os.O_RDONLY | nofollow
    try:
        current_fd = os.open(repo_root, directory_flags)
    except OSError as exc:
        raise MetadataSetError(
            f"{label}: repository root is not a safe directory"
        ) from exc
    try:
        for part in parts[:-1]:
            try:
                next_fd = os.open(part, directory_flags, dir_fd=current_fd)
            except OSError as exc:
                raise MetadataSetError(
                    f"{label}: path component is missing, unsafe, or a symlink"
                ) from exc
            os.close(current_fd)
            current_fd = next_fd
        try:
            file_fd = os.open(parts[-1], file_flags, dir_fd=current_fd)
        except OSError as exc:
            raise MetadataSetError(
                f"{label}: file is missing, unsafe, or a symlink"
            ) from exc
        try:
            before = os.fstat(file_fd)
            if not stat.S_ISREG(before.st_mode):
                raise MetadataSetError(f"{label}: member must be a regular file")
            if before.st_size > max_bytes:
                raise MetadataSetError(f"{label}: member exceeds bounded size")
            chunks: list[bytes] = []
            observed = 0
            while True:
                chunk = os.read(file_fd, min(1_048_576, max_bytes + 1 - observed))
                if not chunk:
                    break
                chunks.append(chunk)
                observed += len(chunk)
                if observed > max_bytes:
                    raise MetadataSetError(f"{label}: member exceeds bounded size")
            after = os.fstat(file_fd)
            if _identity(before) != _identity(after) or observed != after.st_size:
                raise MetadataSetError(f"{label}: file changed while being read")
            return _ReadRecord(path_text, b"".join(chunks), _identity(after))
        finally:
            os.close(file_fd)
    finally:
        os.close(current_fd)


def _strict_json(payload: bytes, label: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise MetadataSetError(f"{label}: duplicate JSON key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda token: (_ for _ in ()).throw(
                MetadataSetError(f"{label}: non-finite JSON number {token}")
            ),
        )
    except MetadataSetError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MetadataSetError(f"{label}: invalid UTF-8 JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise MetadataSetError(f"{label}: JSON root must be an object")
    return value


def _validate_schema_instance(
    value: dict[str, Any], schema: dict[str, Any], label: str
) -> None:
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.absolute_path) or "<root>"
        raise MetadataSetError(
            f"{label}: schema violation at {location}: {first.message}"
        )


def _load_pinned_control_schema(
    repo_root: Path, path: str, expected_sha256: str, label: str
) -> tuple[dict[str, Any], _ReadRecord]:
    record = _read_repo_regular(
        repo_root, path, label=label, max_bytes=MAX_CONTROL_BYTES
    )
    if _sha256(record.payload) != expected_sha256:
        raise MetadataSetError(f"{label}: pinned schema hash differs")
    schema = _strict_json(record.payload, label)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise MetadataSetError(f"{label}: invalid JSON Schema: {exc.message}") from exc
    return schema, record


def _unique_registry(selector: dict[str, Any]) -> dict[str, dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {}
    descriptor_paths: set[str] = set()
    for entry in selector["available_sets"]:
        set_id = entry["set_id"]
        path = _safe_relative_path(entry["descriptor_path"], f"set {set_id}")
        if set_id in registry:
            raise MetadataSetError(f"selector has duplicate set id: {set_id}")
        if path in descriptor_paths:
            raise MetadataSetError(f"selector reuses descriptor path: {path}")
        registry[set_id] = entry
        descriptor_paths.add(path)
    if selector["selected_set"] not in registry:
        raise MetadataSetError("selector selected_set is not in available_sets")
    return registry


def _document_oracles(document: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = [key for key in ("oracles", "projected_oracles") if key in document]
    if len(candidates) != 1 or not isinstance(document[candidates[0]], list):
        raise MetadataSetError(
            "capability_oracles: expected exactly one oracle collection"
        )
    values = document[candidates[0]]
    if not all(isinstance(item, dict) for item in values):
        raise MetadataSetError("capability_oracles: every oracle must be an object")
    return values


def _ledger_binding(capability: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "feature_id",
        "kind",
        "title",
        "source_claims",
        "acceptance_class",
        "thor_state",
        "runtime_state",
        "contract",
        "gap",
    )
    try:
        return {field: copy.deepcopy(capability[field]) for field in fields}
    except KeyError as exc:
        raise MetadataSetError(
            f"official_capabilities: capability lacks binding field {exc.args[0]}"
        ) from exc


def _is_spatial_ai_stage1_binding(
    set_id: str, capability: dict[str, Any], oracle: dict[str, Any]
) -> bool:
    capability_id = capability.get("id")
    binding = oracle.get("ledger_binding")
    unchanged_fields = (
        "feature_id",
        "kind",
        "title",
        "source_claims",
        "acceptance_class",
        "thor_state",
    )
    return (
        set_id in SPATIAL_AI_STAGE1_SET_IDS
        and capability_id in SPATIAL_AI_STAGE1_IDS
        and isinstance(binding, dict)
        and capability.get("runtime_state") == "not_qualified"
        and all(binding.get(key) == capability.get(key) for key in unchanged_fields)
        and binding.get("runtime_state") == "passed_current"
        and binding.get("gap") == SPATIAL_AI_STAGE1_GAP
        and isinstance(binding.get("contract"), dict)
        and binding["contract"].get("warehouse_sample_bundle") == "excluded"
        and oracle.get("acceptance_readiness")
        == {"classification": "executor_ready", "blockers": []}
        and oracle.get("current_state") == "open_unexecuted"
        and oracle.get("evidence") == []
    )


def _derived_family_status(capabilities: list[dict[str, Any]]) -> dict[str, str]:
    acceptance_classes = {item.get("acceptance_class") for item in capabilities}
    if "required_local" in acceptance_classes:
        acceptance_class = "required_local"
    elif acceptance_classes == {"external_optional"}:
        acceptance_class = "external_optional"
    else:
        acceptance_class = "alternate_local_lane"
    thor_states = {item.get("thor_state") for item in capabilities}
    runtime_states = {item.get("runtime_state") for item in capabilities}
    return {
        "acceptance_class": acceptance_class,
        "thor_state": (
            "external_optional"
            if acceptance_class == "external_optional"
            else next(iter(thor_states))
            if len(thor_states) == 1
            else "partial"
        ),
        "runtime_state": (
            next(iter(runtime_states)) if len(runtime_states) == 1 else "not_qualified"
        ),
    }


def _validate_bundle_semantics(
    descriptor: dict[str, Any],
    documents: dict[str, dict[str, Any]],
    schemas: dict[str, dict[str, Any]],
) -> None:
    if set(documents) != REQUIRED_DOCUMENTS or set(schemas) != REQUIRED_SCHEMAS:
        raise MetadataSetError("descriptor does not define the complete metadata plane")
    paths = [
        item["path"]
        for group in (descriptor["documents"], descriptor["schemas"])
        for item in group.values()
    ]
    if len(paths) != len(set(paths)):
        raise MetadataSetError("metadata set reuses a member path")

    for document_id, document in documents.items():
        expected_version = descriptor["documents"][document_id]["schema_version"]
        if document.get("schema_version") != expected_version:
            raise MetadataSetError(
                f"{document_id}: schema_version differs from descriptor"
            )

    for schema_id, schema in schemas.items():
        expected = descriptor["schemas"][schema_id]
        if schema.get("$schema") != expected["dialect"]:
            raise MetadataSetError(f"{schema_id}: JSON Schema dialect differs")
        if schema.get("$id") != expected["document_id"]:
            raise MetadataSetError(f"{schema_id}: JSON Schema id differs")
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            raise MetadataSetError(
                f"{schema_id}: invalid JSON Schema: {exc.message}"
            ) from exc

    for document_id in ("official_capabilities", "capability_oracles"):
        schema_id = descriptor["documents"][document_id]["schema_id"]
        _validate_schema_instance(
            documents[document_id], schemas[schema_id], document_id
        )

    manifest = documents["manifest"]
    ledger = documents["official_capabilities"]
    oracle_document = documents["capability_oracles"]
    acceptance = documents["acceptance_inventory"]
    capabilities = ledger.get("capabilities")
    features = manifest.get("features")
    coverage = acceptance.get("coverage")
    coverage_features = coverage.get("features") if isinstance(coverage, dict) else None
    if not isinstance(capabilities, list) or not all(
        isinstance(item, dict) for item in capabilities
    ):
        raise MetadataSetError("official_capabilities: capabilities must be objects")
    if not isinstance(features, list) or not all(
        isinstance(item, dict) for item in features
    ):
        raise MetadataSetError("manifest: features must be objects")
    if not isinstance(coverage_features, list) or not all(
        isinstance(item, dict) for item in coverage_features
    ):
        raise MetadataSetError("acceptance_inventory: feature coverage must be objects")
    oracles = _document_oracles(oracle_document)

    counts = descriptor["expected_counts"]
    observed_counts = {
        "capabilities": len(capabilities),
        "oracles": len(oracles),
        "feature_families": len(features),
    }
    if observed_counts != counts:
        raise MetadataSetError(
            f"metadata-set counts differ: expected={counts}, observed={observed_counts}"
        )

    capability_ids = [item.get("id") for item in capabilities]
    oracle_ids = [item.get("capability_id") for item in oracles]
    if (
        any(not isinstance(value, str) or not value for value in capability_ids)
        or len(capability_ids) != len(set(capability_ids))
        or oracle_ids != capability_ids
    ):
        raise MetadataSetError("ledger/oracle capability id order differs")
    stage1_bindings: set[str] = set()
    for capability, oracle in zip(capabilities, oracles, strict=True):
        if oracle.get("ledger_binding") == _ledger_binding(capability):
            continue
        if _is_spatial_ai_stage1_binding(descriptor["set_id"], capability, oracle):
            stage1_bindings.add(capability["id"])
        else:
            raise MetadataSetError(f"ledger/oracle binding differs: {capability['id']}")
    expected_stage1_bindings = (
        SPATIAL_AI_STAGE1_IDS
        if descriptor["set_id"] in SPATIAL_AI_STAGE1_SET_IDS
        else set()
    )
    if stage1_bindings != expected_stage1_bindings:
        raise MetadataSetError("SpatialAI Stage-1 binding denominator differs")

    feature_ids = [item.get("id") for item in features]
    coverage_ids = [item.get("feature_id") for item in coverage_features]
    if (
        any(not isinstance(value, str) or not value for value in feature_ids)
        or len(feature_ids) != len(set(feature_ids))
        or coverage_ids != feature_ids
    ):
        raise MetadataSetError("manifest/acceptance feature id order differs")
    manifest_owner: dict[str, str] = {}
    for feature in features:
        ids = feature.get("official_capability_ids", [])
        if not isinstance(ids, list):
            raise MetadataSetError(
                f"manifest feature {feature.get('id')}: capability ids must be a list"
            )
        for capability_id in ids:
            if capability_id in manifest_owner:
                raise MetadataSetError(
                    f"manifest assigns capability more than once: {capability_id}"
                )
            manifest_owner[capability_id] = feature["id"]
    if set(manifest_owner) != set(capability_ids):
        raise MetadataSetError("manifest/ledger capability id sets differ")
    if any(
        manifest_owner[capability["id"]] != capability.get("feature_id")
        for capability in capabilities
    ):
        raise MetadataSetError("manifest/ledger feature ownership differs")

    capabilities_by_feature: dict[str, list[dict[str, Any]]] = {}
    for capability in capabilities:
        capabilities_by_feature.setdefault(capability["feature_id"], []).append(
            capability
        )
    for feature in features:
        family = capabilities_by_feature.get(feature["id"], [])
        if not family:
            continue
        derived = _derived_family_status(family)
        if any(feature.get(field) != value for field, value in derived.items()):
            raise MetadataSetError(
                f"manifest aggregate differs from ledger: {feature['id']}"
            )

    scenarios = acceptance.get("scenarios")
    if not isinstance(scenarios, list) or not all(
        isinstance(item, dict) for item in scenarios
    ):
        raise MetadataSetError("acceptance_inventory: scenarios must be objects")
    scenario_ids = [item.get("id") for item in scenarios]
    if any(not isinstance(value, str) or not value for value in scenario_ids) or len(
        scenario_ids
    ) != len(set(scenario_ids)):
        raise MetadataSetError(
            "acceptance_inventory: scenario ids must be non-empty and unique"
        )
    known_scenarios = set(scenario_ids)
    coverage_by_feature = {item["feature_id"]: item for item in coverage_features}
    for coverage_entry in coverage_features:
        linked = coverage_entry.get("scenario_ids")
        if (
            not isinstance(linked, list)
            or any(not isinstance(value, str) or not value for value in linked)
            or len(linked) != len(set(linked))
            or not set(linked) <= known_scenarios
        ):
            raise MetadataSetError(
                "acceptance_inventory: coverage scenario ids are invalid, "
                f"duplicate, or absent: {coverage_entry['feature_id']}"
            )
    for capability in capabilities:
        linked = capability.get("scenario_ids")
        if (
            not isinstance(linked, list)
            or any(not isinstance(value, str) or not value for value in linked)
            or len(linked) != len(set(linked))
            or not set(linked) <= known_scenarios
        ):
            raise MetadataSetError(
                f"official_capabilities: invalid scenario ids: {capability['id']}"
            )
        missing = set(linked) - set(
            coverage_by_feature[capability["feature_id"]]["scenario_ids"]
        )
        if missing:
            raise MetadataSetError(
                "acceptance coverage omits capability scenarios: "
                f"{capability['id']}: {sorted(missing)}"
            )

    target = descriptor["target"]
    ledger_target = ledger.get("target")
    oracle_target = oracle_document.get("target")
    upstream = manifest.get("upstream")
    if not all(
        isinstance(item, dict) for item in (ledger_target, oracle_target, upstream)
    ):
        raise MetadataSetError("metadata target records are missing")
    if (
        ledger_target.get("product_version") != target["product_version"]
        or oracle_target.get("product_version") != target["product_version"]
        or str(upstream.get("latest_ga", "")).removeprefix("v")
        != target["product_version"]
        or ledger_target.get("main_commit") != target["main_commit"]
        or oracle_target.get("main_commit") != target["main_commit"]
        or upstream.get("target_commit") != target["main_commit"]
    ):
        raise MetadataSetError("metadata target records identify mixed sets")


def _recheck_records(repo_root: Path, records: list[_ReadRecord]) -> None:
    for prior in records:
        current = _read_repo_regular(
            repo_root,
            prior.path,
            label=f"TOCTOU recheck {prior.path}",
            max_bytes=max(MAX_CONTROL_BYTES, MAX_MEMBER_BYTES),
        )
        if current.identity != prior.identity or current.payload != prior.payload:
            raise MetadataSetError(
                f"bundle member changed during resolution: {prior.path}"
            )


def resolve_metadata_set(
    set_id: str | None = None,
    *,
    repo_root: Path = REPO_ROOT,
    selector_path: str = SELECTOR_PATH,
) -> MetadataSnapshot:
    """Validate a complete selected bundle and return one consistent snapshot."""

    root = repo_root.resolve(strict=True)
    if not root.is_dir() or root.is_symlink():
        raise MetadataSetError("repository root must be a regular directory")
    selector_schema, selector_schema_record = _load_pinned_control_schema(
        root,
        SELECTOR_SCHEMA_PATH,
        SELECTOR_SCHEMA_RAW_SHA256,
        "selector schema",
    )
    set_schema, set_schema_record = _load_pinned_control_schema(
        root, SET_SCHEMA_PATH, SET_SCHEMA_RAW_SHA256, "metadata-set schema"
    )
    selector_record = _read_repo_regular(
        root, selector_path, label="selector", max_bytes=MAX_CONTROL_BYTES
    )
    selector = _strict_json(selector_record.payload, "selector")
    _validate_schema_instance(selector, selector_schema, "selector")
    registry = _unique_registry(selector)
    selected_id = selector["selected_set"] if set_id is None else set_id
    if selected_id not in registry:
        raise MetadataSetError(f"unknown metadata set: {selected_id}")
    registry_entry = registry[selected_id]

    descriptor_record = _read_repo_regular(
        root,
        registry_entry["descriptor_path"],
        label=f"descriptor {selected_id}",
        max_bytes=MAX_CONTROL_BYTES,
    )
    descriptor_hash = _sha256(descriptor_record.payload)
    if descriptor_hash != registry_entry["descriptor_raw_sha256"]:
        raise MetadataSetError(f"descriptor {selected_id}: raw hash differs")
    descriptor = _strict_json(descriptor_record.payload, f"descriptor {selected_id}")
    _validate_schema_instance(descriptor, set_schema, f"descriptor {selected_id}")
    if descriptor["set_id"] != selected_id:
        raise MetadataSetError("selector and descriptor set ids differ")
    if set_id is None and descriptor["lifecycle"] != "live_ready":
        raise MetadataSetError(
            f"selected metadata set is not live-ready: {selected_id}"
        )

    documents: dict[str, dict[str, Any]] = {}
    schemas: dict[str, dict[str, Any]] = {}
    records = [
        selector_schema_record,
        set_schema_record,
        selector_record,
        descriptor_record,
    ]
    for group_id, destination in (("schemas", schemas), ("documents", documents)):
        for member_id, member in descriptor[group_id].items():
            record = _read_repo_regular(
                root,
                member["path"],
                label=f"{group_id}.{member_id}",
                max_bytes=MAX_MEMBER_BYTES,
            )
            if _sha256(record.payload) != member["raw_sha256"]:
                raise MetadataSetError(f"{group_id}.{member_id}: raw hash differs")
            destination[member_id] = _strict_json(
                record.payload, f"{group_id}.{member_id}"
            )
            records.append(record)

    _validate_bundle_semantics(descriptor, documents, schemas)
    _recheck_records(root, records)
    return MetadataSnapshot(
        set_id=selected_id,
        descriptor_path=descriptor_record.path,
        descriptor_raw_sha256=descriptor_hash,
        expected_counts=MappingProxyType(dict(descriptor["expected_counts"])),
        _documents=MappingProxyType(copy.deepcopy(documents)),
        _schemas=MappingProxyType(copy.deepcopy(schemas)),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set", dest="set_id", help="resolve a registered set id")
    parser.add_argument("--json", action="store_true", help="print a JSON result")
    args = parser.parse_args()
    try:
        snapshot = resolve_metadata_set(args.set_id)
    except (OSError, MetadataSetError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    result = {
        "set_id": snapshot.set_id,
        "descriptor_raw_sha256": snapshot.descriptor_raw_sha256,
        "expected_counts": dict(snapshot.expected_counts),
        "documents": list(snapshot.document_ids),
        "schemas": list(snapshot.schema_ids),
    }
    if args.json:
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    else:
        counts = result["expected_counts"]
        print(
            "PASS: immutable metadata set "
            f"{snapshot.set_id}; capabilities={counts['capabilities']}, "
            f"oracles={counts['oracles']}, families={counts['feature_families']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
