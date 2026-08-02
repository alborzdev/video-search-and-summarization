#!/usr/bin/env python3
"""Compile an isolated Metadata-500 migration rebase successor."""

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
LEDGER_OUTPUT = PACKAGE / "post-state-official-capabilities.json"
MANIFEST_OUTPUT = PACKAGE / "post-state-manifest.json"
ACCEPTANCE_OUTPUT = PACKAGE / "post-state-acceptance-inventory.json"
ORACLE_OUTPUT = PACKAGE / "post-state-capability-oracles.json"
ORACLE_SCHEMA_OUTPUT = PACKAGE / "post-state-capability-oracles.schema.json"
PROOF_OUTPUT = PACKAGE / "migration.json"
PROOF_SCHEMA_OUTPUT = PACKAGE / "migration.schema.json"
MAX_JSON_BYTES = 64_000_000

INPUTS = {
    "live_manifest": (
        "deploy/docker/thor-local/parity/manifest.json",
        "1f56d63437bd7742cf7488b9bd85b25fc886cdaf39a3c2b46aabecbc6b7201ce",
    ),
    "live_ledger": (
        "deploy/docker/thor-local/parity/official-capabilities.json",
        "61c2a4c0bc9d23940d954311f93824dc55c18cfc58caca002162cc1ef6808098",
    ),
    "live_acceptance": (
        "deploy/docker/thor-local/qualification/acceptance_inventory.json",
        "79001985f9cc9d0dbb64adea2a014aaedacd0b0411d8becb5b311c8697a563a5",
    ),
    "live_oracles": (
        "deploy/docker/thor-local/parity/capability-oracles.json",
        "24214553cbd669eb80efa7b4a602ac52328e00bd43241c839b43b10d05e22e8e",
    ),
    "live_oracle_schema": (
        "deploy/docker/thor-local/parity/capability-oracles.schema.json",
        "55de87c13e78b4f349e7095232f31c1135155e0bc13ed6bcb8e4abb906f26cf1",
    ),
    "live_oracle_validator": (
        "deploy/docker/thor-local/parity/capability_oracles.py",
        "32f18f2d74508a78282cf572c00ba5f7b739b7b0969019f963e04372e791de1c",
    ),
    "official_verifier": (
        "deploy/docker/thor-local/parity/verify_official_capabilities.py",
        "c21fd2910089c6981f0437d41d6c9ef7fff19d55c0153b04b7f7f91b00d79109",
    ),
    "projected_ledger": (
        "deploy/docker/thor-local/qualification/ledger-500-successor/projected-official-capabilities.json",
        "8a6e14b35ce73362bc8c3dccc84788ab48a2e3f88284b41f1b4a6efc30cd7d13",
    ),
    "official_schema": (
        "deploy/docker/thor-local/parity/official-capabilities.schema.json",
        "fb817586b9a37ad7975ca820f69a7f2c6e575bca9f8d8686701d5fa0bf505896",
    ),
    "projected_manifest": (
        "deploy/docker/thor-local/qualification/manifest-500-aggregate-successor/projected-manifest.json",
        "c71f75246fc1e4cbc388f93849d27c3b7dc7edf2d0a516fb3fa13f6d412a4a93",
    ),
    "projected_manifest_schema": (
        "deploy/docker/thor-local/qualification/manifest-500-aggregate-successor/projected-manifest.schema.json",
        "95d981d86879a2ac6e5a69c2f0a2c154d826f54ce15d87f773c0048f39c7ed48",
    ),
    "projected_acceptance": (
        "deploy/docker/thor-local/qualification/acceptance-500-successor/projected-acceptance-inventory.json",
        "69dc4aca160ae236880f9afe7b873c0b3b423f8981c5d934e4ed647043cd8cb0",
    ),
    "projected_acceptance_schema": (
        "deploy/docker/thor-local/qualification/acceptance-500-successor/projected-acceptance-inventory.schema.json",
        "848d84b976906c3059b67218cf1d6bf3960b8b91c620c663bba398f5b302278a",
    ),
    "projected_oracle_successor": (
        "deploy/docker/thor-local/qualification/oracle-500-successor/capability-oracles-500.json",
        "e682282735476830659582bd551fddc3e140580324e856ceaea4507ca5e706c2",
    ),
    "projected_oracle_successor_schema": (
        "deploy/docker/thor-local/qualification/oracle-500-successor/capability-oracles-500.schema.json",
        "759c36ade481c6024815df95738a7fca13e92c66ae70649154bb7cb85b439057",
    ),
    "composition": (
        "deploy/docker/thor-local/qualification/metadata-500-composition-successor/composition.json",
        "8db4dea3425fc0ea1252e6ceac40d32aef9fda41546b14661e79f1bdefe801f2",
    ),
    "composition_schema": (
        "deploy/docker/thor-local/qualification/metadata-500-composition-successor/composition.schema.json",
        "126896936bd45a7eebf0baa09e93986932993aa75317ba51de474d9612e65370",
    ),
}

