#!/usr/bin/env python3
"""Compile and validate the non-advancing 13-to-289 exact-title mapping proof."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import stat
import subprocess
import sys
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4].resolve(strict=True)
CONTRACT_PATH = HERE / "contract.json"
CONTRACT_SCHEMA_PATH = HERE / "contract.schema.json"
PROOF_PATH = HERE / "proof.json"
PROOF_SCHEMA_PATH = HERE / "proof.schema.json"
PREDECESSOR_COMMIT = "76596ccd1a2b02644506399b7e27ce36bbe3544b"
CONTRACT_RAW_SHA256 = "ed1e50ddcaf960aa823a388bf26ada844a9f63c4089a7cd6f4abbeb8f73c6bed"
ALLOWED_GIT_COMMANDS = {"rev-parse", "cat-file", "show"}
MAX_JSON_BYTES = 16_000_000

PLAN_PATH = "deploy/docker/thor-local/qualification/advertised-entry-gaps/plan.json"
MANIFEST_PATH = "deploy/docker/thor-local/parity/manifest.json"
CAPABILITIES_PATH = "deploy/docker/thor-local/parity/official-capabilities.json"
ORACLES_PATH = "deploy/docker/thor-local/parity/capability-oracles.json"
COMPILER_PATH = "deploy/docker/thor-local/qualification/advertised-entry-gaps/compiler.py"
PLAN_SCHEMA_PATH = "deploy/docker/thor-local/qualification/advertised-entry-gaps/plan.schema.json"
SOURCE_PATHS = [
    PLAN_PATH,
    MANIFEST_PATH,
    CAPABILITIES_PATH,
    ORACLES_PATH,
    COMPILER_PATH,
    PLAN_SCHEMA_PATH,
]


class ProofError(RuntimeError):
    """A source identity or exact-title transition invariant failed."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _strict_json_bytes(data: bytes, label: str) -> Any:
    if len(data) > MAX_JSON_BYTES:
        raise ProofError(f"JSON exceeds bounded size: {label}")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ProofError(f"duplicate JSON key in {label}: {key}")
            result[key] = value
        return result

    try:
        return json.loads(
            data.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda token: (_ for _ in ()).throw(
                ProofError(f"non-finite number in {label}: {token}")
            ),
        )
    except ProofError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProofError(f"invalid JSON in {label}: {exc}") from exc


def _regular_file(path: Path, label: str) -> Path:
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise ProofError(f"missing file: {label}") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise ProofError(f"file must be a regular non-symlink: {label}")
    return path


def _repo_file(relative: str) -> Path:
    if not relative or relative.startswith("/") or ".." in Path(relative).parts:
        raise ProofError(f"unsafe repository path: {relative}")
    path = _regular_file(REPO_ROOT / relative, relative)
    if REPO_ROOT not in path.resolve().parents:
        raise ProofError(f"repository path escapes root: {relative}")
    return path


def _load_schema(path: Path) -> dict[str, Any]:
    value = _strict_json_bytes(_regular_file(path, str(path)).read_bytes(), str(path))
    try:
        Draft202012Validator.check_schema(value)
    except SchemaError as exc:
        raise ProofError(f"invalid schema {path.name}: {exc.message}") from exc
    return value


