#!/usr/bin/env python3
"""Compile an isolated 289+211 candidate manifest and capability-ledger successor."""

from __future__ import annotations

import argparse
from collections import Counter
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


sys.dont_write_bytecode = True

PACKAGE = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE.parents[4].resolve(strict=True)
PROOF_OUTPUT = PACKAGE / "projection.json"
MANIFEST_OUTPUT = PACKAGE / "projected-manifest.json"
LEDGER_OUTPUT = PACKAGE / "projected-official-capabilities.json"
PROOF_SCHEMA = PACKAGE / "projection.schema.json"
MANIFEST_SCHEMA = PACKAGE / "projected-manifest.schema.json"

INPUTS = {
    "manifest": {
        "path": "deploy/docker/thor-local/parity/manifest.json",
        "raw_sha256": "1f56d63437bd7742cf7488b9bd85b25fc886cdaf39a3c2b46aabecbc6b7201ce",
    },
    "official_capabilities": {
        "path": "deploy/docker/thor-local/parity/official-capabilities.json",
        "raw_sha256": "cde0dc3981aaf699a017c7108089aac72070101edc47a06489f3940e44fe52a0",
    },
    "official_capabilities_schema": {
        "path": "deploy/docker/thor-local/parity/official-capabilities.schema.json",
        "raw_sha256": "fb817586b9a37ad7975ca820f69a7f2c6e575bca9f8d8686701d5fa0bf505896",
    },
    "candidate": {
        "path": "deploy/docker/thor-local/qualification/remaining-advertised-entry-candidates/candidate.json",
        "raw_sha256": "a3c1b793f976fa384fb4ea588602f225e21c9d2d1fd563f12c0aadfa9d1a56fd",
    },
    "candidate_schema": {
        "path": "deploy/docker/thor-local/qualification/remaining-advertised-entry-candidates/candidate.schema.json",
        "raw_sha256": "e3f09d7c86c46e236b9786f5eb3aa60868e67363224922ce04cfab3d60cd12a8",
    },
    "candidate_oracle_adapter": {
        "path": "deploy/docker/thor-local/qualification/candidate-oracle-adapter/adapter.json",
        "raw_sha256": "6e77635625a1f6b4b27dfcdc9aa5a0e695d6656adad041604f2b96fa2ac17235",
    },
    "candidate_oracle_adapter_schema": {
        "path": "deploy/docker/thor-local/qualification/candidate-oracle-adapter/adapter.schema.json",
        "raw_sha256": "959727de4d57884d67202847cd968e73fd792d1811356755c197a2e34403cbbb",
    },
    "acceptance_inventory": {
        "path": "deploy/docker/thor-local/qualification/acceptance_inventory.json",
        "raw_sha256": "79001985f9cc9d0dbb64adea2a014aaedacd0b0411d8becb5b311c8697a563a5",
    },
    "capability_oracles": {
        "path": "deploy/docker/thor-local/parity/capability-oracles.json",
        "raw_sha256": "c4e7a5ecfedfa2ddf18e68fc2bc110bea48d9ff7ce63d0dd4fdc169711beda90",
    },
    "capability_oracles_schema": {
        "path": "deploy/docker/thor-local/parity/capability-oracles.schema.json",
        "raw_sha256": "55de87c13e78b4f349e7095232f31c1135155e0bc13ed6bcb8e4abb906f26cf1",
    },
    "oracle_500_successor": {
        "path": "deploy/docker/thor-local/qualification/oracle-500-successor/capability-oracles-500.json",
        "raw_sha256": "75a7c6b6ecc5bcfee0eece99a10ca29c0258717887c59847252629ac4d21e364",
    },
    "oracle_500_successor_schema": {
        "path": "deploy/docker/thor-local/qualification/oracle-500-successor/capability-oracles-500.schema.json",
        "raw_sha256": "fcbe27337accc57c5a57a3ce7bf26d1e532c9001f7841134ec22db8663d41024",
    },
}

PROOF_SCHEMA_RAW_SHA256 = (
    "8f74b849581029c303a1e7a927f1f31b7458ed87e529d14e25134e52396f4ec9"
)
MANIFEST_SCHEMA_RAW_SHA256 = (
    "90b0452d8e19f7770b1ed13d6a5a7f1040612cc6e99edf8f4cd2d32ed86582c5"
)
EXPECTED_PROOF_PAYLOAD_SHA256 = (
    "2c62052d9059cad422e2a1acf336a61bc6a14e6d1127d26d570b2c2df7ceb0ed"
)
EXPECTED_PROOF_RAW_SHA256 = (
    "4e206240795e2cf739f595811920ae66a7868ebe92031feb73b7fcbbe5a971d0"
)
EXPECTED_MANIFEST_RAW_SHA256 = (
    "075a859219dfee4982338ca04244b6d444e0c23c9666c88e58e8f5fe58c366e8"
)
EXPECTED_LEDGER_RAW_SHA256 = (
    "f1e63b25c607a09f19a3c53aa47d8d152c61ffbd330440b93d54eccfaa49add6"
)
MAX_JSON_BYTES = 48_000_000
POINTER = re.compile(r"^/features/([0-9]+)/advertised/([0-9]+)$")
EXCLUDED_WAREHOUSE_MARKERS = (
    "warehouse-4cams-20mx20m-synthetic",
    "warehouse-loading-dock-3cams-synthetic",
)


