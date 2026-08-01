#!/usr/bin/env python3
"""Validate Wave 7's remaining source-only advertised-entry candidates.

This executor is deliberately read-only and candidate-only. It performs no
network, Docker, subprocess, credential, download, lifecycle, model, or sample
Warehouse action and cannot promote an official capability or oracle.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4]
INVENTORY_PATH = HERE / "inventory.json"
INVENTORY_SCHEMA_PATH = HERE / "inventory.schema.json"
RESULT_SCHEMA_PATH = HERE / "result.schema.json"
MAX_SOURCE_BYTES = 5_000_000

EXPECTED_INVENTORY_SHA256 = (
    "13219546fbc70a92c8593512d2af405cd977136525721d7f8b063e02025230fa"
)
EXPECTED_INVENTORY_SCHEMA_SHA256 = (
    "2c6d1c09f00a595870c5f375c077276cac290eaa5f434380fcd9313767e2c3a6"
)
EXPECTED_RESULT_SCHEMA_SHA256 = (
    "c51e34eca3a693a105f6d82769f6024f7ca3a64357581d74e4c214938d7b7fe2"
)
EXPECTED_SOURCE_PLAN = {
    "path": "deploy/docker/thor-local/qualification/advertised-entry-gaps/plan.json",
    "raw_sha256": "dd3c8cbbcae859137e73da4a8d4d9227f535dd674979b5d9e8f5cf25b885d122",
    "plan_payload_sha256": "97cb92ffb83d05388759f7428324344f91ec294116e5d24721c1ba21d994ab7d",
}
EXPECTED_SOURCE_MANIFEST = {
    "path": "deploy/docker/thor-local/parity/manifest.json",
    "raw_sha256": "6b041fbd169649b6dac5e68908e4a6dd219da9160cf72594219058885a9b9127",
}
EXPECTED_LIVE_OFFICIAL_CAPABILITIES = {
    "path": "deploy/docker/thor-local/parity/official-capabilities.json",
    "raw_sha256": "53670839f97b50238580741e71ae54a28ef50a7259ee1a847ebc66fc7a26c47d",
}
EXPECTED_LIVE_CAPABILITY_ORACLES = {
    "path": "deploy/docker/thor-local/parity/capability-oracles.json",
    "raw_sha256": "a061b5aca1a27df1e34a8a6480d01843b77609821b93792ed9047c8209ce808f",
}
EXPECTED_PREDECESSORS = [
    {
        "path": "deploy/docker/thor-local/qualification/advertised-entry-executors/inventory.json",
        "raw_sha256": "91406a15ff1340b9b4dba988507470234971fa4905997bc52e64fb983fc12a18",
    },
    {
        "path": "deploy/docker/thor-local/qualification/advertised-entry-executors-wave2/inventory.json",
        "raw_sha256": "2c14f8ae5ade22ccbc556a844b4fcb63661048826660073fb21c5f882047c5d2",
    },
    {
        "path": "deploy/docker/thor-local/qualification/advertised-entry-executors-wave3/inventory.json",
        "raw_sha256": "0b7056eafce7686fc2b7315fef8ae491ddef03d2e52f41e7c7861247933f90ab",
    },
    {
        "path": "deploy/docker/thor-local/qualification/advertised-entry-executors-wave4/inventory.json",
        "raw_sha256": "1de6e9be3c93c349e45b192506e3081758553582dda6f73b79877bc4ff5155a6",
    },
    {
        "path": "deploy/docker/thor-local/qualification/advertised-entry-executors-wave5/inventory.json",
        "raw_sha256": "98876a18d628df644171cd1d0051753dadd904cca67a5fe0fa8696832cb08771",
    },
    {
        "path": "deploy/docker/thor-local/qualification/advertised-entry-executors-wave6/inventory.json",
        "raw_sha256": "dbc1045b5d9e6b02ab152f2f0cc9007c0087e265692ef4e4aa911dc12f7935e3",
    },
]
EXPECTED_DETECTION = {
    "path": "deploy/docker/thor-local/qualification/detection-map-static-executor/contract.json",
    "raw_sha256": "5ca96f6923dee872182ad6af782270d4df14cec17044eebbfd0121601b84bdbc",
    "entry_id": "manifest-gap.spatial-ai-utils.03-detection-map",
}
EXPECTED_POLICY = {
    "candidate_only": True,
    "can_mark_passed_current": False,
    "live_acceptance_mutation_allowed": False,
    "live_oracle_mutation_allowed": False,
    "runtime_evidence": [],
    "network_allowed": False,
    "docker_allowed": False,
    "subprocess_allowed": False,
    "lifecycle_allowed": False,
    "downloads_allowed": False,
    "credentials_allowed": False,
    "warehouse_sample_bundle": "excluded",
    "file_writes_allowed": False,
}
EXPECTED_DENOMINATOR = {
    "advertised_gap_entries": 87,
    "previous_wave_candidates": 71,
    "separate_detection_map_candidates": 1,
    "pre_wave7_candidates": 72,
    "wave7_remaining_entries": 15,
    "selected_source_candidates": 11,
    "external_attestation_blockers": 4,
    "post_wave7_candidates": 83,
    "entries_without_candidate": 4,
    "official_open_entries": 87,
}
EXPECTED_CASE_IDS = {
    "manifest-gap.search-scale.00-configuration-up-to-100-streams",
    "manifest-gap.search-scale.01-16-concurrent-1080p-streams-tested-by-nvidia",
    "manifest-gap.rt-cv-3d-sparse4d.00-sparse4d-multi-camera-3d-detection-and-tracking",
    "manifest-gap.rt-cv-3d-sparse4d.01-shared-rt-cv-lifecycle-health-metrics",
    "manifest-gap.rt-cv-3d-mv3dt.00-per-camera-rt-detr",
    "manifest-gap.rt-cv-3d-mv3dt.01-mv3dt-bev-fusion",
    "manifest-gap.rt-cv-3d-mv3dt.02-bodypose3dnet",
    "manifest-gap.rt-cv-3d-mv3dt.03-four-camera-calibrated-multiview-tracking",
    "manifest-gap.audio-understanding.00-audio-aware-base-workflow",
    "manifest-gap.audio-understanding.01-audio-transcript-per-rt-vlm-chunk",
    "manifest-gap.audio-understanding.02-audio-aware-summarization-and-alerts",
}
EXPECTED_BLOCKED_IDS = {
    "manifest-gap.alert-notifications-slack.00-slack-notification",
    "manifest-gap.spatial-ai-utils.07-aws-gcs-validation",
    "manifest-gap.enterprise-rag.00-rag-report-generation",
    "manifest-gap.enterprise-rag.01-frag-retrieval-integration",
}
ALLOWED_CASE_ORACLE_TYPES = {
    "runtime_scale_benchmark",
    "runtime_custom_data_multicamera",
    "runtime_audio_semantics",
}


class QualificationError(RuntimeError):
    """A schema, lock, denominator, source, or boundary check failed."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
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


