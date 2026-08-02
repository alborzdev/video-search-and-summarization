#!/usr/bin/env python3
"""Compile an isolated 500-row successor oracle projection."""

from __future__ import annotations

import argparse
from collections import Counter
import copy
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


sys.dont_write_bytecode = True

PACKAGE = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE.parents[4].resolve(strict=True)
OUTPUT = PACKAGE / "capability-oracles-500.json"
SCHEMA = PACKAGE / "capability-oracles-500.schema.json"
MAX_JSON_BYTES = 64_000_000

INPUTS = {
    "candidate_adapter": {
        "path": "deploy/docker/thor-local/qualification/candidate-oracle-adapter/adapter.json",
        "raw_sha256": "6e77635625a1f6b4b27dfcdc9aa5a0e695d6656adad041604f2b96fa2ac17235",
    },
    "candidate_adapter_schema": {
        "path": "deploy/docker/thor-local/qualification/candidate-oracle-adapter/adapter.schema.json",
        "raw_sha256": "959727de4d57884d67202847cd968e73fd792d1811356755c197a2e34403cbbb",
    },
    "candidate_source": {
        "path": "deploy/docker/thor-local/qualification/remaining-advertised-entry-candidates/candidate.json",
        "raw_sha256": "a3c1b793f976fa384fb4ea588602f225e21c9d2d1fd563f12c0aadfa9d1a56fd",
    },
    "candidate_source_schema": {
        "path": "deploy/docker/thor-local/qualification/remaining-advertised-entry-candidates/candidate.schema.json",
        "raw_sha256": "e3f09d7c86c46e236b9786f5eb3aa60868e67363224922ce04cfab3d60cd12a8",
    },
    "official_capabilities": {
        "path": "deploy/docker/thor-local/parity/official-capabilities.json",
        "raw_sha256": "cde0dc3981aaf699a017c7108089aac72070101edc47a06489f3940e44fe52a0",
    },
    "official_capabilities_schema": {
        "path": "deploy/docker/thor-local/parity/official-capabilities.schema.json",
        "raw_sha256": "fb817586b9a37ad7975ca820f69a7f2c6e575bca9f8d8686701d5fa0bf505896",
    },
    "live_oracles": {
        "path": "deploy/docker/thor-local/parity/capability-oracles.json",
        "raw_sha256": "c4e7a5ecfedfa2ddf18e68fc2bc110bea48d9ff7ce63d0dd4fdc169711beda90",
    },
    "live_oracles_schema": {
        "path": "deploy/docker/thor-local/parity/capability-oracles.schema.json",
        "raw_sha256": "55de87c13e78b4f349e7095232f31c1135155e0bc13ed6bcb8e4abb906f26cf1",
    },
    "protocol_v2": {
        "path": "deploy/docker/thor-local/qualification/protocol-cases-v2-candidates/protocol-cases-v2-candidate.json",
        "raw_sha256": "886151fee9ce27b24601499011151e827c4742b32d400c609c8c0b149851db62",
    },
    "protocol_v2_schema": {
        "path": "deploy/docker/thor-local/qualification/protocol-cases-v2-candidates/protocol-cases-v2-candidate.schema.json",
        "raw_sha256": "831d982f6912358b8dfae049cd10ed709af299d91cb7196031d28b29a092877d",
    },
    "workloads": {
        "path": "deploy/docker/thor-local/qualification/remaining-entry-workloads/workloads.json",
        "raw_sha256": "ca4170118a94a659acca600d9ab00dca6504544f062edabd5cef0ed3311e8312",
    },
    "workloads_schema": {
        "path": "deploy/docker/thor-local/qualification/remaining-entry-workloads/workload.schema.json",
        "raw_sha256": "736f9295e4f89afbb1aaed7c086155e30a09b6dc2c583433b9cb98ad2c005c14",
    },
}