JSON_INPUTS = set(INPUTS) - {"live_oracle_validator", "official_verifier"}
EXPECTED = {
    "ledger": "8a6e14b35ce73362bc8c3dccc84788ab48a2e3f88284b41f1b4a6efc30cd7d13",
    "manifest": "c71f75246fc1e4cbc388f93849d27c3b7dc7edf2d0a516fb3fa13f6d412a4a93",
    "acceptance": "69dc4aca160ae236880f9afe7b873c0b3b423f8981c5d934e4ed647043cd8cb0",
    "oracles": "911c38e2db0f92bdcc46938c90bac67626ef1009a4e131f1feee5538dcbee021",
    "oracle_schema": "b24308d9647ff7a4c7b66cc91881749eaaa84c21ab7423677fc30ab4f9c36233",
    "proof": "771336f0f843686ee380467a2772a0e6ad4bef9155fe9d511ce738f9e822189c",
    "proof_schema": "45c41fc02b60fa466689ab2ece0e87487287a20e3d247ba0f62293c649a349c0",
    "proof_payload": "408ae46b8863e8f2161018b928303ff85ceb803eb02c7e976dd599186dbc2582",
}

PREDECESSOR_INPUTS = {
    "readme": (
        "deploy/docker/thor-local/qualification/live-metadata-500-migration/README.md",
        "2143af777b5a67523ff226ddef8aaa54897ef1c200a23966b6011923d2c50526",
    ),
    "evidence": (
        "deploy/docker/thor-local/qualification/live-metadata-500-migration/EVIDENCE.md",
        "55d64391c59b65752a95b37f03945d8a24f60a2eeef53db3cacfeb6f91f8bfe8",
    ),
    "compiler": (
        "deploy/docker/thor-local/qualification/live-metadata-500-migration/compiler.py",
        "d1eb9d0e59f9939b63f1ff61768747297cc38e65ebdaa4675b2f378616d11f0a",
    ),
    "tests": (
        "deploy/docker/thor-local/qualification/live-metadata-500-migration/tests/test_compiler.py",
        "5774c8b3680a0f11bc4be16548807ee65caea7c19dbd088943e7895b6f8c67f4",
    ),
    "proof": (
        "deploy/docker/thor-local/qualification/live-metadata-500-migration/migration.json",
        "39ec1db0d4e42c7d39c237f647f80c15dff12cea15630ef3e8572bf5e32dac0d",
    ),
    "proof_schema": (
        "deploy/docker/thor-local/qualification/live-metadata-500-migration/migration.schema.json",
        "786b095f40510e87e76405d0b06e3aae63f50530670d9a8453d5d5dee9b47eb7",
    ),
    "manifest": (
        "deploy/docker/thor-local/qualification/live-metadata-500-migration/post-state-manifest.json",
        "c71f75246fc1e4cbc388f93849d27c3b7dc7edf2d0a516fb3fa13f6d412a4a93",
    ),
    "ledger": (
        "deploy/docker/thor-local/qualification/live-metadata-500-migration/post-state-official-capabilities.json",
        "f1e63b25c607a09f19a3c53aa47d8d152c61ffbd330440b93d54eccfaa49add6",
    ),
    "acceptance": (
        "deploy/docker/thor-local/qualification/live-metadata-500-migration/post-state-acceptance-inventory.json",
        "69dc4aca160ae236880f9afe7b873c0b3b423f8981c5d934e4ed647043cd8cb0",
    ),
    "oracles": (
        "deploy/docker/thor-local/qualification/live-metadata-500-migration/post-state-capability-oracles.json",
        "17091a3c0e9ac4d3aba7b5c6d91f09c8832648f149ac0624f3b63cd2c5e77271",
    ),
    "oracle_schema": (
        "deploy/docker/thor-local/qualification/live-metadata-500-migration/post-state-capability-oracles.schema.json",
        "b24308d9647ff7a4c7b66cc91881749eaaa84c21ab7423677fc30ab4f9c36233",
    ),
    "selector": (
        "deploy/docker/thor-local/parity/metadata_sets/selector.json",
        "8021efc4684b106539a627b3ddfd82937c7ecf1d6111a3c87538fc5ea7360bec",
    ),
    "descriptor": (
        "deploy/docker/thor-local/parity/metadata_sets/sets/thor-vss-3.2.1-metadata-500-staged.json",
        "56ed8f555c0814e80a39c15198a33c80d400c991a4857a27b4609ea88b5750f9",
    ),
}

PREDECESSOR_JSON_INPUTS = {
    "proof",
    "proof_schema",
    "manifest",
    "ledger",
    "acceptance",
    "oracles",
    "oracle_schema",
    "selector",
    "descriptor",
}

PREDECESSOR_MEMBERS = {
    "manifest": ("manifest", MANIFEST_OUTPUT),
    "ledger": ("ledger", LEDGER_OUTPUT),
    "acceptance": ("acceptance", ACCEPTANCE_OUTPUT),
    "oracles": ("oracles", ORACLE_OUTPUT),
    "oracle_schema": ("oracle_schema", ORACLE_SCHEMA_OUTPUT),
}


class MigrationError(RuntimeError):
    """A source lock, post-state invariant, or safe-output rule failed."""


def pending_final_locks() -> list[str]:
    """Return unpinned final-chain inputs and outputs in stable order."""
    sha256 = re.compile(r"[0-9a-f]{64}").fullmatch
    pending = [
        f"input:{source_id}"
        for source_id, (_, digest) in sorted(INPUTS.items())
        if sha256(digest) is None
    ]
    pending.extend(
        f"expected:{artifact_id}"
        for artifact_id, digest in sorted(EXPECTED.items())
        if sha256(digest) is None
    )
    return pending


def _require_final_locks() -> None:
    pending = pending_final_locks()
    if pending:
        raise MigrationError(
            "final source/output locks are not pinned: " + ", ".join(pending)
        )