def _read_package_file(path: Path, expected_sha256: str, label: str) -> bytes:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise QualificationError(f"{label} is unavailable") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise QualificationError(f"{label} must be a regular non-symlink")
    data = path.read_bytes()
    if _sha256(data) != expected_sha256:
        raise QualificationError(f"{label} raw digest mismatch")
    return data


def _safe_repo_path(repo_root: Path, relative_path: str) -> Path:
    pure = PurePosixPath(relative_path)
    if pure.is_absolute() or not pure.parts or ".." in pure.parts:
        raise QualificationError(f"unsafe repository path: {relative_path}")
    root = repo_root.resolve(strict=True)
    candidate = root
    for part in pure.parts:
        candidate /= part
        try:
            metadata = candidate.lstat()
        except OSError as exc:
            raise QualificationError(
                f"repository input is unavailable: {relative_path}"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise QualificationError(
                f"repository input contains a symlink: {relative_path}"
            )
    resolved = candidate.resolve(strict=True)
    if resolved != root and root not in resolved.parents:
        raise QualificationError(f"repository input escaped root: {relative_path}")
    if not resolved.is_file():
        raise QualificationError(
            f"repository input must be a regular file: {relative_path}"
        )
    return resolved


def _read_repo_bytes(
    repo_root: Path, relative_path: str, *, max_bytes: int = MAX_SOURCE_BYTES
) -> bytes:
    path = _safe_repo_path(repo_root, relative_path)
    if path.stat().st_size > max_bytes:
        raise QualificationError(
            f"repository input exceeds {max_bytes} bytes: {relative_path}"
        )
    data = path.read_bytes()
    if len(data) > max_bytes:
        raise QualificationError(
            f"repository input exceeds {max_bytes} bytes: {relative_path}"
        )
    return data


def _validate_schema(instance: Any, schema_bytes: bytes, label: str) -> None:
    schema = _strict_json_bytes(schema_bytes, f"{label} schema")
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise QualificationError(f"invalid {label} JSON schema") from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(instance),
        key=lambda error: [str(item) for item in error.absolute_path],
    )
    if errors:
        first = errors[0]
        where = "/" + "/".join(str(item) for item in first.absolute_path)
        raise QualificationError(
            f"{label} schema validation failed at {where}: {first.message}"
        )