SCHEMA_RAW_SHA256 = "fcbe27337accc57c5a57a3ce7bf26d1e532c9001f7841134ec22db8663d41024"
EXPECTED_OUTPUT_PAYLOAD_SHA256 = (
    "4d4875014874bcad3fa9f90024207097a1304090759a90fc1f760beef97d33dc"
)
EXPECTED_OUTPUT_RAW_SHA256 = (
    "75a7c6b6ecc5bcfee0eece99a10ca29c0258717887c59847252629ac4d21e364"
)


class SuccessorError(RuntimeError):
    """A source lock, semantic invariant, or deterministic output failed."""


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
        raise SuccessorError(f"JSON exceeds bounded size: {label}")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise SuccessorError(f"duplicate JSON key in {label}: {key!r}")
            result[key] = value
        return result

    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda token: (_ for _ in ()).throw(
                SuccessorError(f"non-finite JSON number in {label}: {token}")
            ),
        )
    except SuccessorError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SuccessorError(f"invalid UTF-8 JSON in {label}: {exc}") from exc


def _repo_file(relative_text: str) -> Path:
    relative = Path(relative_text)
    if not relative_text or relative.is_absolute() or ".." in relative.parts:
        raise SuccessorError(f"unsafe repository path: {relative_text}")
    current = REPO_ROOT
    for part in relative.parts:
        current /= part
        try:
            mode = current.lstat().st_mode
        except OSError as exc:
            raise SuccessorError(f"missing repository file: {relative_text}") from exc
        if stat.S_ISLNK(mode):
            raise SuccessorError(f"repository path traverses symlink: {relative_text}")
    if not stat.S_ISREG(current.lstat().st_mode):
        raise SuccessorError(f"repository path is not a regular file: {relative_text}")
    try:
        current.resolve(strict=True).relative_to(REPO_ROOT)
    except (OSError, RuntimeError, ValueError) as exc:
        raise SuccessorError(f"repository path escapes root: {relative_text}") from exc
    return current


def _load_locked(relative: str, expected_sha256: str) -> tuple[Any, str]:
    path = _repo_file(relative)
    payload = path.read_bytes()
    digest = _sha_bytes(payload)
    if expected_sha256 not in ("TO_BE_PINNED", digest):
        raise SuccessorError(f"raw source digest drift: {relative}")
    return _strict_json(payload, relative), digest