def _sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha_json(value: Any) -> str:
    return _sha_bytes(
        json.dumps(
            value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode()
    )


def _git_blob_oid(payload: bytes) -> str:
    return hashlib.sha1(f"blob {len(payload)}\0".encode() + payload).hexdigest()


def _encoded(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    ).encode()


def _strict_json(payload: bytes, label: str) -> Any:
    if len(payload) > MAX_JSON_BYTES:
        raise MigrationError(f"oversized JSON input: {label}")

    def pairs(rows: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in rows:
            if key in result:
                raise MigrationError(f"duplicate JSON key in {label}: {key}")
            result[key] = value
        return result

    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                MigrationError(f"non-finite JSON number in {label}: {value}")
            ),
        )
    except MigrationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MigrationError(f"invalid UTF-8 JSON in {label}: {exc}") from exc


def _repo_file(relative: str) -> Path:
    path = Path(relative)
    if not relative or path.is_absolute() or ".." in path.parts:
        raise MigrationError(f"unsafe repository path: {relative}")
    current = REPO_ROOT
    for part in path.parts:
        current /= part
        try:
            mode = current.lstat().st_mode
        except OSError as exc:
            raise MigrationError(f"missing repository input: {relative}") from exc
        if stat.S_ISLNK(mode):
            raise MigrationError(f"repository input contains symlink: {relative}")
    try:
        current.resolve(strict=True).relative_to(REPO_ROOT)
    except (OSError, RuntimeError, ValueError) as exc:
        raise MigrationError(f"repository input escapes root: {relative}") from exc
    if not stat.S_ISREG(current.lstat().st_mode):
        raise MigrationError(f"repository input is not regular: {relative}")
    return current


def _load_sources() -> tuple[
    dict[str, Any], dict[str, bytes], dict[str, dict[str, str]]
]:
    documents: dict[str, Any] = {}
    payloads: dict[str, bytes] = {}
    locks: dict[str, dict[str, str]] = {}
    for source_id, (relative, expected) in INPUTS.items():
        payload = _repo_file(relative).read_bytes()
        digest = _sha_bytes(payload)
        if digest != expected:
            raise MigrationError(f"raw source digest drift: {relative}")
        payloads[source_id] = payload
        documents[source_id] = (
            _strict_json(payload, relative) if source_id in JSON_INPUTS else payload
        )
        locks[source_id] = {"path": relative, "raw_sha256": digest}
    return documents, payloads, locks


def _load_predecessors() -> tuple[
    dict[str, Any], dict[str, bytes], dict[str, dict[str, str]]
]:
    """Load the immutable predecessor package and selected metadata pair."""
    documents: dict[str, Any] = {}
    payloads: dict[str, bytes] = {}
    locks: dict[str, dict[str, str]] = {}
    for source_id, (relative, expected) in sorted(PREDECESSOR_INPUTS.items()):
        payload = _repo_file(relative).read_bytes()
        digest = _sha_bytes(payload)
        if digest != expected:
            raise MigrationError(f"predecessor digest drift: {relative}")
        payloads[source_id] = payload
        document = (
            _strict_json(payload, relative)
            if source_id in PREDECESSOR_JSON_INPUTS
            else payload
        )
        documents[source_id] = document
        lock = {
            "path": relative,
            "raw_sha256": digest,
            "git_blob_oid": _git_blob_oid(payload),
        }
        if source_id in PREDECESSOR_JSON_INPUTS:
            lock["canonical_sha256"] = _sha_json(document)
        locks[source_id] = lock
    return documents, payloads, locks


def _validate_applied_selection(
    documents: dict[str, Any], locks: dict[str, dict[str, str]]
) -> dict[str, Any]:
    """Prove that the applied selector/descriptor binds the predecessor members."""
    selector = documents["selector"]
    descriptor = documents["descriptor"]
    set_id = descriptor.get("set_id")
    available = {
        row.get("set_id"): row for row in selector.get("available_sets", [])
    }
    selected = available.get(selector.get("selected_set"))
    if (
        not isinstance(set_id, str)
        or selector.get("selected_set") != set_id
        or not isinstance(selected, dict)
        or selected.get("descriptor_path") != locks["descriptor"]["path"]
        or selected.get("descriptor_raw_sha256")
        != locks["descriptor"]["raw_sha256"]
    ):
        raise MigrationError("applied selector does not bind the locked descriptor")
    if (
        descriptor.get("mode") != "immutable_static_metadata_set"
        or descriptor.get("lifecycle") != "live_ready"
        or descriptor.get("expected_counts")
        != {"capabilities": 500, "oracles": 500, "feature_families": 55}
    ):
        raise MigrationError("applied descriptor lifecycle or denominator drift")
    expected_documents = {
        "manifest": "manifest",
        "official_capabilities": "ledger",
        "capability_oracles": "oracles",
        "acceptance_inventory": "acceptance",
    }
    bound_documents = descriptor.get("documents", {})
    for descriptor_id, predecessor_id in expected_documents.items():
        binding = bound_documents.get(descriptor_id, {})
        if (
            binding.get("path") != locks[predecessor_id]["path"]
            or binding.get("raw_sha256")
            != locks[predecessor_id]["raw_sha256"]
        ):
            raise MigrationError(
                f"applied descriptor member binding drift: {descriptor_id}"
            )
    oracle_schema = descriptor.get("schemas", {}).get(
        "capability_oracles_schema", {}
    )
    if (
        oracle_schema.get("path") != locks["oracle_schema"]["path"]
        or oracle_schema.get("raw_sha256")
        != locks["oracle_schema"]["raw_sha256"]
    ):
        raise MigrationError("applied descriptor oracle schema binding drift")
    return {
        "set_id": set_id,
        "selector_path": locks["selector"]["path"],
        "selector_raw_sha256": locks["selector"]["raw_sha256"],
        "descriptor_path": locks["descriptor"]["path"],
        "descriptor_raw_sha256": locks["descriptor"]["raw_sha256"],
        "predecessor_member_ids": list(expected_documents),
    }