def _resolve_pointer(document: Any, pointer: str) -> Any:
    if not pointer.startswith("/"):
        raise QualificationError(f"invalid JSON pointer: {pointer}")
    value = document
    try:
        for token in pointer.split("/")[1:]:
            token = token.replace("~1", "/").replace("~0", "~")
            value = value[int(token)] if isinstance(value, list) else value[token]
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        raise QualificationError(f"unresolved JSON pointer: {pointer}") from exc
    return value


def _load_locked_json(
    repo_root: Path, lock: dict[str, str], label: str
) -> tuple[Any, bytes]:
    raw = _read_repo_bytes(repo_root, lock["path"])
    actual = _sha256(raw)
    if actual != lock["raw_sha256"]:
        raise QualificationError(
            f"{label} raw digest mismatch for {lock['path']}: {actual}"
        )
    return _strict_json_bytes(raw, lock["path"]), raw


def _verify_inventory_boundary(inventory: dict[str, Any]) -> None:
    if inventory.get("source_plan") != EXPECTED_SOURCE_PLAN:
        raise QualificationError("source plan binding drift")
    if inventory.get("source_manifest") != EXPECTED_SOURCE_MANIFEST:
        raise QualificationError("source manifest binding drift")
    if (
        inventory.get("live_official_capabilities")
        != EXPECTED_LIVE_OFFICIAL_CAPABILITIES
    ):
        raise QualificationError("live official-capability binding drift")
    if inventory.get("live_capability_oracles") != EXPECTED_LIVE_CAPABILITY_ORACLES:
        raise QualificationError("live capability-oracle binding drift")
    if inventory.get("previous_candidate_inventories") != EXPECTED_PREDECESSORS:
        raise QualificationError("six-wave predecessor binding drift")
    if inventory.get("separate_detection_map_candidate") != EXPECTED_DETECTION:
        raise QualificationError("separate detection-map binding drift")
    if inventory.get("policy") != EXPECTED_POLICY:
        raise QualificationError("candidate-only safety policy drift")
    if inventory.get("denominator") != EXPECTED_DENOMINATOR:
        raise QualificationError("Wave 7 denominator drift")

    cases = inventory.get("cases")
    blocked = inventory.get("blocked_entries")
    if not isinstance(cases, list) or not isinstance(blocked, list):
        raise QualificationError("case/blocker collections are malformed")
    case_ids = [item.get("entry_id") for item in cases if isinstance(item, dict)]
    blocked_ids = [item.get("entry_id") for item in blocked if isinstance(item, dict)]
    if len(case_ids) != 11 or set(case_ids) != EXPECTED_CASE_IDS:
        raise QualificationError("Wave 7 candidate identity set drift")
    if len(blocked_ids) != 4 or set(blocked_ids) != EXPECTED_BLOCKED_IDS:
        raise QualificationError("Wave 7 external blocker identity set drift")
    if len(case_ids) != len(set(case_ids)) or len(blocked_ids) != len(set(blocked_ids)):
        raise QualificationError("duplicate Wave 7 entry identity")
    if set(case_ids) & set(blocked_ids):
        raise QualificationError("candidate and blocker partitions overlap")