def _load_local_schema(path: Path, expected_sha256: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise SuccessorError(f"schema must be a regular non-symlink: {path}")
    payload = path.read_bytes()
    digest = _sha_bytes(payload)
    if expected_sha256 not in ("TO_BE_PINNED", digest):
        raise SuccessorError(f"raw schema digest drift: {path}")
    schema = _strict_json(payload, str(path))
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise SuccessorError(f"invalid schema {path.name}: {exc.message}") from exc
    return schema


def _validate(value: Any, schema: dict[str, Any], label: str) -> None:
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = "/" + "/".join(str(part) for part in error.absolute_path)
        raise SuccessorError(f"{label} schema error at {location}: {error.message}")


def _unique(
    rows: list[dict[str, Any]], key: str, label: str
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        identity = row.get(key)
        if not isinstance(identity, str) or not identity or identity in result:
            raise SuccessorError(f"missing or duplicate {label} key: {identity!r}")
        result[identity] = row
    return result


def _assert_payload(value: dict[str, Any], field: str, label: str) -> None:
    payload = dict(value)
    observed = payload.pop(field)
    if observed != _sha_json(payload):
        raise SuccessorError(f"{label} payload digest mismatch")


def _manifest_order(pointer: str) -> tuple[int, int]:
    parts = pointer.split("/")
    if (
        len(parts) != 5
        or parts[0] != ""
        or parts[1] != "features"
        or parts[3] != "advertised"
        or not parts[2].isdigit()
        or not parts[4].isdigit()
    ):
        raise SuccessorError(f"invalid manifest pointer: {pointer!r}")
    return int(parts[2]), int(parts[4])


def _ordered_candidate_ids(candidate_source: dict[str, Any]) -> list[str]:
    result: list[str] = []
    prior: tuple[int, int] | None = None
    seen: set[tuple[int, int]] = set()
    for entry in candidate_source["entries"]:
        order = _manifest_order(entry["manifest_pointer"])
        if order in seen or (prior is not None and order <= prior):
            raise SuccessorError("candidate source manifest-pointer order drift")
        seen.add(order)
        prior = order
        result.append(entry["proposed_capability"]["id"])
    return result


def _candidate_successor_row(
    adapter: dict[str, Any],
    protocol_binding: dict[str, Any] | None,
    workload: dict[str, Any] | None,
) -> dict[str, Any]:
    row = copy.deepcopy(adapter)
    capability_id = row["capability_id"]
    kind = row["ledger_binding"]["kind"]
    if (protocol_binding is not None) != (kind == "protocol"):
        raise SuccessorError(f"{capability_id}: protocol-v2 binding kind drift")
    if (workload is not None) != (kind in {"api", "deployment"}):
        raise SuccessorError(f"{capability_id}: workload binding kind drift")
    if protocol_binding is not None:
        if (
            protocol_binding["capability_id"] != capability_id
            or protocol_binding["boundary"] != row["execution_boundary"]
            or protocol_binding["readiness"] != "planning_only"
            or protocol_binding["activation_supported"] is not False
            or protocol_binding["vector_projection"]["contract"]
            != row["candidate_oracle_plan"]
        ):
            raise SuccessorError(f"{capability_id}: protocol-v2 semantic drift")
    if workload is not None:
        if (
            workload["candidate_id"] != capability_id
            or workload["workload_type"] != kind
            or workload["acceptance_class"] != row["acceptance_class"]
            or workload["manifest_pointer"] != row["manifest_pointer"]
            or workload["advertised"] != row["advertised"]
        ):
            raise SuccessorError(f"{capability_id}: workload semantic drift")

    adapter_sha256 = _sha_json(adapter)
    row.update(
        {
            "successor_schema_version": 1,
            "origin": "candidate_successor_planning_only",
            "profile": row["profile_seed"],
            "mode": row["mode_seed"],
            "protocol_v2_binding": copy.deepcopy(protocol_binding),
            "workload_binding": copy.deepcopy(workload),
            "binding_integrity": {
                "adapter_record_canonical_sha256": adapter_sha256,
                "protocol_v2_binding_canonical_sha256": (
                    _sha_json(protocol_binding)
                    if protocol_binding is not None
                    else None
                ),
                "workload_binding_canonical_sha256": (
                    _sha_json(workload) if workload is not None else None
                ),
            },
        }
    )
    row["successor_row_payload_sha256"] = _sha_json(row)
    return row


def _validate_preserved_live(
    projected: list[dict[str, Any]], live: dict[str, Any]
) -> None:
    live_rows = live["oracles"]
    prefix = projected[: len(live_rows)]
    if prefix != live_rows or _canonical_bytes(prefix) != _canonical_bytes(live_rows):
        raise SuccessorError("existing live oracle prefix changed semantically")
    for index, original in enumerate(live_rows):
        if _canonical_bytes(prefix[index]) != _canonical_bytes(original):
            raise SuccessorError(f"existing live oracle row changed at index {index}")


def compile_successor() -> dict[str, Any]:
    documents: dict[str, Any] = {}
    locks: dict[str, dict[str, str]] = {}
    for source_id, specification in INPUTS.items():
        value, digest = _load_locked(specification["path"], specification["raw_sha256"])
        documents[source_id] = value
        locks[source_id] = {"path": specification["path"], "raw_sha256": digest}

    for document_name, schema_name in (
        ("candidate_adapter", "candidate_adapter_schema"),
        ("candidate_source", "candidate_source_schema"),
        ("official_capabilities", "official_capabilities_schema"),
        ("live_oracles", "live_oracles_schema"),
        ("protocol_v2", "protocol_v2_schema"),
        ("workloads", "workloads_schema"),
    ):
        schema = documents[schema_name]
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            raise SuccessorError(
                f"invalid locked schema {schema_name}: {exc.message}"
            ) from exc
        _validate(documents[document_name], schema, document_name)

    adapter_document = documents["candidate_adapter"]
    candidate_source = documents["candidate_source"]
    official_capabilities = documents["official_capabilities"]
    live_document = documents["live_oracles"]
    protocol_document = documents["protocol_v2"]
    workload_document = documents["workloads"]
    _assert_payload(adapter_document, "adapter_payload_sha256", "candidate adapter")
    _assert_payload(candidate_source, "candidate_payload_sha256", "candidate source")
    _assert_payload(protocol_document, "candidate_payload_sha256", "protocol-v2")
    _assert_payload(workload_document, "payload_sha256", "workloads")

    adapters = adapter_document["candidate_adapters_by_capability_id"]
    live_by_id = _unique(live_document["oracles"], "capability_id", "live oracle")
    official_by_id = _unique(
        official_capabilities["capabilities"], "id", "official capability"
    )
    all_protocol_bindings = _unique(
        protocol_document["bindings"], "capability_id", "protocol-v2 binding"
    )
    protocol_bindings = {
        key: value
        for key, value in all_protocol_bindings.items()
        if key.startswith("manifest-entry.")
    }
    workloads = _unique(workload_document["workloads"], "candidate_id", "workload")
    if len(adapters) != 211 or len(live_by_id) != 289:
        raise SuccessorError("211/289 source denominator drift")
    live_order = [row["capability_id"] for row in live_document["oracles"]]
    official_order = [row["id"] for row in official_capabilities["capabilities"]]
    if live_order != official_order or set(live_by_id) != set(official_by_id):
        raise SuccessorError("live oracle/official ledger order drift")
    candidate_order = _ordered_candidate_ids(candidate_source)
    candidate_entries_by_id = _unique(
        [
            {
                "capability_id": entry["proposed_capability"]["id"],
                "entry": entry,
            }
            for entry in candidate_source["entries"]
        ],
        "capability_id",
        "candidate source entry",
    )
    if set(candidate_order) != set(adapters) or len(candidate_order) != 211:
        raise SuccessorError("candidate source/adapter key partition drift")
    for capability_id in candidate_order:
        entry = candidate_entries_by_id[capability_id]["entry"]
        adapter = adapters[capability_id]
        if adapter["manifest_pointer"] != entry["manifest_pointer"] or adapter[
            "candidate_entry_sha256"
        ] != _sha_json(entry):
            raise SuccessorError(f"{capability_id}: candidate source binding drift")
    if set(adapters) & set(live_by_id) or len(set(adapters) | set(live_by_id)) != 500:
        raise SuccessorError("candidate/live key partition drift")

    expected_protocol = {
        capability_id
        for capability_id, adapter in adapters.items()
        if adapter["ledger_binding"]["kind"] == "protocol"
    }
    expected_workloads = {
        capability_id
        for capability_id, adapter in adapters.items()
        if adapter["ledger_binding"]["kind"] in {"api", "deployment"}
    }
    if set(protocol_bindings) != expected_protocol or len(protocol_bindings) != 23:
        raise SuccessorError("exact 23 candidate protocol-v2 binding set drift")
    if set(workloads) != expected_workloads or len(workloads) != 60:
        raise SuccessorError("exact 60 API/deployment workload set drift")

    candidate_rows = [
        _candidate_successor_row(
            adapters[capability_id],
            protocol_bindings.get(capability_id),
            workloads.get(capability_id),
        )
        for capability_id in candidate_order
    ]
    candidate_by_id = _unique(candidate_rows, "capability_id", "candidate successor")
    fixture_ids: set[str] = set()
    namespaces: set[str] = set()
    for row in candidate_rows:
        capability_id = row["capability_id"]
        fixture_id = row["fixture"]["id"]
        namespace = row["fixture"]["namespace"]
        observations = (
            row["expected_observations"] + row["adjacent_negative_observations"]
        )
        observation_ids = [item["id"] for item in observations]
        assertion_ids = [item["id"] for item in row["assertions"]]
        gate_ids = [item["id"] for item in row["admission_gates"]]
        if fixture_id in fixture_ids or namespace in namespaces:
            raise SuccessorError(f"{capability_id}: fixture identity collision")
        if len(observation_ids) != len(set(observation_ids)):
            raise SuccessorError(f"{capability_id}: duplicate observation identity")
        if len(assertion_ids) != len(set(assertion_ids)):
            raise SuccessorError(f"{capability_id}: duplicate assertion identity")
        if len(gate_ids) != len(set(gate_ids)):
            raise SuccessorError(f"{capability_id}: duplicate admission identity")
        if {item["observation_id"] for item in row["assertions"]} != set(
            observation_ids
        ):
            raise SuccessorError(f"{capability_id}: assertion reference drift")
        fixture_ids.add(fixture_id)
        namespaces.add(namespace)
    projected = copy.deepcopy(live_document["oracles"]) + candidate_rows
    _validate_preserved_live(projected, live_document)
    projected_by_id = _unique(projected, "capability_id", "projected oracle")
    if len(projected) != 500 or set(projected_by_id) != set(live_by_id) | set(adapters):
        raise SuccessorError("projected 500-row oracle partition drift")
    projected_order = [row["capability_id"] for row in projected]
    if projected_order != official_order + candidate_order:
        raise SuccessorError("projected oracle capability-ID order drift")

    candidate_evidence = sum(len(row["evidence"]) for row in candidate_rows)
    candidate_promoted = sum(
        row["runtime_state"] in {"passed", "passed_current"}
        or row["can_promote_runtime_state"]
        for row in candidate_rows
    )
    candidate_executor_ready = sum(
        row["readiness"]["executor_ready"] for row in candidate_rows
    )
    external_rows = [
        row for row in candidate_rows if row["execution_boundary"] == "external"
    ]
    if candidate_evidence or candidate_promoted or candidate_executor_ready:
        raise SuccessorError("candidate rows cannot be evidenced, ready, or promoted")
    if any(
        row["current_state"] != "external_boundary_unexecuted"
        or row["runtime_state"] != "not_applicable"
        or row["execution_bounds"]["network_scope"] != "operator_approved_external_only"
        for row in external_rows
    ):
        raise SuccessorError("external boundary state drift")

    live_row_hashes = {
        capability_id: _sha_json(row)
        for capability_id, row in sorted(live_by_id.items())
    }
    candidate_row_hashes = {
        capability_id: _sha_json(row)
        for capability_id, row in sorted(candidate_by_id.items())
    }
    output = {
        "schema_version": 2,
        "successor_id": "vss-3.2.1-thor-oracle-500-candidate-successor",
        "mode": "isolated_candidate_only_projection",
        "target": copy.deepcopy(live_document["target"]),
        "source_locks": locks,
        "policy": {
            "candidate_only_extension": True,
            "live_registry_modified": False,
            "wrapper_modified": False,
            "runtime_execution": "forbidden",
            "required_cloud_inference": False,
            "warehouse_sample_bundle": "excluded",
            "runtime_evidence": [],
            "can_promote_runtime_state": False,
        },
        "summary": {
            "preserved_live_oracles": len(live_by_id),
            "candidate_successor_oracles": len(candidate_rows),
            "authoritative_gap_requirements": sum(
                "authoritative_gap_requirement" in row["candidate_oracle_plan"]
                for row in candidate_rows
            ),
            "projected_oracles": len(projected),
            "protocol_v2_bound_candidates": len(protocol_bindings),
            "workload_bound_candidates": len(workloads),
            "api_workload_bound_candidates": sum(
                row["workload_type"] == "api" for row in workloads.values()
            ),
            "deployment_workload_bound_candidates": sum(
                row["workload_type"] == "deployment" for row in workloads.values()
            ),
            "unbound_planning_candidates": len(adapters)
            - len(protocol_bindings)
            - len(workloads),
            "candidate_execution_boundary_counts": dict(
                sorted(
                    Counter(row["execution_boundary"] for row in candidate_rows).items()
                )
            ),
            "candidate_evidence_records": candidate_evidence,
            "candidate_executor_ready": candidate_executor_ready,
            "candidate_promoted": candidate_promoted,
            "external_candidate_oracles": len(external_rows),
        },
        "ordering": {
            "live_order": "official_capabilities_source_order",
            "candidate_order": "strict_manifest_pointer_order",
            "live_capability_id_order_sha256": _sha_json(official_order),
            "candidate_capability_id_order_sha256": _sha_json(candidate_order),
            "projected_capability_id_order_sha256": _sha_json(projected_order),
        },
        "live_preservation": {
            "live_document_raw_sha256": locks["live_oracles"]["raw_sha256"],
            "live_oracle_records_canonical_sha256": _sha_json(live_document["oracles"]),
            "projected_live_prefix_canonical_sha256": _sha_json(
                projected[: len(live_document["oracles"])]
            ),
            "live_record_hashes_by_capability_id": live_row_hashes,
        },
        "candidate_integrity": {
            "adapter_payload_sha256": adapter_document["adapter_payload_sha256"],
            "protocol_v2_payload_sha256": protocol_document["candidate_payload_sha256"],
            "workloads_payload_sha256": workload_document["payload_sha256"],
            "candidate_record_hashes_by_capability_id": candidate_row_hashes,
        },
        "projected_oracles": projected,
        "projected_oracle_records_canonical_sha256": _sha_json(projected),
    }
    output["successor_payload_sha256"] = _sha_json(output)
    return output


def validate_successor(successor: dict[str, Any]) -> None:
    schema = _load_local_schema(SCHEMA, SCHEMA_RAW_SHA256)
    _validate(successor, schema, "oracle-500 successor")
    payload = dict(successor)
    observed = payload.pop("successor_payload_sha256")
    if observed != _sha_json(payload):
        raise SuccessorError("successor payload digest mismatch")
    if EXPECTED_OUTPUT_PAYLOAD_SHA256 != observed:
        raise SuccessorError("successor payload lock drift")


def _atomic_write_regular(path: Path, payload: bytes) -> None:
    parent = path.parent
    if parent.is_symlink() or not parent.is_dir():
        raise SuccessorError(f"output parent must be a regular directory: {parent}")
    if path.is_symlink():
        raise SuccessorError(f"refusing to replace symlink output: {path}")
    if path.exists() and not path.is_file():
        raise SuccessorError(f"output is not a regular file: {path}")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            os.fchmod(handle.fileno(), 0o644)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if temporary.is_symlink() or not temporary.is_file():
            raise SuccessorError(f"temporary output is not regular: {temporary}")
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise SuccessorError(f"output target changed unsafely: {path}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    try:
        successor = compile_successor()
        validate_successor(successor)
        encoded = _encoded(successor)
        if args.write:
            _atomic_write_regular(OUTPUT, encoded)
            print(f"WROTE: {OUTPUT.relative_to(REPO_ROOT)}")
            return 0
        checked, digest = _load_locked(
            str(OUTPUT.relative_to(REPO_ROOT)), EXPECTED_OUTPUT_RAW_SHA256
        )
        if checked != successor or OUTPUT.read_bytes() != encoded:
            raise SuccessorError("checked successor differs from deterministic compile")
        print(
            "PASS: oracle-500 successor; preserved=289, candidates=211, "
            "projected=500, evidence=0, promoted=0"
        )
        return 0
    except (SuccessorError, KeyError, TypeError, ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