def _validate(value: Any, schema: dict[str, Any], label: str) -> None:
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda e: tuple(map(str, e.absolute_path)),
    )
    if errors:
        error = errors[0]
        location = "/" + "/".join(map(str, error.absolute_path))
        raise MigrationError(f"{label} schema error at {location}: {error.message}")


def _unique(
    rows: list[dict[str, Any]], key: str, label: str
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        identity = row.get(key)
        if not isinstance(identity, str) or not identity or identity in result:
            raise MigrationError(f"missing or duplicate {label}: {identity!r}")
        result[identity] = row
    return result


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


def _derive_status(group: list[dict[str, Any]]) -> dict[str, str]:
    classes = {row["acceptance_class"] for row in group}
    acceptance = (
        "required_local"
        if "required_local" in classes
        else "external_optional"
        if classes == {"external_optional"}
        else "alternate_local_lane"
    )
    thor = {row["thor_state"] for row in group}
    runtime = {row["runtime_state"] for row in group}
    return {
        "acceptance_class": acceptance,
        "thor_state": "external_optional"
        if acceptance == "external_optional"
        else next(iter(thor))
        if len(thor) == 1
        else "partial",
        "runtime_state": next(iter(runtime)) if len(runtime) == 1 else "not_qualified",
    }


def _aggregate_drift(manifest: dict[str, Any], ledger: dict[str, Any]) -> list[str]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in ledger["capabilities"]:
        groups.setdefault(row["feature_id"], []).append(row)
    return [
        feature["id"]
        for feature in manifest["features"]
        if any(
            feature[field] != _derive_status(groups[feature["id"]])[field]
            for field in ("acceptance_class", "thor_state", "runtime_state")
        )
    ]


def _coverage_gaps(
    ledger: dict[str, Any], acceptance: dict[str, Any]
) -> list[dict[str, Any]]:
    scenario_ids = set(_unique(acceptance["scenarios"], "id", "scenario"))
    coverage = _unique(
        acceptance["coverage"]["features"], "feature_id", "feature coverage"
    )
    required: dict[str, set[str]] = {}
    for capability in ledger["capabilities"]:
        linked = capability["scenario_ids"]
        if len(linked) != len(set(linked)) or not set(linked) <= scenario_ids:
            raise MigrationError(f"{capability['id']}: scenario identity drift")
        required.setdefault(capability["feature_id"], set()).update(linked)
    return [
        {
            "feature_id": feature_id,
            "missing_scenario_ids": sorted(
                ids - set(coverage[feature_id]["scenario_ids"])
            ),
        }
        for feature_id, ids in required.items()
        if ids - set(coverage[feature_id]["scenario_ids"])
    ]


def _build_oracle_registry(documents: dict[str, Any]) -> dict[str, Any]:
    live = documents["live_oracles"]
    successor = documents["projected_oracle_successor"]
    projected = successor["projected_oracles"]
    if projected[:289] != live["oracles"] or len(projected) != 500:
        raise MigrationError(
            "oracle successor does not preserve the exact live 289-row prefix"
        )
    return {
        "schema_version": 2,
        "target": copy.deepcopy(successor["target"]),
        "policy": copy.deepcopy(live["policy"]),
        "oracles": copy.deepcopy(projected),
    }


def _rewrite_refs(value: Any, prefix: str) -> Any:
    """Copy a schema fragment while namespacing its local definition refs."""
    if isinstance(value, dict):
        return {
            key: (
                f"#/$defs/{prefix}{item.removeprefix('#/$defs/')}"
                if key == "$ref"
                and isinstance(item, str)
                and item.startswith("#/$defs/")
                else _rewrite_refs(item, prefix)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_rewrite_refs(item, prefix) for item in value]
    return copy.deepcopy(value)


def _oracle_v2_schema(documents: dict[str, Any]) -> dict[str, Any]:
    """Build a compact, self-contained strict union schema for the live v2 root."""
    live_schema = documents["live_oracle_schema"]
    successor_schema = documents["projected_oracle_successor_schema"]
    definitions = {
        **{
            f"live_{name}": _rewrite_refs(value, "live_")
            for name, value in live_schema["$defs"].items()
        },
        **{
            f"candidate_{name}": _rewrite_refs(value, "candidate_")
            for name, value in successor_schema["$defs"].items()
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://developer.nvidia.com/vss/thor-local/live-capability-oracles-v2.schema.json",
        "title": "Strict VSS live v2 capability oracle registry",
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "target", "policy", "oracles"],
        "properties": {
            "schema_version": {"const": 2},
            "target": copy.deepcopy(live_schema["properties"]["target"]),
            "policy": copy.deepcopy(live_schema["properties"]["policy"]),
            "oracles": {
                "type": "array",
                "minItems": 500,
                "maxItems": 500,
                "items": {
                    "oneOf": [
                        {"$ref": "#/$defs/live_oracle"},
                        {"$ref": "#/$defs/candidate_candidateSuccessorOracle"},
                    ]
                },
            },
        },
        "$defs": definitions,
    }


def _validate_post_state(
    documents: dict[str, Any], registry: dict[str, Any]
) -> dict[str, Any]:
    ledger = documents["projected_ledger"]
    manifest = documents["projected_manifest"]
    acceptance = documents["projected_acceptance"]
    oracles = registry["oracles"]
    capabilities = ledger["capabilities"]
    if (
        len(capabilities),
        len(oracles),
        len(manifest["features"]),
        len(acceptance["coverage"]["features"]),
    ) != (500, 500, 55, 55):
        raise MigrationError("post-state denominator drift")
    capability_ids = [row["id"] for row in capabilities]
    oracle_ids = [row["capability_id"] for row in oracles]
    if capability_ids != oracle_ids or len(set(capability_ids)) != 500:
        raise MigrationError("ledger/oracle identity or order drift")
    for capability, oracle in zip(capabilities, oracles, strict=True):
        if oracle["ledger_binding"] != _ledger_binding(capability):
            raise MigrationError(f"{capability['id']}: oracle ledger binding drift")
    candidates = capabilities[289:]
    candidate_oracles = oracles[289:]
    if any("runtime_evidence" in row for row in candidates):
        raise MigrationError("candidate capability invented runtime evidence")
    for capability, oracle in zip(candidates, candidate_oracles, strict=True):
        external = capability["acceptance_class"] == "external_optional"
        alternate = capability["acceptance_class"] == "alternate_local_lane"
        if capability["runtime_state"] != (
            "not_applicable" if external else "not_qualified"
        ):
            raise MigrationError(
                f"{capability['id']}: candidate runtime state advanced"
            )
        expected_boundary = (
            "external" if external else "alternate_local" if alternate else "local"
        )
        expected_network = (
            "operator_approved_external_only"
            if external
            else "operator_selected_local_alternate"
            if alternate
            else "loopback_or_compose_internal"
        )
        expected_state = (
            "external_boundary_unexecuted" if external else "open_unexecuted"
        )
        if (
            oracle.get("successor_schema_version") != 1
            or oracle.get("origin") != "candidate_successor_planning_only"
            or oracle.get("acceptance_class") != capability["acceptance_class"]
            or oracle.get("runtime_state") != capability["runtime_state"]
            or oracle.get("feature_id") != capability["feature_id"]
            or oracle.get("source_claims") != capability["source_claims"]
            or oracle.get("implementation_surfaces")
            != capability["contract"]["implementation_surfaces"]
            or oracle.get("manifest_pointer")
            != capability["contract"]["manifest_pointer"]
            or oracle.get("advertised") != capability["contract"]["advertised_literal"]
            or oracle.get("oracle_id") != f"oracle.{capability['id']}"
            or oracle.get("fixture", {}).get("id") != f"fixture.{capability['id']}"
            or oracle.get("reviewed_scenario_ids", [])[-1:]
            != [f"oracle.{capability['id']}"]
            or oracle.get("profile") != oracle.get("profile_seed")
            or oracle.get("mode") != oracle.get("mode_seed")
            or oracle.get("readiness")
            != {
                "blockers": [
                    "fixture_not_materialized",
                    "executor_not_implemented",
                    "collectors_not_implemented",
                    "operator_approval_absent",
                ],
                "classification": "planning_index_only",
                "executor_ready": False,
                "fixture_materialized": False,
            }
            or oracle.get("can_promote_runtime_state") is not False
            or oracle.get("evidence") != []
            or oracle.get("fixture", {}).get("materialization") is not None
            or oracle.get("fixture", {}).get("namespace")
            != oracle.get("execution_bounds", {}).get("namespace")
            or oracle.get("execution_bounds", {}).get("executor") is not None
            or oracle.get("execution_bounds", {}).get("collectors") is not None
            or oracle.get("execution_bounds", {}).get("max_actions") is not None
            or oracle.get("execution_bounds", {}).get("max_duration_seconds")
            is not None
            or oracle.get("execution_bounds", {}).get("max_requests") is not None
            or oracle.get("execution_bounds", {}).get("acceptance_class")
            != capability["acceptance_class"]
            or oracle.get("execution_bounds", {}).get("execution_boundary")
            != expected_boundary
            or oracle.get("execution_bounds", {}).get("network_scope")
            != expected_network
            or any(
                oracle.get("cleanup", {}).get(key) is not None
                for key in (
                    "targets",
                    "allowlist",
                    "executor",
                    "postcondition_collectors",
                )
            )
        ):
            raise MigrationError(
                f"{capability['id']}: candidate oracle implies activation"
            )
        operator_gates = [
            gate
            for gate in oracle.get("admission_gates", [])
            if gate.get("id") == "operator-approval"
        ]
        if operator_gates != [
            {
                "id": "operator-approval",
                "requirement": "explicit approval exists before any runtime or external activity",
                "status": "unmet",
            }
        ]:
            raise MigrationError(f"{capability['id']}: operator approval gate drift")
        observation_ids = {
            row["id"]
            for row in oracle.get("expected_observations", [])
            + oracle.get("adjacent_negative_observations", [])
        }
        if any(
            row.get("observation_id") not in observation_ids
            for row in oracle.get("assertions", [])
        ):
            raise MigrationError(f"{capability['id']}: dangling assertion reference")
        if (
            oracle["execution_boundary"] != expected_boundary
            or oracle["current_state"] != expected_state
        ):
            raise MigrationError(f"{capability['id']}: candidate boundary drift")
        protocol = oracle.get("protocol_v2_binding")
        workload = oracle.get("workload_binding")
        if capability["kind"] == "protocol":
            if (
                not isinstance(protocol, dict)
                or workload is not None
                or protocol.get("capability_id") != capability["id"]
                or protocol.get("activation_supported") is not False
                or protocol.get("readiness") != "planning_only"
                or protocol.get("boundary") != expected_boundary
                or protocol.get("vector_projection", {}).get("contract")
                != oracle["candidate_oracle_plan"]
            ):
                raise MigrationError(
                    f"{capability['id']}: protocol planning binding drift"
                )
        elif capability["kind"] in {"api", "deployment"}:
            if (
                protocol is not None
                or not isinstance(workload, dict)
                or workload.get("workload_type") != capability["kind"]
                or workload.get("candidate_id") != capability["id"]
                or workload.get("acceptance_class") != capability["acceptance_class"]
                or workload.get("manifest_pointer")
                != capability["contract"]["manifest_pointer"]
                or workload.get("advertised")
                != capability["contract"]["advertised_literal"]
            ):
                raise MigrationError(
                    f"{capability['id']}: workload planning binding drift"
                )
        elif protocol is not None or workload is not None:
            raise MigrationError(f"{capability['id']}: unexpected planning binding")
    protocol_count = sum(
        row.get("protocol_v2_binding") is not None for row in candidate_oracles
    )
    workload_count = sum(
        row.get("workload_binding") is not None for row in candidate_oracles
    )
    if (protocol_count, workload_count) != (23, 60):
        raise MigrationError("candidate protocol/workload binding denominator drift")
    external_features = [
        row
        for row in manifest["features"]
        if row["acceptance_class"] == "external_optional"
    ]
    if len(external_features) != 8 or any(
        row["thor_state"] != "external_optional"
        or row["runtime_state"] != "not_applicable"
        for row in external_features
    ):
        raise MigrationError("external manifest family boundary drift")
    if _aggregate_drift(manifest, ledger) or _coverage_gaps(ledger, acceptance):
        raise MigrationError("post-state aggregate or acceptance drift")
    return {
        "candidate_acceptance_class_counts": dict(
            sorted(Counter(row["acceptance_class"] for row in candidates).items())
        ),
        "candidate_thor_state_counts": dict(
            sorted(Counter(row["thor_state"] for row in candidates).items())
        ),
        "candidate_runtime_state_counts": dict(
            sorted(Counter(row["runtime_state"] for row in candidates).items())
        ),
        "candidate_oracle_state_counts": dict(
            sorted(Counter(row["current_state"] for row in candidate_oracles).items())
        ),
        "candidate_protocol_binding_count": protocol_count,
        "candidate_workload_binding_count": workload_count,
    }


def _exact_schema(value: Any, schema_id: str, title: str) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": schema_id,
        "title": title,
        "const": value,
    }


def compile_migration() -> tuple[dict[str, Any], dict[str, Any], dict[Path, bytes]]:
    _require_final_locks()
    documents, source_payloads, source_locks = _load_sources()
    predecessor_documents, predecessor_payloads, predecessor_locks = (
        _load_predecessors()
    )
    applied_selection = _validate_applied_selection(
        predecessor_documents, predecessor_locks
    )
    for schema_name in (
        "official_schema",
        "projected_manifest_schema",
        "projected_acceptance_schema",
        "projected_oracle_successor_schema",
        "composition_schema",
    ):
        try:
            Draft202012Validator.check_schema(documents[schema_name])
        except SchemaError as exc:
            raise MigrationError(
                f"invalid locked schema {schema_name}: {exc.message}"
            ) from exc
    _validate(
        documents["projected_ledger"], documents["official_schema"], "projected ledger"
    )
    _validate(
        documents["projected_manifest"],
        documents["projected_manifest_schema"],
        "projected manifest",
    )
    _validate(
        documents["projected_acceptance"],
        documents["projected_acceptance_schema"],
        "projected acceptance",
    )
    _validate(
        documents["projected_oracle_successor"],
        documents["projected_oracle_successor_schema"],
        "oracle successor",
    )
    _validate(documents["composition"], documents["composition_schema"], "composition")
    if documents["composition"]["authoritative_validation"]["result"] != "passed":
        raise MigrationError("composition is not authoritative-validation passed")

    registry = _build_oracle_registry(documents)
    counts = _validate_post_state(documents, registry)
    oracle_schema = _oracle_v2_schema(documents)
    _validate(registry, oracle_schema, "post-state oracle registry")
    outputs = {
        LEDGER_OUTPUT: source_payloads["projected_ledger"],
        MANIFEST_OUTPUT: source_payloads["projected_manifest"],
        ACCEPTANCE_OUTPUT: source_payloads["projected_acceptance"],
        ORACLE_OUTPUT: _encoded(registry),
        ORACLE_SCHEMA_OUTPUT: _encoded(oracle_schema),
    }
    journal = []
    for artifact_id, (predecessor_id, output_path) in PREDECESSOR_MEMBERS.items():
        before = predecessor_payloads[predecessor_id]
        after = outputs[output_path]
        after_doc = _strict_json(after, str(output_path.relative_to(REPO_ROOT)))
        journal.append(
            {
                "artifact_id": artifact_id,
                "predecessor_path": predecessor_locks[predecessor_id]["path"],
                "successor_path": str(output_path.relative_to(REPO_ROOT)),
                "changed": before != after,
                "before": {
                    "raw_sha256": _sha_bytes(before),
                    "canonical_sha256": _sha_json(
                        predecessor_documents[predecessor_id]
                    ),
                    "git_blob_oid": _git_blob_oid(before),
                },
                "after": {
                    "raw_sha256": _sha_bytes(after),
                    "canonical_sha256": _sha_json(after_doc),
                    "git_blob_oid": _git_blob_oid(after),
                },
            }
        )
    changed_member_ids = [row["artifact_id"] for row in journal if row["changed"]]
    unchanged_member_ids = [
        row["artifact_id"] for row in journal if not row["changed"]
    ]
    all_source_locks = {
        **source_locks,
        **{
            f"predecessor_{source_id}": lock
            for source_id, lock in predecessor_locks.items()
        },
    }
    proof: dict[str, Any] = {
        "schema_version": 1,
        "migration_id": "vss-3.2.1-thor-metadata-500-rebase-successor",
        "mode": "isolated_non_applying_rebase_successor",
        "source_locks": all_source_locks,
        "predecessor_lock_map_sha256": _sha_json(
            {
                source_id: predecessor_locks[source_id]
                for source_id in sorted(predecessor_locks)
            }
        ),
        "applied_selection": applied_selection,
        "policy": {
            "modifies_live_files": False,
            "modifies_predecessor_package": False,
            "modifies_selector_or_descriptors": False,
            "creates_git_patch": False,
            "runtime_execution": "forbidden",
            "network_access": False,
            "docker_access": False,
            "host_inspection": False,
            "model_execution": False,
            "warehouse_sample_bundle": "excluded",
            "candidate_runtime_promotion": False,
        },
        "summary": {
            "target_file_count": 5,
            "feature_count": 55,
            "skill_count": 16,
            "capability_count": 500,
            "preserved_oracle_count": 289,
            "candidate_oracle_count": 211,
            "aggregate_drift_count": 0,
            "acceptance_coverage_gap_count": 0,
            "candidate_runtime_evidence_count": 0,
            "candidate_executor_count": 0,
            "candidate_materialization_count": 0,
            "candidate_promotable_count": 0,
            "external_candidate_count": 6,
            "external_manifest_family_count": 8,
            "changed_member_count": len(changed_member_ids),
            "unchanged_member_count": len(unchanged_member_ids),
            "changed_member_ids": changed_member_ids,
            "unchanged_member_ids": unchanged_member_ids,
            **counts,
        },
        "identity_order": {
            "feature_ids_sha256": _sha_json(
                [row["id"] for row in documents["projected_manifest"]["features"]]
            ),
            "skill_ids_sha256": _sha_json(
                [row["id"] for row in documents["projected_manifest"]["skills"]]
            ),
            "coverage_feature_ids_sha256": _sha_json(
                [
                    row["feature_id"]
                    for row in documents["projected_acceptance"]["coverage"]["features"]
                ]
            ),
            "capability_ids_sha256": _sha_json(
                [row["id"] for row in documents["projected_ledger"]["capabilities"]]
            ),
            "oracle_capability_ids_sha256": _sha_json(
                [row["capability_id"] for row in registry["oracles"]]
            ),
            "preserved_oracles_sha256": _sha_json(registry["oracles"][:289]),
            "candidate_oracles_sha256": _sha_json(registry["oracles"][289:]),
        },
        "migration_journal": journal,
        "migration_journal_sha256": _sha_json(journal),
        "rollback": {
            "strategy": "retain_predecessor_and_rebind_selector_separately",
            "live_apply_authorized": False,
            "predecessor_bytes_embedded": False,
            "predecessor_git_blob_oids_recorded": True,
            "selector_or_descriptor_change_included": False,
            "partial_application_forbidden": True,
            "reverse_targets": [
                {
                    "predecessor_path": row["predecessor_path"],
                    "successor_path": row["successor_path"],
                    "restore_raw_sha256": row["before"]["raw_sha256"],
                    "restore_git_blob_oid": row["before"]["git_blob_oid"],
                }
                for row in reversed(journal)
            ],
        },
        "application_boundary": {
            "id": "selector-descriptor-rebase-successor-required",
            "detail": "Canonical descriptor and selector rebinding is outside this package and requires a separately reviewed activation rebase successor.",
        },
        "artifacts": {
            path.name: {
                "path": str(path.relative_to(REPO_ROOT)),
                "raw_sha256": _sha_bytes(payload),
            }
            for path, payload in outputs.items()
        },
    }
    proof["migration_payload_sha256"] = _sha_json(proof)
    proof_schema = _exact_schema(
        proof,
        "https://developer.nvidia.com/vss/thor-local/live-metadata-500-migration-rebase-successor.schema.json",
        "Exact VSS metadata 500 migration rebase successor proof",
    )
    outputs[PROOF_OUTPUT] = _encoded(proof)
    outputs[PROOF_SCHEMA_OUTPUT] = _encoded(proof_schema)
    return proof, proof_schema, outputs


def validate_migration(
    proof: dict[str, Any], proof_schema: dict[str, Any], outputs: dict[Path, bytes]
) -> None:
    _validate(proof, proof_schema, "migration proof")
    payload = dict(proof)
    observed = payload.pop("migration_payload_sha256")
    if observed != _sha_json(payload):
        raise MigrationError("migration payload digest mismatch")
    for path, data in outputs.items():
        artifact = proof.get("artifacts", {}).get(path.name)
        if path not in {PROOF_OUTPUT, PROOF_SCHEMA_OUTPUT} and (
            artifact is None or artifact["raw_sha256"] != _sha_bytes(data)
        ):
            raise MigrationError(f"artifact binding drift: {path.name}")


def _allowed_output_names() -> set[str]:
    return {
        LEDGER_OUTPUT.name,
        MANIFEST_OUTPUT.name,
        ACCEPTANCE_OUTPUT.name,
        ORACLE_OUTPUT.name,
        ORACLE_SCHEMA_OUTPUT.name,
        PROOF_OUTPUT.name,
        PROOF_SCHEMA_OUTPUT.name,
    }


def _expected_by_path() -> dict[Path, str]:
    return {
        LEDGER_OUTPUT: EXPECTED["ledger"],
        MANIFEST_OUTPUT: EXPECTED["manifest"],
        ACCEPTANCE_OUTPUT: EXPECTED["acceptance"],
        ORACLE_OUTPUT: EXPECTED["oracles"],
        ORACLE_SCHEMA_OUTPUT: EXPECTED["oracle_schema"],
        PROOF_OUTPUT: EXPECTED["proof"],
        PROOF_SCHEMA_OUTPUT: EXPECTED["proof_schema"],
    }


def _validate_expected(proof: dict[str, Any], outputs: dict[Path, bytes]) -> None:
    """Require exact reviewed hashes before either checking or writing outputs."""
    _require_final_locks()
    expected_by_path = _expected_by_path()
    if set(outputs) != set(expected_by_path):
        raise MigrationError("generated output denominator drift")
    for path, expected in expected_by_path.items():
        if _sha_bytes(outputs[path]) != expected:
            raise MigrationError(f"generated output hash differs from pin: {path.name}")
    if proof.get("migration_payload_sha256") != EXPECTED["proof_payload"]:
        raise MigrationError("generated proof payload differs from pin")


def _preflight_output(path: Path) -> None:
    try:
        parent = path.parent.resolve(strict=True)
    except OSError as exc:
        raise MigrationError(f"unsafe output parent: {path.parent}") from exc
    if parent != PACKAGE.resolve(strict=True) or path.name not in _allowed_output_names():
        raise MigrationError(f"output is outside the isolated package: {path}")
    if path.parent.is_symlink() or not path.parent.is_dir():
        raise MigrationError(f"unsafe output parent: {path.parent}")
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise MigrationError(f"unsafe output path: {path}")


def _stage_payload(path: Path, payload: bytes, tag: str) -> Path:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.{tag}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            os.fchmod(handle.fileno(), 0o644)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if temporary.is_symlink() or not temporary.is_file():
            raise MigrationError(f"unsafe temporary output: {temporary}")
        return temporary
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _fsync_package() -> None:
    directory = os.open(PACKAGE, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _atomic_write(path: Path, payload: bytes) -> None:
    _preflight_output(path)
    temporary = _stage_payload(path, payload, "single")
    try:
        os.replace(temporary, path)
        _fsync_package()
    finally:
        temporary.unlink(missing_ok=True)


def _transactional_write(outputs: dict[Path, bytes]) -> None:
    """Stage all seven members, then commit them with failure rollback."""
    expected_paths = {PACKAGE / name for name in _allowed_output_names()}
    if set(outputs) != expected_paths or len(outputs) != 7:
        raise MigrationError("transaction requires the exact seven package outputs")
    ordered = [
        PACKAGE / LEDGER_OUTPUT.name,
        PACKAGE / MANIFEST_OUTPUT.name,
        PACKAGE / ACCEPTANCE_OUTPUT.name,
        PACKAGE / ORACLE_OUTPUT.name,
        PACKAGE / ORACLE_SCHEMA_OUTPUT.name,
        PACKAGE / PROOF_OUTPUT.name,
        PACKAGE / PROOF_SCHEMA_OUTPUT.name,
    ]
    for path in ordered:
        _preflight_output(path)
    staged: dict[Path, Path] = {}
    backups: dict[Path, Path | None] = {}
    committed: list[Path] = []
    try:
        for path in ordered:
            staged[path] = _stage_payload(path, outputs[path], "stage")
        for path in ordered:
            backups[path] = (
                _stage_payload(path, path.read_bytes(), "backup")
                if path.exists()
                else None
            )
        try:
            for path in ordered:
                os.replace(staged[path], path)
                committed.append(path)
            _fsync_package()
        except BaseException as exc:
            rollback_errors: list[str] = []
            for path in reversed(committed):
                backup = backups[path]
                try:
                    if backup is None:
                        path.unlink(missing_ok=True)
                    else:
                        os.replace(backup, path)
                        backups[path] = None
                except OSError as rollback_exc:
                    rollback_errors.append(f"{path.name}: {rollback_exc}")
            try:
                _fsync_package()
            except OSError as rollback_exc:
                rollback_errors.append(f"directory fsync: {rollback_exc}")
            if rollback_errors:
                raise MigrationError(
                    "transactional output commit and rollback failed: "
                    + "; ".join(rollback_errors)
                ) from exc
            raise MigrationError(
                "transactional output commit failed; prior state restored"
            ) from exc
    finally:
        for temporary in [*staged.values(), *backups.values()]:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    try:
        proof, schema, outputs = compile_migration()
        validate_migration(proof, schema, outputs)
        _validate_expected(proof, outputs)
        if args.write:
            _transactional_write(outputs)
            for path in outputs:
                print(f"WROTE: {path.relative_to(REPO_ROOT)}")
            return 0
        for path, payload in outputs.items():
            if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
                raise MigrationError(f"checked output drift: {path.name}")
        print(
            "PASS: isolated five-file metadata post-state; capabilities=500, oracles=500, candidate promotion=0"
        )
        return 0
    except (
        MigrationError,
        SchemaError,
        KeyError,
        IndexError,
        TypeError,
        ValueError,
        OSError,
    ) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