def _verify_denominator(
    repo_root: Path,
    inventory: dict[str, Any],
    plan: dict[str, Any],
    detection_contract: dict[str, Any],
) -> None:
    plan_entries = plan.get("entries")
    if not isinstance(plan_entries, list) or len(plan_entries) != 87:
        raise QualificationError("advertised-gap plan denominator drift")
    all_ids = [item.get("entry_id") for item in plan_entries if isinstance(item, dict)]
    if len(all_ids) != 87 or len(set(all_ids)) != 87:
        raise QualificationError(
            "advertised-gap plan identities are not exactly unique"
        )

    previous: set[str] = set()
    for lock in EXPECTED_PREDECESSORS:
        predecessor, _ = _load_locked_json(repo_root, lock, "predecessor inventory")
        rows = predecessor.get("cases") if isinstance(predecessor, dict) else None
        if not isinstance(rows, list):
            raise QualificationError("predecessor inventory cases are malformed")
        ids = {row.get("entry_id") for row in rows if isinstance(row, dict)}
        if len(ids) != len(rows) or previous & ids:
            raise QualificationError("predecessor candidate inventories overlap")
        previous |= ids
    if len(previous) != 71:
        raise QualificationError("six-wave candidate denominator is not 71")

    detection_id = detection_contract.get("entry", {}).get("entry_id")
    if detection_id != EXPECTED_DETECTION["entry_id"]:
        raise QualificationError("detection-map contract entry drift")
    if detection_id in previous:
        raise QualificationError("detection-map candidate overlaps Waves 1-6")

    case_ids = {item["entry_id"] for item in inventory["cases"]}
    blocker_ids = {item["entry_id"] for item in inventory["blocked_entries"]}
    if previous & case_ids or previous & blocker_ids:
        raise QualificationError("Wave 7 entries overlap Waves 1-6")
    if detection_id in case_ids | blocker_ids:
        raise QualificationError("detection-map entry leaked into Wave 7's 15")
    if previous | {detection_id} | case_ids | blocker_ids != set(all_ids):
        raise QualificationError("87-entry denominator is not an exact partition")
    if len(case_ids) + len(blocker_ids) != 15:
        raise QualificationError("Wave 7 remaining denominator is not 15")


def _verify_plan_payload(plan: dict[str, Any]) -> None:
    if plan.get("plan_payload_sha256") != EXPECTED_SOURCE_PLAN["plan_payload_sha256"]:
        raise QualificationError("plan payload digest binding drift")
    payload = dict(plan)
    observed = payload.pop("plan_payload_sha256", None)
    if _sha256(_canonical_bytes(payload)) != observed:
        raise QualificationError("plan payload digest is internally inconsistent")


def _verify_live_open(
    plan: dict[str, Any],
    official_capabilities: dict[str, Any],
    capability_oracles: dict[str, Any],
) -> None:
    entries = plan.get("entries")
    capabilities = official_capabilities.get("capabilities")
    oracles = capability_oracles.get("oracles")
    if not isinstance(entries, list) or not isinstance(capabilities, list):
        raise QualificationError("live official-capability document is malformed")
    if not isinstance(oracles, list):
        raise QualificationError("live capability-oracle document is malformed")

    proposed_ids = {
        entry.get("proposed_capability", {}).get("id")
        for entry in entries
        if isinstance(entry, dict)
    }
    capability_ids = {row.get("id") for row in capabilities if isinstance(row, dict)}
    oracle_capability_ids = {
        row.get("capability_id") for row in oracles if isinstance(row, dict)
    }
    if len(proposed_ids) != 87 or None in proposed_ids:
        raise QualificationError("87 proposed capability identities are not exact")
    if proposed_ids & capability_ids:
        raise QualificationError("advertised-gap capability was promoted live")
    if proposed_ids & oracle_capability_ids:
        raise QualificationError("advertised-gap oracle was materialized live")

    for entry in entries:
        required_oracle = entry.get("required_oracle")
        if (
            entry.get("coverage_state") != "open_missing_entry_capability_and_oracle"
            or not isinstance(required_oracle, dict)
            or required_oracle.get("status") != "open_unexecuted"
            or required_oracle.get("runtime_evidence") != []
        ):
            raise QualificationError(
                f"advertised-gap plan entry is not live-open: {entry.get('entry_id')}"
            )