def _validate(value: Any, schema_path: Path, label: str) -> None:
    errors = sorted(
        Draft202012Validator(_load_schema(schema_path)).iter_errors(value),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        raise ProofError(f"{label} schema validation failed: {errors[0].message}")


def _git(command: str, *args: str) -> bytes:
    if command not in ALLOWED_GIT_COMMANDS:
        raise ProofError(f"prohibited git command: {command}")
    completed = subprocess.run(
        ["git", command, *args],
        cwd=REPO_ROOT,
        shell=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=20,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ProofError(f"git {command} failed: {detail}")
    return completed.stdout


def _git_text(command: str, *args: str) -> str:
    return _git(command, *args).decode("ascii").strip()


def _load_predecessor(contract: dict[str, Any]) -> tuple[dict[str, bytes], dict[str, Any]]:
    predecessor = contract["predecessor"]
    resolved = _git_text("rev-parse", "--verify", f"{PREDECESSOR_COMMIT}^{{commit}}")
    if resolved != PREDECESSOR_COMMIT or _git_text("cat-file", "-t", resolved) != "commit":
        raise ProofError("predecessor commit identity mismatch")
    if _git_text("rev-parse", f"{resolved}^") != predecessor["parent_commit"]:
        raise ProofError("predecessor parent identity mismatch")
    if _git_text("rev-parse", f"{resolved}^{{tree}}") != predecessor["root_tree_oid"]:
        raise ProofError("predecessor root tree mismatch")
    return _load_locked_objects(contract["predecessor"]["source_objects"], resolved)


def _load_current(contract: dict[str, Any]) -> tuple[dict[str, bytes], dict[str, Any]]:
    expected = contract["successor"]["source_objects"]
    if [row["path"] for row in expected] != SOURCE_PATHS:
        raise ProofError("current source path/order drift")
    raw: dict[str, bytes] = {}
    parsed: dict[str, Any] = {}
    for row in expected:
        path = row["path"]
        payload = _repo_file(path).read_bytes()
        if _sha256(payload) != row["sha256"]:
            raise ProofError(f"current source digest mismatch: {path}")
        raw[path] = payload
        if path.endswith(".json"):
            parsed[path] = _strict_json_bytes(payload, path)
    return raw, parsed


def _load_locked_objects(
    objects: list[dict[str, str]], commit: str
) -> tuple[dict[str, bytes], dict[str, Any]]:
    if [row["path"] for row in objects] != SOURCE_PATHS:
        raise ProofError("predecessor source path/order drift")
    raw: dict[str, bytes] = {}
    parsed: dict[str, Any] = {}
    for row in objects:
        path = row["path"]
        object_spec = f"{commit}:{path}"
        if _git_text("cat-file", "-t", object_spec) != "blob":
            raise ProofError(f"predecessor source object is not a blob: {path}")
        payload = _git("show", object_spec)
        if _sha256(payload) != row["sha256"]:
            raise ProofError(f"predecessor source digest mismatch: {path}")
        raw[path] = payload
        if path.endswith(".json"):
            parsed[path] = _strict_json_bytes(payload, object_spec)
    return raw, parsed


def _id_map(rows: list[dict[str, Any]], key: str, label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        identity = row.get(key)
        if not isinstance(identity, str) or not identity or identity in result:
            raise ProofError(f"invalid or duplicate {label} ID")
        result[identity] = row
    return result


def _migrated_ids(compiler_bytes: bytes, label: str) -> set[str]:
    try:
        tree = ast.parse(compiler_bytes, filename=label)
    except SyntaxError as exc:
        raise ProofError(f"cannot parse {label}") from exc
    assignments = [
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "MIGRATED_ENTRY_CAPABILITY_IDS" for target in node.targets)
    ]
    if len(assignments) != 1:
        raise ProofError(f"MIGRATED_ENTRY_CAPABILITY_IDS definition drift: {label}")
    try:
        value = ast.literal_eval(assignments[0].value)
    except (ValueError, TypeError) as exc:
        raise ProofError(f"MIGRATED_ENTRY_CAPABILITY_IDS is not literal: {label}") from exc
    if not isinstance(value, set) or not all(isinstance(item, str) for item in value):
        raise ProofError(f"MIGRATED_ENTRY_CAPABILITY_IDS type drift: {label}")
    return value


def _exact_mappings(
    manifest: dict[str, Any], capabilities: dict[str, Any], oracles: dict[str, Any]
) -> tuple[list[dict[str, str]], int]:
    cap_map = _id_map(capabilities["capabilities"], "id", "capability")
    oracle_by_capability: dict[str, dict[str, Any]] = {}
    for oracle in oracles["oracles"]:
        capability_id = oracle.get("capability_id")
        if not isinstance(capability_id, str) or capability_id in oracle_by_capability:
            raise ProofError("invalid or duplicate oracle capability binding")
        oracle_by_capability[capability_id] = oracle
    if set(oracle_by_capability) != set(cap_map):
        raise ProofError("capability/oracle binding set mismatch")

    features = manifest.get("features")
    if not isinstance(features, list):
        raise ProofError("manifest features must be an array")
    seen_feature_ids: set[str] = set()
    mappings: list[dict[str, str]] = []
    advertised_total = 0
    for feature_index, feature in enumerate(features):
        feature_id = feature.get("id")
        if not isinstance(feature_id, str) or not feature_id or feature_id in seen_feature_ids:
            raise ProofError("invalid or duplicate manifest feature ID")
        seen_feature_ids.add(feature_id)
        capability_ids = feature.get("official_capability_ids", [])
        advertised = feature.get("advertised", [])
        if not isinstance(capability_ids, list) or not isinstance(advertised, list):
            raise ProofError(f"invalid feature arrays: {feature_id}")
        title_to_ids: dict[str, list[str]] = {}
        for capability_id in capability_ids:
            capability = cap_map.get(capability_id)
            if capability is None:
                raise ProofError(f"manifest capability absent from ledger: {capability_id}")
            if capability.get("feature_id") != feature_id:
                raise ProofError(f"capability feature mismatch: {capability_id}")
            title = capability.get("title")
            if not isinstance(title, str) or not title:
                raise ProofError(f"invalid capability title: {capability_id}")
            title_to_ids.setdefault(title, []).append(capability_id)
        for advertised_index, literal in enumerate(advertised):
            advertised_total += 1
            if not isinstance(literal, str) or not literal:
                raise ProofError(f"invalid advertised literal: {feature_id}")
            candidates = title_to_ids.get(literal, [])
            if len(candidates) > 1:
                raise ProofError(f"ambiguous exact title mapping: {feature_id}:{literal}")
            if candidates:
                capability_id = candidates[0]
                oracle = oracle_by_capability[capability_id]
                mappings.append(
                    {
                        "manifest_pointer": f"/features/{feature_index}/advertised/{advertised_index}",
                        "feature_id": feature_id,
                        "advertised": literal,
                        "capability_id": capability_id,
                        "oracle_id": oracle["oracle_id"],
                    }
                )
    if len({row["manifest_pointer"] for row in mappings}) != len(mappings):
        raise ProofError("duplicate exact mapping pointer")
    if len({row["capability_id"] for row in mappings}) != len(mappings):
        raise ProofError("one capability maps to multiple advertised entries")
    return mappings, advertised_total


def _plan_semantics(plan: dict[str, Any]) -> dict[str, Any]:
    result = dict(plan)
    for key in ("plan_payload_sha256", "source_locks", "summary"):
        result.pop(key, None)
    return result


def _verify_frozen_tooling_package(contract: dict[str, Any]) -> dict[str, Any]:
    package = contract["frozen_predecessor_package"]
    expected_path = "deploy/docker/thor-local/qualification/tooling-entry-ledger-successor"
    if package["id"] != "tooling-entry-ledger-successor" or package["path"] != expected_path:
        raise ProofError("frozen tooling successor package identity drift")
    tree_oid = _git_text("rev-parse", f"{PREDECESSOR_COMMIT}:{expected_path}")
    if tree_oid != package["tree_oid"] or _git_text("cat-file", "-t", tree_oid) != "tree":
        raise ProofError("frozen tooling successor package tree mismatch")
    expected_names = [
        "EVIDENCE.md", "README.md", "contract.json", "contract.schema.json",
        "executor.py", "result.schema.json", "tests/test_executor.py",
    ]
    if [Path(row["path"]).relative_to(expected_path).as_posix() for row in package["files"]] != expected_names:
        raise ProofError("frozen tooling successor package file/order drift")
    for row in package["files"]:
        if not row["path"].startswith(expected_path + "/"):
            raise ProofError("frozen tooling successor artifact escapes package")
        payload = _git("show", f"{PREDECESSOR_COMMIT}:{row['path']}")
        if _sha256(payload) != row["sha256"]:
            raise ProofError(f"frozen tooling successor artifact digest mismatch: {row['path']}")
    return {
        "id": package["id"],
        "tree_oid": tree_oid,
        "file_count": len(package["files"]),
        "execution_state": "identity_verified_not_reexecuted",
    }


def compile_proof(contract: dict[str, Any], old_raw: dict[str, bytes], old: dict[str, Any], new_raw: dict[str, bytes], new: dict[str, Any]) -> dict[str, Any]:
    old_plan = old[PLAN_PATH]
    new_plan = new[PLAN_PATH]
    old_denominator = contract["predecessor"]["denominator"]
    new_denominator = contract["successor"]["denominator"]
    if len(old_plan["entries"]) != 74 or len(new_plan["entries"]) != 74:
        raise ProofError("scoped advertised gap denominator drift")
    if old_plan["plan_payload_sha256"] != contract["predecessor"]["plan_payload_sha256"]:
        raise ProofError("predecessor plan payload mismatch")
    if new_plan["plan_payload_sha256"] != contract["successor"]["plan_payload_sha256"]:
        raise ProofError("successor plan payload mismatch")
    for plan, expected, label in (
        (old_plan, old_denominator, "predecessor"),
        (new_plan, new_denominator, "successor"),
    ):
        summary = plan["summary"]
        if summary.get("open_unverified_entries") != expected["explicit_missing_entry_gap"]:
            raise ProofError(f"{label} explicit gap denominator mismatch")
        if summary.get("advertised_entries_without_entry_specific_capability_mapping") != expected["missing_exact_mapping"]:
            raise ProofError(f"{label} missing exact mapping denominator mismatch")
        if summary.get("family_only_entries_outside_this_plan") != expected["family_only_unreviewed"]:
            raise ProofError(f"{label} family-only denominator mismatch")
        if summary.get("runtime_evidence_count") != 0:
            raise ProofError(f"{label} runtime evidence count is nonzero")

    for path in (MANIFEST_PATH, CAPABILITIES_PATH, ORACLES_PATH):
        if old_raw[path] != new_raw[path]:
            raise ProofError(f"semantic ledger source changed across transition: {path}")
    if _plan_semantics(old_plan) != _plan_semantics(new_plan):
        raise ProofError("74-entry gap plan changed beyond summary/source locks/payload")

    mappings, advertised_total = _exact_mappings(
        new[MANIFEST_PATH], new[CAPABILITIES_PATH], new[ORACLES_PATH]
    )
    old_migrated = _migrated_ids(old_raw[COMPILER_PATH], "predecessor gap compiler")
    if _migrated_ids(new_raw[COMPILER_PATH], "successor gap compiler") != old_migrated:
        raise ProofError("canonical manifest-entry migration set changed")
    predecessor_mappings = [row for row in mappings if row["capability_id"] in old_migrated]
    newly_recognized = [row for row in mappings if row["capability_id"] not in old_migrated]
    cap_map = _id_map(new[CAPABILITIES_PATH]["capabilities"], "id", "capability")
    oracle_map = _id_map(new[ORACLES_PATH]["oracles"], "oracle_id", "oracle")

    if advertised_total != 500 or len(mappings) != 289:
        raise ProofError("successor exact-title mapping denominator drift")
    if len(predecessor_mappings) != 13 or set(row["capability_id"] for row in predecessor_mappings) != old_migrated:
        raise ProofError("predecessor exact-title mapping denominator/set drift")
    if len(newly_recognized) != 276:
        raise ProofError("new exact-title mapping denominator drift")
    if any(row["capability_id"].startswith("manifest-entry.") for row in newly_recognized):
        raise ProofError("newly recognized mapping is a canonical manifest-entry capability")
    if {row["capability_id"] for row in mappings} != set(cap_map):
        raise ProofError("exact-title mappings do not cover every capability exactly once")
    for row in mappings:
        capability = cap_map[row["capability_id"]]
        oracle = oracle_map.get(row["oracle_id"])
        if capability["title"] != row["advertised"] or capability["feature_id"] != row["feature_id"]:
            raise ProofError(f"exact title/feature invariant failed: {row['capability_id']}")
        if oracle is None or oracle["capability_id"] != row["capability_id"]:
            raise ProofError(f"bound oracle invariant failed: {row['capability_id']}")

    capabilities = new[CAPABILITIES_PATH]["capabilities"]
    oracles = new[ORACLES_PATH]["oracles"]
    if any(capability.get("evidence", []) for capability in capabilities):
        raise ProofError("capability runtime evidence is nonempty")
    if any(oracle.get("evidence", []) for oracle in oracles):
        raise ProofError("oracle runtime evidence is nonempty")
    if any(capability.get("runtime_state") == "passed_current" for capability in capabilities):
        raise ProofError("passed_current capability promotion detected")
    if new_plan["policy"].get("warehouse_sample_bundle") != "excluded":
        raise ProofError("Warehouse sample is not excluded by gap plan")
    if any(oracle.get("execution_bounds", {}).get("warehouse_sample_bundle") != "excluded" for oracle in oracles):
        raise ProofError("Warehouse sample is not excluded by every oracle bound")

    frozen = _verify_frozen_tooling_package(contract)
    mapping_hash = _sha256(_canonical_bytes(mappings))
    newly_recognized_hash = _sha256(_canonical_bytes(newly_recognized))
    semantic_gap_hash = _sha256(_canonical_bytes(_plan_semantics(new_plan)))
    return {
        "schema_version": 1,
        "mode": contract["mode"],
        "predecessor": {
            "commit": PREDECESSOR_COMMIT,
            "advertised_entry_count": 500,
            "exact_mapping_count": 13,
            "missing_exact_mapping_count": 487,
            "family_only_unreviewed_count": 413,
            "explicit_missing_entry_gap_count": 74,
            "plan_payload_sha256": old_plan["plan_payload_sha256"],
        },
        "successor": {
            "advertised_entry_count": 500,
            "exact_mapping_count": 289,
            "missing_exact_mapping_count": 211,
            "family_only_unreviewed_count": 137,
            "explicit_missing_entry_gap_count": 74,
            "plan_payload_sha256": new_plan["plan_payload_sha256"],
        },
        "transition": {
            "new_exact_mapping_count": 276,
            "existing_non_manifest_entry_capability_count": 276,
            "byte_identical_title_match_count": 276,
            "same_feature_match_count": 276,
            "bound_oracle_count": 276,
            "all_exact_mapping_rows_sha256": mapping_hash,
            "new_exact_mapping_rows_sha256": newly_recognized_hash,
            "capability_records_unchanged": 289,
            "oracle_records_unchanged": 289,
            "gap_entries_semantically_unchanged": 74,
            "gap_semantics_sha256": semantic_gap_hash,
            "capability_runtime_evidence_count": 0,
            "oracle_runtime_evidence_count": 0,
            "plan_runtime_evidence_count": 0,
            "passed_current_promotions": 0,
            "warehouse_sample_bundle": "excluded",
        },
        "frozen_predecessor_package": frozen,
        "effects": {
            "can_mark_passed_current": False,
            "runtime_evidence": [],
            "network_used": False,
            "docker_used": False,
            "runtime_used": False,
            "downloads_used": False,
            "host_inspection_used": False,
            "subprocess_scope": "read_only_local_git_objects_only",
            "git_commands": ["rev-parse", "cat-file", "show"],
        },
        "limitations": [
            "semantic_inventory_mapping_only_not_runtime_qualification",
            "two_hundred_eleven_advertised_entries_still_lack_exact_capability_mapping",
            "historical_tooling_successor_identity_verified_not_reexecuted",
            "warehouse_sample_bundle_excluded_custom_data_warehouse_remains_in_scope",
        ],
    }


def execute(contract_path: Path = CONTRACT_PATH, expected_raw_sha256: str | None = None) -> dict[str, Any]:
    raw_contract = _regular_file(contract_path, str(contract_path)).read_bytes()
    expected = CONTRACT_RAW_SHA256 if expected_raw_sha256 is None else expected_raw_sha256
    if _sha256(raw_contract) != expected:
        raise ProofError("contract raw digest mismatch")
    contract = _strict_json_bytes(raw_contract, str(contract_path))
    _validate(contract, CONTRACT_SCHEMA_PATH, "contract")
    if contract["policy"]["allowed_git_commands"] != ["rev-parse", "cat-file", "show"]:
        raise ProofError("allowed Git command policy drift")
    old_raw, old = _load_predecessor(contract)
    new_raw, new = _load_current(contract)
    proof = compile_proof(contract, old_raw, old, new_raw, new)
    _validate(proof, PROOF_SCHEMA_PATH, "proof")
    return proof


def _render(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify the committed proof byte-for-byte")
    args = parser.parse_args(argv)
    try:
        rendered = _render(execute())
        if args.check:
            if _regular_file(PROOF_PATH, "proof.json").read_bytes() != rendered:
                raise ProofError("committed proof artifact drift")
            print("PASS: exact-title mapping transition 13->289 verified without runtime promotion")
        else:
            sys.stdout.buffer.write(rendered)
    except ProofError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