class ProjectionError(RuntimeError):
    """A source lock, preservation rule, or deterministic projection failed."""


def _sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha_json(value: Any) -> str:
    return _sha_bytes(_canonical_bytes(value))


def _encoded(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _strict_json(payload: bytes, label: str) -> Any:
    if len(payload) > MAX_JSON_BYTES:
        raise ProjectionError(f"JSON exceeds bounded size: {label}")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ProjectionError(f"duplicate JSON key in {label}: {key!r}")
            result[key] = value
        return result

    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda token: (_ for _ in ()).throw(
                ProjectionError(f"non-finite JSON number in {label}: {token}")
            ),
        )
    except ProjectionError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProjectionError(f"invalid UTF-8 JSON in {label}: {exc}") from exc


def _repo_file(relative_text: str) -> Path:
    relative = Path(relative_text)
    if not relative_text or relative.is_absolute() or ".." in relative.parts:
        raise ProjectionError(f"unsafe repository path: {relative_text}")
    current = REPO_ROOT
    for part in relative.parts:
        current /= part
        try:
            mode = current.lstat().st_mode
        except OSError as exc:
            raise ProjectionError(f"missing repository file: {relative_text}") from exc
        if stat.S_ISLNK(mode):
            raise ProjectionError(f"repository path traverses symlink: {relative_text}")
    if not stat.S_ISREG(current.lstat().st_mode):
        raise ProjectionError(f"repository path is not a regular file: {relative_text}")
    try:
        current.resolve(strict=True).relative_to(REPO_ROOT)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ProjectionError(f"repository path escapes root: {relative_text}") from exc
    return current


def _load_locked(relative: str, expected_sha256: str) -> tuple[Any, str]:
    payload = _repo_file(relative).read_bytes()
    digest = _sha_bytes(payload)
    if expected_sha256 != digest:
        raise ProjectionError(f"raw source digest drift: {relative}")
    return _strict_json(payload, relative), digest