def _bind_plan_entry(
    row: dict[str, Any], plan_by_id: dict[str, dict[str, Any]], manifest: dict[str, Any]
) -> dict[str, Any]:
    entry_id = row["entry_id"]
    plan_entry = plan_by_id.get(entry_id)
    if plan_entry is None:
        raise QualificationError(f"plan entry is missing: {entry_id}")
    for field in (
        "manifest_pointer",
        "entry_id",
        "advertised",
        "advertised_utf8_sha256",
        "advertised_canonical_sha256",
    ):
        if row[field] != plan_entry.get(field):
            raise QualificationError(f"{entry_id}: plan binding differs for {field}")
    if row.get("proposed_capability_id") is not None and row[
        "proposed_capability_id"
    ] != plan_entry.get("proposed_capability", {}).get("id"):
        raise QualificationError(f"{entry_id}: proposed capability binding differs")
    advertised = row["advertised"]
    if _sha256(advertised.encode("utf-8")) != row["advertised_utf8_sha256"]:
        raise QualificationError(f"{entry_id}: advertised UTF-8 digest differs")
    if _sha256(_canonical_bytes(advertised)) != row["advertised_canonical_sha256"]:
        raise QualificationError(f"{entry_id}: advertised canonical digest differs")
    if _resolve_pointer(manifest, row["manifest_pointer"]) != advertised:
        raise QualificationError(f"{entry_id}: manifest pointer binding differs")
    required_oracle = plan_entry.get("required_oracle")
    if not isinstance(required_oracle, dict):
        raise QualificationError(f"{entry_id}: required oracle is malformed")
    if (
        _sha256(_canonical_bytes(required_oracle))
        != row["required_oracle_canonical_sha256"]
    ):
        raise QualificationError(f"{entry_id}: required oracle digest differs")
    if (
        required_oracle.get("status") != "open_unexecuted"
        or required_oracle.get("runtime_evidence") != []
    ):
        raise QualificationError(f"{entry_id}: required oracle is not open/unexecuted")
    return required_oracle


