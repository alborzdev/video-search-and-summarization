#!/usr/bin/env python3
"""Compile two Wave 8 executable subsets onto the selected 500-oracle index.

The selected schema-v2 oracle document is reused byte-for-byte. Executable
subset observations live in a separate annotation artifact and therefore
cannot be confused with runtime evidence or invalidate the selected schema.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import stat
import sys
import tempfile
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4]
CONTRACT_PATH = HERE / "contract.json"
CONTRACT_SCHEMA_PATH = HERE / "contract.schema.json"
RECEIPT_PATH = HERE / "execution-receipt.json"
RECEIPT_SCHEMA_PATH = HERE / "execution-receipt.schema.json"
SUCCESSOR_PATH = HERE / "successor-capability-oracles.json"
SUCCESSOR_SCHEMA_PATH = HERE / "successor-capability-oracles.schema.json"
MAX_BYTES = 96_000_000
RECEIPT_ID = "successor-500-executable-subsets-wave1-receipt-2026-08-01"
EXPECTED_CAPABILITY_IDS = (
    "manifest-entry.video-summarization-live.05-sse-mcp-server",
    "manifest-entry.agent-and-mcp-apis.06-lvs-mcp",
)
SET_ID = "thor-vss-3.2.1-metadata-500-staged"
SELECTOR_PATH = (
    "deploy/docker/thor-local/qualification/"
    "live-metadata-500-activation-rebase-successor/projected-selector.json"
)
DESCRIPTOR_PATH = (
    "deploy/docker/thor-local/qualification/"
    "live-metadata-500-activation-rebase-successor/"
    "projected-live-ready-descriptor.json"
)
SELECTOR_SCHEMA_PATH = (
    "deploy/docker/thor-local/parity/metadata_sets/selector.schema.json"
)
SET_SCHEMA_PATH = (
    "deploy/docker/thor-local/parity/metadata_sets/metadata-set.schema.json"
)
LIVE_OFFICIAL_PATH = "deploy/docker/thor-local/parity/official-capabilities.json"
LIVE_ORACLES_PATH = "deploy/docker/thor-local/parity/capability-oracles.json"
PRESERVED_FIELDS = (
    "current_state",
    "runtime_state",
    "evidence",
    "can_promote_runtime_state",
    "readiness",
    "admission_gates",
)


class CompilationError(RuntimeError):
    """A selected-set, execution, schema, or non-promotion invariant failed."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def strict_json_bytes(payload: bytes, label: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise CompilationError(f"{label}: duplicate JSON key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda token: (_ for _ in ()).throw(
                CompilationError(f"{label}: non-finite number {token}")
            ),
        )
    except CompilationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CompilationError(f"{label}: invalid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise CompilationError(f"{label}: JSON root must be an object")
    return value


def read_regular(path: Path, label: str, *, max_bytes: int = MAX_BYTES) -> bytes:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise CompilationError(f"{label}: unavailable") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise CompilationError(f"{label}: must be a regular non-symlink")
    if metadata.st_size > max_bytes:
        raise CompilationError(f"{label}: exceeds size bound")
    payload = path.read_bytes()
    if len(payload) != metadata.st_size or len(payload) > max_bytes:
        raise CompilationError(f"{label}: changed while reading or exceeds bound")
    return payload


def repo_path(relative: str) -> Path:
    pure = PurePosixPath(relative)
    if (
        pure.is_absolute()
        or not pure.parts
        or any(part in {"", ".", ".."} for part in pure.parts)
        or pure.as_posix() != relative
    ):
        raise CompilationError(f"unsafe repository path: {relative}")
    path = REPO_ROOT
    for part in pure.parts:
        path = path / part
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise CompilationError(f"repository path unavailable: {relative}") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise CompilationError(f"repository path contains a symlink: {relative}")
    resolved = path.resolve(strict=True)
    if REPO_ROOT != resolved and REPO_ROOT not in resolved.parents:
        raise CompilationError(f"repository path escaped root: {relative}")
    return path


def validate_schema(value: dict[str, Any], schema_path: Path, label: str) -> None:
    schema = strict_json_bytes(
        read_regular(schema_path, schema_path.name), schema_path.name
    )
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise CompilationError(f"{label}: invalid JSON Schema") from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        first = errors[0]
        where = "/" + "/".join(str(part) for part in first.absolute_path)
        raise CompilationError(f"{label}: schema violation at {where}: {first.message}")


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    contract = strict_json_bytes(read_regular(path, "contract"), "contract")
    validate_schema(contract, CONTRACT_SCHEMA_PATH, "contract")
    seen: set[str] = set()
    for lock in contract["source_locks"]:
        if lock["path"] in seen:
            raise CompilationError(f"duplicate source lock: {lock['path']}")
        seen.add(lock["path"])
        actual = sha256(read_regular(repo_path(lock["path"]), lock["path"]))
        if actual != lock["raw_sha256"]:
            raise CompilationError(f"source lock mismatch: {lock['path']}")
    bindings = contract["bindings"]
    if tuple(item["capability_id"] for item in bindings) != EXPECTED_CAPABILITY_IDS:
        raise CompilationError("binding order or exact capability denominator drift")
    if len({item["legacy_entry_id"] for item in bindings}) != 2:
        raise CompilationError("legacy entry bindings must be unique")
    if len({item["oracle_index"] for item in bindings}) != 2:
        raise CompilationError("oracle indexes must be unique")
    return contract


def load_module(path: Path, module_name: str) -> Any:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise CompilationError(f"cannot load reviewed module: {path}")
    module = importlib.util.module_from_spec(spec)
    prior = sys.modules.get(module_name)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        if prior is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = prior
    return module


def _write_overlay(root: Path, relative: str, payload: bytes) -> None:
    pure = PurePosixPath(relative)
    if (
        pure.is_absolute()
        or not pure.parts
        or any(part in {"", ".", ".."} for part in pure.parts)
        or pure.as_posix() != relative
    ):
        raise CompilationError(f"unsafe temporary overlay path: {relative}")
    target = root.joinpath(*pure.parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)


def load_selected_oracles(contract: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    resolver_relative = "deploy/docker/thor-local/parity/metadata_sets/resolver.py"
    resolver_path = repo_path(resolver_relative)
    resolver = load_module(resolver_path, "vss_metadata_set_resolver_wave1")
    selector = strict_json_bytes(
        read_regular(repo_path(SELECTOR_PATH), SELECTOR_PATH), SELECTOR_PATH
    )
    descriptor = strict_json_bytes(
        read_regular(repo_path(DESCRIPTOR_PATH), DESCRIPTOR_PATH), DESCRIPTOR_PATH
    )
    selected_rows = [
        row
        for row in selector.get("available_sets", [])
        if row.get("set_id") == SET_ID
    ]
    if (
        selector.get("selected_set") != SET_ID
        or len(selected_rows) != 1
        or selected_rows[0].get("descriptor_raw_sha256")
        != contract["selected_metadata_set"]["descriptor_raw_sha256"]
    ):
        raise CompilationError("activation-rebase selector or descriptor identity drift")
    descriptor_raw = read_regular(repo_path(DESCRIPTOR_PATH), DESCRIPTOR_PATH)
    if sha256(descriptor_raw) != selected_rows[0].get("descriptor_raw_sha256"):
        raise CompilationError("activation-rebase descriptor raw identity drift")

    try:
        with tempfile.TemporaryDirectory(
            prefix="vss-successor-500-wave1-rebase-"
        ) as name:
            root = Path(name)
            _write_overlay(
                root,
                resolver.SELECTOR_SCHEMA_PATH,
                read_regular(repo_path(SELECTOR_SCHEMA_PATH), SELECTOR_SCHEMA_PATH),
            )
            _write_overlay(
                root,
                resolver.SET_SCHEMA_PATH,
                read_regular(repo_path(SET_SCHEMA_PATH), SET_SCHEMA_PATH),
            )
            _write_overlay(
                root,
                resolver.SELECTOR_PATH,
                read_regular(repo_path(SELECTOR_PATH), SELECTOR_PATH),
            )
            _write_overlay(root, selected_rows[0]["descriptor_path"], descriptor_raw)
            for group in ("documents", "schemas"):
                for member in descriptor[group].values():
                    payload = read_regular(repo_path(member["path"]), member["path"])
                    if sha256(payload) != member["raw_sha256"]:
                        raise CompilationError(
                            f"activation descriptor member drift: {member['path']}"
                        )
                    _write_overlay(root, member["path"], payload)
            snapshot = resolver.resolve_metadata_set(repo_root=root)
    except Exception as exc:
        raise CompilationError(
            f"activation-rebase metadata set did not resolve: {exc}"
        ) from exc
    expected = contract["selected_metadata_set"]
    if (
        snapshot.set_id != expected["set_id"]
        or snapshot.descriptor_raw_sha256 != expected["descriptor_raw_sha256"]
        or dict(snapshot.expected_counts).get("capabilities")
        != expected["capabilities"]
        or dict(snapshot.expected_counts).get("oracles") != expected["oracles"]
    ):
        raise CompilationError("selected Metadata-500 identity or counts drift")
    document = snapshot.document("capability_oracles")
    if (
        sha256(canonical_bytes(document))
        != contract["base_oracle_document"]["canonical_sha256"]
    ):
        raise CompilationError("selected oracle document canonical identity drift")
    return snapshot, document


def execute_wave8(contract: dict[str, Any]) -> dict[str, Any]:
    executor = load_module(
        repo_path(contract["wave8"]["executor_path"]), "vss_wave8_executor_wave1"
    )
    try:
        result = executor.build_result()
    except Exception as exc:
        raise CompilationError(f"Wave 8 deterministic execution failed: {exc}") from exc
    if sha256(canonical_bytes(result)) != contract["wave8"]["result_canonical_sha256"]:
        raise CompilationError("Wave 8 deterministic result identity drift")
    return result


def assert_oracle_boundary(row: dict[str, Any], capability_id: str) -> None:
    if (
        row.get("capability_id") != capability_id
        or row.get("current_state") != "open_unexecuted"
        or row.get("runtime_state") != "not_qualified"
        or row.get("evidence") != []
        or row.get("can_promote_runtime_state") is not False
        or row.get("readiness", {}).get("executor_ready") is not False
    ):
        raise CompilationError(f"non-promotion boundary drift: {capability_id}")
    operator_gates = [
        gate
        for gate in row.get("admission_gates", [])
        if gate.get("id") == "operator-approval"
    ]
    if len(operator_gates) != 1 or operator_gates[0].get("status") != "unmet":
        raise CompilationError(f"operator gate changed: {capability_id}")


def compile_outputs(
    contract: dict[str, Any],
    snapshot: Any,
    oracle_document: dict[str, Any],
    wave8_result: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if (
        sha256(canonical_bytes(oracle_document))
        != contract["base_oracle_document"]["canonical_sha256"]
    ):
        raise CompilationError("input oracle document canonical identity drift")
    if (
        sha256(canonical_bytes(wave8_result))
        != contract["wave8"]["result_canonical_sha256"]
    ):
        raise CompilationError("input Wave 8 result canonical identity drift")
    rows = oracle_document.get("oracles")
    if not isinstance(rows, list) or len(rows) != 500:
        raise CompilationError("selected oracle denominator is not exactly 500")
    wave_entries = wave8_result.get("entries")
    if not isinstance(wave_entries, list) or len(wave_entries) != 2:
        raise CompilationError("Wave 8 result must contain exactly two entries")
    by_legacy = {entry.get("entry_id"): entry for entry in wave_entries}
    if len(by_legacy) != 2:
        raise CompilationError("Wave 8 result entry identities are not unique")
    safety = wave8_result.get("safety")
    expected_false = {
        "network_used",
        "socket_used",
        "subprocess_used",
        "docker_used",
        "service_lifecycle_used",
        "downloads_used",
        "credentials_used",
        "caller_supplied_callback_used",
        "warehouse_sample_used",
        "live_sse_connection",
        "mcp_transport_handshake",
        "deployed_lvs",
        "vlm_inference",
        "thor_runtime_readiness",
    }
    if (
        not isinstance(safety, dict)
        or any(safety.get(key) is not False for key in expected_false)
        or safety.get("temporary_files_cleaned") is not True
        or wave8_result.get("runtime_evidence") != []
        or wave8_result.get("official_capability_effect") != "none_candidate_only"
    ):
        raise CompilationError("Wave 8 result crossed a safety or promotion boundary")

    receipt_entries: list[dict[str, Any]] = []
    annotations: list[dict[str, Any]] = []
    annotated_indexes: set[int] = set()
    for binding in contract["bindings"]:
        index = binding["oracle_index"]
        row = rows[index]
        assert_oracle_boundary(row, binding["capability_id"])
        row_hash = sha256(canonical_bytes(row))
        if row_hash != binding["base_row_canonical_sha256"]:
            raise CompilationError(
                f"selected row identity drift: {binding['capability_id']}"
            )
        entry = by_legacy.get(binding["legacy_entry_id"])
        if entry is None:
            raise CompilationError(
                f"missing Wave 8 entry: {binding['legacy_entry_id']}"
            )
        receipt_entry = {
            "legacy_entry_id": binding["legacy_entry_id"],
            "capability_id": binding["capability_id"],
            "candidate_state": entry["candidate_state"],
            "evidence_scope": entry["evidence_scope"],
            "matched_assertions": entry["matched_assertions"],
            "retained_blockers": entry["retained_blockers"],
        }
        receipt_entries.append(receipt_entry)
        annotations.append(
            {
                "oracle_index": index,
                "capability_id": binding["capability_id"],
                "oracle_row_canonical_sha256": row_hash,
                "evidence_class": "candidate_executable_subset_non_advancing",
                "receipt_id": RECEIPT_ID,
                "wave8_result_canonical_sha256": contract["wave8"][
                    "result_canonical_sha256"
                ],
                "legacy_entry_id": binding["legacy_entry_id"],
                "evidence_scope": entry["evidence_scope"],
                "matched_assertions": entry["matched_assertions"],
                "retained_blockers": entry["retained_blockers"],
                "fixture": {
                    "kind": "executor_owned_ephemeral",
                    "sha256": wave8_result["execution"]["fixture_sha256"],
                    "retained": False,
                    "cleanup_verified": True,
                },
                "admission_effect": {
                    "subset_fixture_materialized": True,
                    "subset_executor_implemented": True,
                    "subset_collectors_implemented": True,
                    "full_oracle_executor_ready": False,
                    "operator_gate_satisfied": False,
                },
                "runtime_evidence": [],
            }
        )
        annotated_indexes.add(index)

    # The oracle successor deliberately reuses the complete selected document.
    # Deep-copy and byte comparison make accidental row mutation a hard failure.
    successor_document = copy.deepcopy(oracle_document)
    if canonical_bytes(successor_document) != canonical_bytes(oracle_document):
        raise CompilationError("byte-identical oracle reuse invariant failed")
    for binding in contract["bindings"]:
        before = oracle_document["oracles"][binding["oracle_index"]]
        after = successor_document["oracles"][binding["oracle_index"]]
        if any(before.get(field) != after.get(field) for field in PRESERVED_FIELDS):
            raise CompilationError(
                f"protected field changed: {binding['capability_id']}"
            )

    unannotated = [
        {
            "index": index,
            "capability_id": row["capability_id"],
            "row_canonical_sha256": sha256(canonical_bytes(row)),
        }
        for index, row in enumerate(rows)
        if index not in annotated_indexes
    ]
    if len(unannotated) != 498:
        raise CompilationError("unannotated oracle partition is not exactly 498")
    row_hashes = [sha256(canonical_bytes(row)) for row in rows]
    document_path = next(
        lock["path"]
        for lock in contract["source_locks"]
        if lock["raw_sha256"] == contract["base_oracle_document"]["raw_sha256"]
    )
    receipt = {
        "schema_version": 1,
        "receipt_id": RECEIPT_ID,
        "selected_set_id": snapshot.set_id,
        "selected_descriptor_raw_sha256": snapshot.descriptor_raw_sha256,
        "wave8_result_canonical_sha256": contract["wave8"]["result_canonical_sha256"],
        "outcome": "observed_match_candidate_only",
        "official_capability_effect": "none_candidate_only",
        "runtime_evidence": [],
        "entries": receipt_entries,
        "execution": wave8_result["execution"],
        "safety": {
            **{
                key: safety[key]
                for key in sorted(expected_false | {"temporary_files_cleaned"})
            },
            "models_used": False,
        },
    }
    projection = {
        "oracle_document_canonical_sha256": sha256(canonical_bytes(successor_document)),
        "annotation_index": annotations,
    }
    successor = {
        "schema_version": 1,
        "artifact_id": "successor-500-executable-subsets-wave1",
        "mode": "byte_identical_v2_oracles_plus_non_promoting_annotation_index",
        "oracle_document": {
            "path": document_path,
            "set_id": snapshot.set_id,
            "descriptor_raw_sha256": snapshot.descriptor_raw_sha256,
            "raw_sha256": contract["base_oracle_document"]["raw_sha256"],
            "canonical_sha256": sha256(canonical_bytes(successor_document)),
            "ordered_rows_canonical_sha256": sha256(canonical_bytes(row_hashes)),
            "byte_identical_to_selected_metadata_set": True,
        },
        "counts": {
            "oracles": 500,
            "annotated_rows": 2,
            "unannotated_rows": 498,
            "mutated_oracle_rows": 0,
            "runtime_promotions": 0,
        },
        "annotations": annotations,
        "unannotated_partition": {
            "count": 498,
            "ordered_row_identity_canonical_sha256": sha256(
                canonical_bytes(unannotated)
            ),
            "all_rows_byte_identical": True,
        },
        "projection_canonical_sha256": sha256(canonical_bytes(projection)),
        "global_invariants": {
            "current_state_changed": False,
            "runtime_state_changed": False,
            "runtime_evidence_added": False,
            "can_promote_changed": False,
            "executor_ready_changed": False,
            "operator_gate_changed": False,
            "canonical_metadata_mutated": False,
            "warehouse_sample_bundle": "excluded",
        },
    }
    validate_schema(receipt, RECEIPT_SCHEMA_PATH, "execution receipt")
    validate_schema(successor, SUCCESSOR_SCHEMA_PATH, "successor annotations")
    return receipt, successor


def build_outputs() -> tuple[dict[str, Any], dict[str, Any]]:
    contract = load_contract()
    snapshot, document = load_selected_oracles(contract)
    wave8_result = execute_wave8(contract)
    return compile_outputs(contract, snapshot, document, wave8_result)


def check_checked_artifacts(
    generated_receipt: dict[str, Any], generated_successor: dict[str, Any]
) -> None:
    checked_receipt = strict_json_bytes(
        read_regular(RECEIPT_PATH, "checked receipt"), "checked receipt"
    )
    checked_successor = strict_json_bytes(
        read_regular(SUCCESSOR_PATH, "checked successor"), "checked successor"
    )
    validate_schema(checked_receipt, RECEIPT_SCHEMA_PATH, "checked receipt")
    validate_schema(checked_successor, SUCCESSOR_SCHEMA_PATH, "checked successor")
    if checked_receipt != generated_receipt:
        raise CompilationError(
            "checked execution receipt differs from generated result"
        )
    if checked_successor != generated_successor:
        raise CompilationError(
            "checked successor annotation artifact differs from generated result"
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify checked artifacts")
    parser.add_argument(
        "--emit", choices=("receipt", "successor"), help="print one generated artifact"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        receipt, successor = build_outputs()
        if args.emit:
            value = receipt if args.emit == "receipt" else successor
            print(json.dumps(value, indent=2, sort_keys=True))
            return 0
        check_checked_artifacts(receipt, successor)
    except (CompilationError, OSError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        "PASS: two Wave 8 executable-subset annotations; "
        "500 oracle rows byte-identical; zero runtime promotions"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