def _load_schema(path: Path, expected_sha256: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ProjectionError(f"schema must be a regular non-symlink: {path}")
    payload = path.read_bytes()
    digest = _sha_bytes(payload)
    if expected_sha256 != digest:
        raise ProjectionError(f"raw schema digest drift: {path}")
    schema = _strict_json(payload, str(path))
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ProjectionError(f"invalid schema {path.name}: {exc.message}") from exc
    return schema


def _validate(value: Any, schema: dict[str, Any], label: str) -> None:
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = "/" + "/".join(str(part) for part in error.absolute_path)
        raise ProjectionError(f"{label} schema error at {location}: {error.message}")


def _unique(
    rows: list[dict[str, Any]], key: str, label: str
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        identity = row.get(key)
        if not isinstance(identity, str) or not identity or identity in result:
            raise ProjectionError(f"missing or duplicate {label} key: {identity!r}")
        result[identity] = row
    return result


def _candidate_order_key(entry: dict[str, Any]) -> tuple[int, int]:
    match = POINTER.fullmatch(entry["manifest_pointer"])
    if match is None:
        raise ProjectionError(
            f"invalid candidate manifest pointer: {entry['manifest_pointer']}"
        )
    pointer_key = (int(match.group(1)), int(match.group(2)))
    if pointer_key != (entry["feature_index"], entry["advertised_index"]):
        raise ProjectionError(
            f"candidate pointer/index drift: {entry['manifest_pointer']}"
        )
    return pointer_key


def _assert_payload(value: dict[str, Any], field: str, label: str) -> None:
    payload = dict(value)
    observed = payload.pop(field)
    if observed != _sha_json(payload):
        raise ProjectionError(f"{label} payload digest mismatch")


def _ledger_binding(capability: dict[str, Any]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(capability[key])
        for key in (
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
    }


def _evidence_references(value: Any) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []

    def visit(node: Any, pointer: str) -> None:
        if isinstance(node, dict):
            for key in sorted(node):
                child_pointer = f"{pointer}/{key}"
                if "evidence" in key.lower():
                    references.append(
                        {"pointer": child_pointer, "value": copy.deepcopy(node[key])}
                    )
                visit(node[key], child_pointer)
        elif isinstance(node, list):
            for index, item in enumerate(node):
                visit(item, f"{pointer}/{index}")

    visit(value, "")
    return references


def _source_claim_set_digest(source_id: str, capabilities: list[dict[str, Any]]) -> str:
    claims = []
    for capability in capabilities:
        for claim in capability["source_claims"]:
            if claim["source_id"] == source_id:
                claims.append(
                    {
                        "capability_id": capability["id"],
                        "locator": claim["locator"],
                        "contract": capability["contract"],
                    }
                )
    canonical = sorted(
        json.dumps(item, sort_keys=True, separators=(",", ":")) for item in claims
    )
    return _sha_bytes(json.dumps(canonical, separators=(",", ":")).encode())


def _merge_blockers(
    projected_manifest: dict[str, Any],
    projected_ledger: dict[str, Any],
    acceptance: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    capabilities = projected_ledger["capabilities"]
    source_ids = set(_unique(projected_ledger["sources"], "id", "projected source"))
    scenario_ids = {
        row["id"] for row in acceptance["scenarios"] if isinstance(row, dict)
    }
    by_feature: dict[str, list[dict[str, Any]]] = {}
    for capability in capabilities:
        if not set(capability["scenario_ids"]) <= scenario_ids:
            raise ProjectionError(f"{capability['id']}: unknown acceptance scenario")
        for claim in capability["source_claims"]:
            if claim["source_id"] not in source_ids:
                raise ProjectionError(f"{capability['id']}: unknown source claim")
            if claim["locator"].lstrip().startswith("Advertised "):
                raise ProjectionError(
                    f"{capability['id']}: synthetic advertised source locator"
                )
        by_feature.setdefault(capability["feature_id"], []).append(capability)

    family_status: list[dict[str, Any]] = []
    for feature in projected_manifest["features"]:
        group = by_feature[feature["id"]]
        classes = {row["acceptance_class"] for row in group}
        derived_class = (
            "required_local"
            if "required_local" in classes
            else "external_optional"
            if classes == {"external_optional"}
            else "alternate_local_lane"
        )
        thor_states = {row["thor_state"] for row in group}
        derived_thor = next(iter(thor_states)) if len(thor_states) == 1 else "partial"
        runtime_states = {row["runtime_state"] for row in group}
        derived_runtime = (
            next(iter(runtime_states)) if len(runtime_states) == 1 else "not_qualified"
        )
        differences = [
            field
            for field, observed, derived in (
                ("acceptance_class", feature["acceptance_class"], derived_class),
                ("thor_state", feature["thor_state"], derived_thor),
                ("runtime_state", feature["runtime_state"], derived_runtime),
            )
            if observed != derived
        ]
        if differences:
            family_status.append(
                {
                    "feature_id": feature["id"],
                    "differing_fields": differences,
                    "preserved": {
                        "acceptance_class": feature["acceptance_class"],
                        "thor_state": feature["thor_state"],
                        "runtime_state": feature["runtime_state"],
                    },
                    "derived_from_500": {
                        "acceptance_class": derived_class,
                        "thor_state": derived_thor,
                        "runtime_state": derived_runtime,
                    },
                }
            )

    coverage_by_feature = {
        row["feature_id"]: set(row["scenario_ids"])
        for row in acceptance["coverage"]["features"]
    }
    scenario_gaps: list[dict[str, Any]] = []
    for feature_id, group in by_feature.items():
        required = set().union(*(set(row["scenario_ids"]) for row in group))
        missing = sorted(required - coverage_by_feature.get(feature_id, set()))
        if missing:
            scenario_gaps.append(
                {"feature_id": feature_id, "missing_scenario_ids": missing}
            )

    source_claim_drift: list[dict[str, Any]] = []
    for source in projected_ledger["sources"]:
        projected_digest = _source_claim_set_digest(source["id"], capabilities)
        if projected_digest != source["claim_set_sha256"]:
            source_claim_drift.append(
                {
                    "source_id": source["id"],
                    "preserved_claim_set_sha256": source["claim_set_sha256"],
                    "projected_claim_set_sha256": projected_digest,
                }
            )

    external_thor_states = [
        {
            "capability_id": row["id"],
            "candidate_thor_state": row["thor_state"],
            "live_external_family_required_thor_state": "external_optional",
        }
        for row in capabilities[289:]
        if row["acceptance_class"] == "external_optional"
        and row["thor_state"] != "external_optional"
    ]
    return {
        "external_candidate_thor_states": external_thor_states,
        "family_status_aggregate_drift": family_status,
        "acceptance_scenario_coverage_gaps": scenario_gaps,
        "source_claim_set_drift": source_claim_drift,
    }


def _project(
    manifest: dict[str, Any],
    ledger: dict[str, Any],
    candidate: dict[str, Any],
    adapter: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    features = manifest["features"]
    feature_by_id = _unique(features, "id", "manifest feature")
    current_capabilities = _unique(ledger["capabilities"], "id", "current capability")
    if len(features) != 55 or len(current_capabilities) != 289:
        raise ProjectionError("current manifest/ledger denominator drift")

    ordered_entries = sorted(candidate["entries"], key=_candidate_order_key)
    candidate_capabilities: dict[str, dict[str, Any]] = {}
    entries_by_feature: dict[str, list[dict[str, Any]]] = {}
    append_order: list[dict[str, Any]] = []
    adapter_rows = adapter["candidate_adapters_by_capability_id"]
    if len(adapter_rows) != 211:
        raise ProjectionError("candidate adapter denominator drift")
    for entry in ordered_entries:
        capability = entry["proposed_capability"]
        capability_id = capability["id"]
        if (
            capability_id in current_capabilities
            or capability_id in candidate_capabilities
        ):
            raise ProjectionError(
                f"duplicate or colliding candidate capability: {capability_id}"
            )
        feature = feature_by_id.get(entry["feature_id"])
        if feature is None or capability["feature_id"] != entry["feature_id"]:
            raise ProjectionError(f"{capability_id}: candidate feature binding drift")
        if feature["advertised"][entry["advertised_index"]] != entry["advertised"]:
            raise ProjectionError(f"{capability_id}: advertised pointer drift")
        adapter_row = adapter_rows.get(capability_id)
        if (
            adapter_row is None
            or adapter_row["candidate_entry_sha256"] != _sha_json(entry)
            or adapter_row["ledger_binding"] != _ledger_binding(capability)
            or adapter_row["readiness"]["classification"] != "planning_index_only"
            or adapter_row["readiness"]["executor_ready"] is not False
            or adapter_row["evidence"]
            or adapter_row["can_promote_runtime_state"] is not False
        ):
            raise ProjectionError(f"{capability_id}: candidate adapter binding drift")
        candidate_capabilities[capability_id] = capability
        entries_by_feature.setdefault(entry["feature_id"], []).append(entry)
        append_order.append(
            {
                "manifest_pointer": entry["manifest_pointer"],
                "feature_index": entry["feature_index"],
                "advertised_index": entry["advertised_index"],
                "feature_id": entry["feature_id"],
                "capability_id": capability_id,
                "capability_canonical_sha256": _sha_json(capability),
                "adapter_entry_sha256": _sha_json(adapter_row),
            }
        )
    if len(candidate_capabilities) != 211 or set(adapter_rows) != set(
        candidate_capabilities
    ):
        raise ProjectionError("candidate/adapter key partition drift")

    projected_manifest = copy.deepcopy(manifest)
    for feature in projected_manifest["features"]:
        additions = entries_by_feature.get(feature["id"], [])
        existing_ids = list(feature.get("official_capability_ids", []))
        feature["official_capability_ids"] = [
            *existing_ids,
            *(entry["proposed_capability"]["id"] for entry in additions),
        ]

    projected_ledger = copy.deepcopy(ledger)
    projected_ledger["capabilities"].extend(
        copy.deepcopy(candidate_capabilities[row["capability_id"]])
        for row in append_order
    )
    for source in projected_ledger["sources"]:
        source["claim_set_sha256"] = _source_claim_set_digest(
            source["id"], projected_ledger["capabilities"]
        )
    return projected_manifest, projected_ledger, append_order


def _verify_adapter_preservation(
    adapter: dict[str, Any],
    current_ledger: dict[str, Any],
    current_oracles: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    capability_by_id = _unique(
        current_ledger["capabilities"], "id", "current capability"
    )
    oracle_by_capability = _unique(
        current_oracles["oracles"], "capability_id", "current oracle capability"
    )
    preserved = adapter["current_oracle_preservation"]["by_capability_id"]
    if set(preserved) != set(capability_by_id) or set(oracle_by_capability) != set(
        capability_by_id
    ):
        raise ProjectionError("adapter current-oracle preservation key drift")
    for capability_id, capability in capability_by_id.items():
        oracle = oracle_by_capability[capability_id]
        expected = {
            "oracle_id": oracle["oracle_id"],
            "current_state": oracle["current_state"],
            "ledger_runtime_state": capability["runtime_state"],
            "evidence": oracle["evidence"],
        }
        row = preserved[capability_id]
        if (
            {key: row[key] for key in expected} != expected
            or row["state_evidence_sha256"]
            != _sha_json(
                {
                    key: expected[key]
                    for key in ("current_state", "ledger_runtime_state", "evidence")
                }
            )
            or oracle["oracle_id"] != f"oracle.{capability_id}"
        ):
            raise ProjectionError(f"{capability_id}: adapter oracle preservation drift")
    preservation = adapter["current_oracle_preservation"]
    if (
        preservation["ledger_records_canonical_sha256"]
        != _sha_json(current_ledger["capabilities"])
        or preservation["oracle_records_canonical_sha256"]
        != _sha_json(current_oracles["oracles"])
        or preservation["state_evidence_projection_sha256"] != _sha_json(preserved)
        or adapter["summary"]["preserved_current_oracle_count"] != 289
        or adapter["summary"]["current_evidence_record_count"] != 0
        or any(row["evidence"] for row in preserved.values())
    ):
        raise ProjectionError("adapter current-oracle preservation digest/count drift")

    explicit = 0
    family_only = 0
    adapter_rows = adapter["candidate_adapters_by_capability_id"]
    for entry in candidate["entries"]:
        capability_id = entry["proposed_capability"]["id"]
        row = adapter_rows[capability_id]
        authoritative = row["candidate_oracle_plan"].get(
            "authoritative_gap_requirement"
        )
        if entry["prior_mapping_class"] == "explicit_missing_entry_gap":
            explicit += 1
            if authoritative != entry["gap_plan_binding"]:
                raise ProjectionError(
                    f"{capability_id}: adapter authoritative gap binding drift"
                )
        else:
            family_only += 1
            if authoritative is not None or "gap_plan_binding" in entry:
                raise ProjectionError(f"{capability_id}: family-only gap binding drift")
    if (explicit, family_only) != (74, 137):
        raise ProjectionError("candidate gap/family partition drift")
    return {
        "current_oracle_count": len(preserved),
        "current_oracle_evidence_record_count": sum(
            len(row["evidence"]) for row in preserved.values()
        ),
        "current_oracle_records_canonical_sha256": _sha_json(
            current_oracles["oracles"]
        ),
        "current_oracle_state_evidence_projection_sha256": _sha_json(preserved),
        "explicit_authoritative_gap_binding_count": explicit,
        "family_only_without_gap_binding_count": family_only,
    }


def _verify_projection(
    current_manifest: dict[str, Any],
    current_ledger: dict[str, Any],
    projected_manifest: dict[str, Any],
    projected_ledger: dict[str, Any],
    append_order: list[dict[str, Any]],
    official_schema: dict[str, Any],
    manifest_schema: dict[str, Any],
) -> dict[str, Any]:
    _validate(projected_manifest, manifest_schema, "projected manifest")
    _validate(projected_ledger, official_schema, "projected official capabilities")
    if projected_manifest.keys() != current_manifest.keys():
        raise ProjectionError("manifest root fields drift")
    if len(projected_manifest["features"]) != len(current_manifest["features"]):
        raise ProjectionError("manifest feature count drift")
    for before, after in zip(
        current_manifest["features"], projected_manifest["features"], strict=True
    ):
        before_without_ids = copy.deepcopy(before)
        after_without_ids = copy.deepcopy(after)
        original_ids = before_without_ids.pop("official_capability_ids", [])
        projected_ids = after_without_ids.pop("official_capability_ids", [])
        if (
            before_without_ids != after_without_ids
            or projected_ids[: len(original_ids)] != original_ids
        ):
            raise ProjectionError(
                f"{before['id']}: manifest feature preservation drift"
            )
    for field in current_manifest:
        if field != "features" and projected_manifest[field] != current_manifest[field]:
            raise ProjectionError(f"manifest field preservation drift: {field}")

    if (
        projected_ledger["schema_version"] != current_ledger["schema_version"]
        or projected_ledger["target"] != current_ledger["target"]
        or projected_ledger["source_discrepancies"]
        != current_ledger["source_discrepancies"]
        or projected_ledger["capabilities"][:289] != current_ledger["capabilities"]
    ):
        raise ProjectionError("current ledger semantic/order preservation drift")
    if len(projected_ledger["sources"]) != len(current_ledger["sources"]):
        raise ProjectionError("source denominator drift")
    for before, after in zip(
        current_ledger["sources"], projected_ledger["sources"], strict=True
    ):
        before_without_hash = {
            key: value for key, value in before.items() if key != "claim_set_sha256"
        }
        after_without_hash = {
            key: value for key, value in after.items() if key != "claim_set_sha256"
        }
        expected_claim_hash = _source_claim_set_digest(
            after["id"], projected_ledger["capabilities"]
        )
        if (
            before_without_hash != after_without_hash
            or after["claim_set_sha256"] != expected_claim_hash
        ):
            raise ProjectionError(
                f"{before['id']}: source preservation/claim hash drift"
            )
    if len(projected_ledger["capabilities"]) != 500 or len(append_order) != 211:
        raise ProjectionError("projected ledger denominator drift")

    capability_by_id = _unique(
        projected_ledger["capabilities"], "id", "projected capability"
    )
    seen_mappings: set[str] = set()
    mapping_rows: list[dict[str, Any]] = []
    exact_mapping_count = 0
    missing = 0
    ambiguous = 0
    for feature in projected_manifest["features"]:
        ids = feature["official_capability_ids"]
        if len(ids) != len(set(ids)):
            raise ProjectionError(f"{feature['id']}: duplicate capability reference")
        title_to_ids: dict[str, list[str]] = {}
        for capability_id in ids:
            capability = capability_by_id.get(capability_id)
            if capability is None or capability["feature_id"] != feature["id"]:
                raise ProjectionError(
                    f"{feature['id']}: missing or cross-family capability"
                )
            title_to_ids.setdefault(capability["title"], []).append(capability_id)
        feature_index = projected_manifest["features"].index(feature)
        for advertised_index, advertised in enumerate(feature["advertised"]):
            matches = title_to_ids.get(advertised, [])
            if not matches:
                missing += 1
            elif len(matches) > 1:
                ambiguous += 1
            else:
                exact_mapping_count += 1
                seen_mappings.add(matches[0])
                mapping_rows.append(
                    {
                        "manifest_pointer": f"/features/{feature_index}/advertised/{advertised_index}",
                        "feature_id": feature["id"],
                        "advertised": advertised,
                        "capability_id": matches[0],
                    }
                )
    if (
        exact_mapping_count != 500
        or missing
        or ambiguous
        or seen_mappings != set(capability_by_id)
    ):
        raise ProjectionError("exact-title mapping completeness drift")

    candidates = projected_ledger["capabilities"][289:]
    acceptance_counts = dict(
        sorted(Counter(row["acceptance_class"] for row in candidates).items())
    )
    candidate_runtime_counts = dict(
        sorted(Counter(row["runtime_state"] for row in candidates).items())
    )
    projected_runtime_counts = dict(
        sorted(
            Counter(
                row["runtime_state"] for row in projected_ledger["capabilities"]
            ).items()
        )
    )
    if acceptance_counts != {
        "alternate_local_lane": 46,
        "external_optional": 6,
        "required_local": 159,
    } or candidate_runtime_counts != {"not_applicable": 6, "not_qualified": 205}:
        raise ProjectionError("candidate acceptance/runtime boundary drift")
    runtime_evidence_count = sum(
        len(row.get("runtime_evidence", [])) for row in projected_ledger["capabilities"]
    )
    passed_current_count = sum(
        row["runtime_state"] == "passed_current"
        for row in projected_ledger["capabilities"]
    )
    if runtime_evidence_count or passed_current_count:
        raise ProjectionError(
            "projection cannot add evidence or current-pass promotion"
        )
    external_thor_state_blockers = sum(
        row["acceptance_class"] == "external_optional"
        and row["thor_state"] != "external_optional"
        for row in candidates
    )
    if external_thor_state_blockers != 6:
        raise ProjectionError("external candidate Thor-state blocker denominator drift")
    serialized_candidates = json.dumps(candidates, sort_keys=True).lower()
    if any(marker in serialized_candidates for marker in EXCLUDED_WAREHOUSE_MARKERS):
        raise ProjectionError(
            "excluded Warehouse sample marker in candidate projection"
        )
    return {
        "exact_mapping_count": exact_mapping_count,
        "missing_exact_mapping_count": missing,
        "ambiguous_exact_mapping_count": ambiguous,
        "candidate_acceptance_class_counts": acceptance_counts,
        "candidate_runtime_state_counts": candidate_runtime_counts,
        "projected_runtime_state_counts": projected_runtime_counts,
        "runtime_evidence_record_count": runtime_evidence_count,
        "passed_current_count": passed_current_count,
        "external_candidate_thor_state_distinction_count": external_thor_state_blockers,
        "exact_mapping_rows_sha256": _sha_json(mapping_rows),
    }


def compile_projection() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    documents: dict[str, Any] = {}
    source_locks: dict[str, dict[str, str]] = {}
    for source_id, specification in INPUTS.items():
        value, digest = _load_locked(specification["path"], specification["raw_sha256"])
        documents[source_id] = value
        source_locks[source_id] = {
            "path": specification["path"],
            "raw_sha256": digest,
        }

    official_schema = documents["official_capabilities_schema"]
    candidate_schema = documents["candidate_schema"]
    adapter_schema = documents["candidate_oracle_adapter_schema"]
    oracle_schema = documents["capability_oracles_schema"]
    oracle_500_schema = documents["oracle_500_successor_schema"]
    for label, schema in (
        ("official capabilities", official_schema),
        ("candidate", candidate_schema),
        ("candidate oracle adapter", adapter_schema),
        ("capability oracles", oracle_schema),
        ("oracle-500 successor", oracle_500_schema),
    ):
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            raise ProjectionError(f"invalid {label} schema: {exc.message}") from exc

    manifest_schema = _load_schema(MANIFEST_SCHEMA, MANIFEST_SCHEMA_RAW_SHA256)
    candidate = documents["candidate"]
    adapter = documents["candidate_oracle_adapter"]
    current_manifest = documents["manifest"]
    current_ledger = documents["official_capabilities"]
    current_oracles = documents["capability_oracles"]
    acceptance = documents["acceptance_inventory"]
    oracle_500 = documents["oracle_500_successor"]
    current_manifest_schema = copy.deepcopy(manifest_schema)
    current_manifest_schema["$defs"]["feature"]["required"].remove(
        "official_capability_ids"
    )
    _validate(current_manifest, current_manifest_schema, "current manifest")
    _validate(current_ledger, official_schema, "current official capabilities")
    _validate(candidate, candidate_schema, "candidate")
    _validate(adapter, adapter_schema, "candidate oracle adapter")
    _validate(current_oracles, oracle_schema, "current capability oracles")
    _validate(oracle_500, oracle_500_schema, "oracle-500 successor")
    _assert_payload(candidate, "candidate_payload_sha256", "candidate")
    _assert_payload(adapter, "adapter_payload_sha256", "candidate oracle adapter")
    _assert_payload(oracle_500, "successor_payload_sha256", "oracle-500 successor")
    for adapter_source, local_source in (
        ("candidate", "candidate"),
        ("candidate_schema", "candidate_schema"),
        ("official_capabilities", "official_capabilities"),
        ("official_capabilities_schema", "official_capabilities_schema"),
        ("capability_oracles", "capability_oracles"),
        ("capability_oracles_schema", "capability_oracles_schema"),
    ):
        if adapter["source_locks"][adapter_source] != source_locks[local_source]:
            raise ProjectionError(f"adapter source lock drift: {adapter_source}")
    if adapter["target"] != candidate["target"]:
        raise ProjectionError("adapter/candidate target drift")
    oracle_preservation = _verify_adapter_preservation(
        adapter, current_ledger, current_oracles, candidate
    )

    projected_manifest, projected_ledger, append_order = _project(
        current_manifest, current_ledger, candidate, adapter
    )
    projected_oracles = oracle_500["projected_oracles"]
    if len(projected_oracles) != 500 or [
        row["capability_id"] for row in projected_oracles
    ] != [row["id"] for row in projected_ledger["capabilities"]]:
        raise ProjectionError("oracle-500 capability order/set binding drift")
    for capability, oracle in zip(
        projected_ledger["capabilities"], projected_oracles, strict=True
    ):
        if oracle["ledger_binding"] != _ledger_binding(capability):
            raise ProjectionError(
                f"{capability['id']}: oracle-500 ledger binding drift"
            )
    oracle_500_order_sha256 = _sha_json(
        [row["capability_id"] for row in projected_oracles]
    )
    verification = _verify_projection(
        current_manifest,
        current_ledger,
        projected_manifest,
        projected_ledger,
        append_order,
        official_schema,
        manifest_schema,
    )
    blockers = _merge_blockers(projected_manifest, projected_ledger, acceptance)
    if (
        len(blockers["family_status_aggregate_drift"]) != 9
        or len(blockers["acceptance_scenario_coverage_gaps"]) != 8
        or blockers["source_claim_set_drift"]
        or len(blockers["external_candidate_thor_states"]) != 6
    ):
        raise ProjectionError("live-verifier blocker/distinction denominator drift")
    merge_blockers = {
        "family_status_aggregate_drift": blockers["family_status_aggregate_drift"],
        "acceptance_scenario_coverage_gaps": blockers[
            "acceptance_scenario_coverage_gaps"
        ],
    }
    reviewed_distinctions = {
        "external_candidate_thor_states": blockers["external_candidate_thor_states"]
    }
    source_claim_transitions = [
        {
            "source_id": before["id"],
            "current_claim_set_sha256": before["claim_set_sha256"],
            "projected_claim_set_sha256": after["claim_set_sha256"],
            "changed": before["claim_set_sha256"] != after["claim_set_sha256"],
        }
        for before, after in zip(
            current_ledger["sources"], projected_ledger["sources"], strict=True
        )
    ]
    changed_source_ids = [
        row["source_id"] for row in source_claim_transitions if row["changed"]
    ]
    unchanged_source_ids = [
        row["source_id"] for row in source_claim_transitions if not row["changed"]
    ]
    if (len(changed_source_ids), len(unchanged_source_ids)) != (17, 109):
        raise ProjectionError("source claim-set transition denominator drift")
    manifest_encoded = _encoded(projected_manifest)
    ledger_encoded = _encoded(projected_ledger)
    manifest_evidence_fields = _evidence_references(current_manifest)
    current_runtime_projection = [
        {"id": row["id"], "runtime_state": row["runtime_state"]}
        for row in current_ledger["capabilities"]
    ]
    proof: dict[str, Any] = {
        "schema_version": 1,
        "projection_id": "vss-3.2.1-thor-ledger-500-candidate-successor",
        "mode": "candidate_only_non_advancing_projection",
        "target": copy.deepcopy(candidate["target"]),
        "source_locks": source_locks,
        "policy": {
            "candidate_only": True,
            "modifies_live_files": False,
            "live_merge_ready": False,
            "can_promote_runtime_state": False,
            "runtime_evidence": [],
            "required_cloud_inference": False,
            "warehouse_sample_bundle": "excluded",
            "custom_data_warehouse_capability": "in_scope",
        },
        "summary": {
            "current_capability_count": 289,
            "appended_candidate_count": 211,
            "projected_capability_count": 500,
            "manifest_feature_count": len(projected_manifest["features"]),
            "manifest_advertised_count": sum(
                len(feature["advertised"]) for feature in projected_manifest["features"]
            ),
            **verification,
            "source_count": len(projected_ledger["sources"]),
            "source_discrepancy_count": len(projected_ledger["source_discrepancies"]),
            "candidate_adapter_count": len(
                adapter["candidate_adapters_by_capability_id"]
            ),
            "candidate_executor_ready_count": adapter["summary"][
                "candidate_executor_ready_count"
            ],
            "warehouse_sample_bundle_entries": 0,
            "projected_oracle_count": len(projected_oracles),
            "live_merge_blocker_category_count": len(merge_blockers),
            "family_status_aggregate_drift_count": len(
                merge_blockers["family_status_aggregate_drift"]
            ),
            "acceptance_scenario_coverage_gap_count": len(
                merge_blockers["acceptance_scenario_coverage_gaps"]
            ),
            "changed_source_claim_hash_count": len(changed_source_ids),
            "unchanged_source_claim_hash_count": len(unchanged_source_ids),
        },
        "preservation": {
            "current_manifest_canonical_sha256": _sha_json(current_manifest),
            "current_manifest_non_id_feature_fields_sha256": _sha_json(
                [
                    {
                        key: value
                        for key, value in feature.items()
                        if key != "official_capability_ids"
                    }
                    for feature in current_manifest["features"]
                ]
            ),
            "current_feature_capability_id_order_sha256": _sha_json(
                [
                    feature.get("official_capability_ids", [])
                    for feature in current_manifest["features"]
                ]
            ),
            "current_ledger_root_without_capabilities_sha256": _sha_json(
                {
                    key: value
                    for key, value in current_ledger.items()
                    if key != "capabilities"
                }
            ),
            "current_capability_records_ordered_sha256": _sha_json(
                current_ledger["capabilities"]
            ),
            "current_source_discrepancies_ordered_sha256": _sha_json(
                current_ledger["source_discrepancies"]
            ),
            "current_runtime_state_projection_sha256": _sha_json(
                current_runtime_projection
            ),
            "current_manifest_evidence_field_count": len(manifest_evidence_fields),
            "current_manifest_evidence_fields_sha256": _sha_json(
                manifest_evidence_fields
            ),
            "candidate_append_order_sha256": _sha_json(append_order),
            "candidate_capability_records_ordered_sha256": _sha_json(
                projected_ledger["capabilities"][289:]
            ),
            "projected_capability_records_ordered_sha256": _sha_json(
                projected_ledger["capabilities"]
            ),
            "projected_oracle_capability_order_sha256": oracle_500_order_sha256,
            "projected_oracle_records_canonical_sha256": _sha_json(projected_oracles),
            **oracle_preservation,
        },
        "source_claim_hash_projection": {
            "algorithm": "verify_official_capabilities_claim_set_v1",
            "changed_source_ids": changed_source_ids,
            "unchanged_source_ids": unchanged_source_ids,
            "transition_rows_sha256": _sha_json(source_claim_transitions),
            "transitions": source_claim_transitions,
        },
        "merge_readiness": {
            "live_merge_ready": False,
            "verifier_blocker_categories": [
                "family_status_aggregate_drift",
                "acceptance_scenario_coverage_gaps",
            ],
            "blockers": merge_blockers,
            "reviewed_nonblocking_distinctions": reviewed_distinctions,
        },
        "artifacts": {
            "projected_manifest": {
                "path": str(MANIFEST_OUTPUT.relative_to(REPO_ROOT)),
                "raw_sha256": _sha_bytes(manifest_encoded),
                "canonical_sha256": _sha_json(projected_manifest),
            },
            "projected_official_capabilities": {
                "path": str(LEDGER_OUTPUT.relative_to(REPO_ROOT)),
                "raw_sha256": _sha_bytes(ledger_encoded),
                "canonical_sha256": _sha_json(projected_ledger),
            },
        },
        "candidate_append_order": append_order,
    }
    proof["projection_payload_sha256"] = _sha_json(proof)
    validate_projection(
        proof,
        projected_manifest,
        projected_ledger,
        current_manifest=current_manifest,
        current_ledger=current_ledger,
        official_schema=official_schema,
        manifest_schema=manifest_schema,
    )
    return proof, projected_manifest, projected_ledger


def validate_projection(
    proof: dict[str, Any],
    projected_manifest: dict[str, Any],
    projected_ledger: dict[str, Any],
    *,
    current_manifest: dict[str, Any] | None = None,
    current_ledger: dict[str, Any] | None = None,
    official_schema: dict[str, Any] | None = None,
    manifest_schema: dict[str, Any] | None = None,
) -> None:
    proof_schema = _load_schema(PROOF_SCHEMA, PROOF_SCHEMA_RAW_SHA256)
    _validate(proof, proof_schema, "projection proof")
    payload = dict(proof)
    observed = payload.pop("projection_payload_sha256")
    if observed != _sha_json(payload):
        raise ProjectionError("projection payload digest mismatch")
    if EXPECTED_PROOF_PAYLOAD_SHA256 != observed:
        raise ProjectionError("projection payload lock drift")
    if current_manifest is None or current_ledger is None or official_schema is None:
        current_manifest = _load_locked(
            INPUTS["manifest"]["path"], INPUTS["manifest"]["raw_sha256"]
        )[0]
        current_ledger = _load_locked(
            INPUTS["official_capabilities"]["path"],
            INPUTS["official_capabilities"]["raw_sha256"],
        )[0]
        official_schema = _load_locked(
            INPUTS["official_capabilities_schema"]["path"],
            INPUTS["official_capabilities_schema"]["raw_sha256"],
        )[0]
    if manifest_schema is None:
        manifest_schema = _load_schema(MANIFEST_SCHEMA, MANIFEST_SCHEMA_RAW_SHA256)
    _verify_projection(
        current_manifest,
        current_ledger,
        projected_manifest,
        projected_ledger,
        proof["candidate_append_order"],
        official_schema,
        manifest_schema,
    )
    expected_manifest = proof["artifacts"]["projected_manifest"]
    expected_ledger = proof["artifacts"]["projected_official_capabilities"]
    if (
        expected_manifest["raw_sha256"] != _sha_bytes(_encoded(projected_manifest))
        or expected_manifest["canonical_sha256"] != _sha_json(projected_manifest)
        or expected_ledger["raw_sha256"] != _sha_bytes(_encoded(projected_ledger))
        or expected_ledger["canonical_sha256"] != _sha_json(projected_ledger)
    ):
        raise ProjectionError("projected artifact binding drift")


def _atomic_write(path: Path, payload: bytes) -> None:
    if path.parent.is_symlink() or not path.parent.is_dir():
        raise ProjectionError(f"unsafe output parent: {path.parent}")
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ProjectionError(f"unsafe output path: {path}")
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
        if temporary.is_symlink() or not temporary.is_file():
            raise ProjectionError(f"unsafe temporary output: {temporary}")
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    try:
        proof, projected_manifest, projected_ledger = compile_projection()
        outputs = {
            MANIFEST_OUTPUT: _encoded(projected_manifest),
            LEDGER_OUTPUT: _encoded(projected_ledger),
            PROOF_OUTPUT: _encoded(proof),
        }
        if args.write:
            for path, payload in outputs.items():
                _atomic_write(path, payload)
                print(f"WROTE: {path.relative_to(REPO_ROOT)}")
            return 0
        expected_raw = {
            PROOF_OUTPUT: EXPECTED_PROOF_RAW_SHA256,
            MANIFEST_OUTPUT: EXPECTED_MANIFEST_RAW_SHA256,
            LEDGER_OUTPUT: EXPECTED_LEDGER_RAW_SHA256,
        }
        for path, payload in outputs.items():
            if path.is_symlink() or not path.is_file():
                raise ProjectionError(f"checked output is missing or unsafe: {path}")
            if (
                _sha_bytes(path.read_bytes()) != expected_raw[path]
                or path.read_bytes() != payload
            ):
                raise ProjectionError(f"checked output differs: {path.name}")
        print(
            "PASS: isolated ledger successor; current=289, appended=211, projected=500, "
            "exact=500, missing=0, ambiguous=0, evidence=0, promoted=0"
        )
        return 0
    except (
        ProjectionError,
        KeyError,
        IndexError,
        TypeError,
        ValueError,
        OSError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