def _observe_case(
    repo_root: Path,
    row: dict[str, Any],
    plan_by_id: dict[str, dict[str, Any]],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    required_oracle = _bind_plan_entry(row, plan_by_id, manifest)
    if required_oracle.get("type") not in ALLOWED_CASE_ORACLE_TYPES:
        raise QualificationError(
            f"{row['entry_id']}: source candidate crossed into forbidden oracle class"
        )
    if "no " not in row["evidence_scope"].lower():
        raise QualificationError(f"{row['entry_id']}: evidence scope lacks exclusions")

    locks = row["source_locks"]
    by_path = {item["path"]: item["sha256"] for item in locks}
    if len(by_path) != len(locks):
        raise QualificationError(f"{row['entry_id']}: duplicate source lock path")
    source_sha256: dict[str, str] = {}
    source_text: dict[str, str] = {}
    for path, expected in by_path.items():
        raw = _read_repo_bytes(repo_root, path)
        actual = _sha256(raw)
        if actual != expected:
            raise QualificationError(
                f"{row['entry_id']}: source digest mismatch for {path}: {actual}"
            )
        try:
            source_text[path] = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise QualificationError(
                f"{row['entry_id']}: source is not UTF-8 text: {path}"
            ) from exc
        source_sha256[path] = actual

    assertion_sha256: list[str] = []
    asserted_paths: set[str] = set()
    for assertion in row["source_assertions"]:
        path = assertion["path"]
        if path not in source_text:
            raise QualificationError(
                f"{row['entry_id']}: assertion path is not source-locked: {path}"
            )
        asserted_paths.add(path)
        for fragment in assertion["fragments"]:
            if fragment not in source_text[path]:
                raise QualificationError(
                    f"{row['entry_id']}: semantic source fragment missing in {path}: {fragment!r}"
                )
            assertion_sha256.append(
                _sha256(_canonical_bytes({"path": path, "fragment": fragment}))
            )
    if asserted_paths != set(by_path):
        raise QualificationError(
            f"{row['entry_id']}: every locked source must have a semantic assertion"
        )
    if len(assertion_sha256) != len(set(assertion_sha256)):
        raise QualificationError(f"{row['entry_id']}: duplicate semantic assertion")
    return {
        "entry_id": row["entry_id"],
        "adapter_id": row["adapter_id"],
        "observation": "source_subset_match_candidate_only",
        "evidence_scope": row["evidence_scope"],
        "source_sha256": source_sha256,
        "assertion_sha256": sorted(assertion_sha256),
        "required_oracle": required_oracle,
        "full_oracle_status": "open_unexecuted",
        "can_mark_passed_current": False,
        "runtime_evidence": [],
    }


def execute(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    inventory_raw = _read_package_file(
        INVENTORY_PATH, EXPECTED_INVENTORY_SHA256, "Wave 7 inventory"
    )
    inventory_schema_raw = _read_package_file(
        INVENTORY_SCHEMA_PATH,
        EXPECTED_INVENTORY_SCHEMA_SHA256,
        "Wave 7 inventory schema",
    )
    result_schema_raw = _read_package_file(
        RESULT_SCHEMA_PATH, EXPECTED_RESULT_SCHEMA_SHA256, "Wave 7 result schema"
    )
    inventory = _strict_json_bytes(inventory_raw, "Wave 7 inventory")
    _validate_schema(inventory, inventory_schema_raw, "inventory")
    _verify_inventory_boundary(inventory)

    plan, _ = _load_locked_json(repo_root, EXPECTED_SOURCE_PLAN, "source plan")
    manifest, _ = _load_locked_json(
        repo_root, EXPECTED_SOURCE_MANIFEST, "source manifest"
    )
    official_capabilities, _ = _load_locked_json(
        repo_root,
        EXPECTED_LIVE_OFFICIAL_CAPABILITIES,
        "live official capabilities",
    )
    capability_oracles, _ = _load_locked_json(
        repo_root,
        EXPECTED_LIVE_CAPABILITY_ORACLES,
        "live capability oracles",
    )
    detection_contract, _ = _load_locked_json(
        repo_root, EXPECTED_DETECTION, "detection-map contract"
    )
    if (
        not isinstance(plan, dict)
        or not isinstance(manifest, dict)
        or not isinstance(official_capabilities, dict)
        or not isinstance(capability_oracles, dict)
        or not isinstance(detection_contract, dict)
    ):
        raise QualificationError("locked root document is not an object")
    _verify_plan_payload(plan)
    _verify_denominator(repo_root, inventory, plan, detection_contract)
    _verify_live_open(plan, official_capabilities, capability_oracles)
    plan_by_id = {entry["entry_id"]: entry for entry in plan["entries"]}

    observations = [
        _observe_case(repo_root, row, plan_by_id, manifest)
        for row in inventory["cases"]
    ]
    blockers: list[dict[str, Any]] = []
    for row in inventory["blocked_entries"]:
        required_oracle = _bind_plan_entry(row, plan_by_id, manifest)
        if required_oracle.get("type") != "external_optional_boundary":
            raise QualificationError(
                f"{row['entry_id']}: blocker is not an external boundary"
            )
        blockers.append(
            {
                "entry_id": row["entry_id"],
                "blocker_type": row["blocker_type"],
                "reason": row["reason"],
                "required_oracle": required_oracle,
                "candidate_materialized": False,
                "runtime_evidence": [],
            }
        )

    all_sources = {
        path: digest
        for observation in observations
        for path, digest in observation["source_sha256"].items()
    }
    result = {
        "schema_version": 1,
        "mode": inventory["mode"],
        "candidate_only": True,
        "can_mark_passed_current": False,
        "official_capability_effect": "none_candidate_only",
        "runtime_evidence": [],
        "network_used": False,
        "docker_used": False,
        "subprocess_used": False,
        "lifecycle_used": False,
        "downloads_used": False,
        "credentials_used": False,
        "warehouse_sample_bundle_used": False,
        "file_writes_used": False,
        "denominator": {
            "advertised_gap_entries": 87,
            "prior_candidates": 72,
            "wave7_candidates": 11,
            "external_blockers": 4,
            "candidate_total": 83,
            "official_open_entries": 87,
        },
        "observations": observations,
        "blocked_entries": blockers,
        "source_tree_sha256": _sha256(_canonical_bytes(all_sources)),
    }
    _validate_schema(result, result_schema_raw, "result")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="validate and print only a status line"
    )
    args = parser.parse_args(argv)
    try:
        result = execute()
    except QualificationError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True))
        return 1
    if args.check:
        print("VALID: 11 Wave 7 source candidates; 4 external blockers preserved")
    else:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
