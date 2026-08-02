#!/usr/bin/env python3
"""Validate the inert 208-candidate execution-binding registry rebase."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import sys
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4].resolve(strict=True)
ARTIFACT_PATH = HERE / "registry.json"
SCHEMA_PATH = HERE / "registry.schema.json"
MAX_BYTES = 96_000_000

MAPPING_DIR = (
    "deploy/docker/thor-local/qualification/"
    "candidate-approval-mapping-rebase-successor-v2"
)
ADAPTER_DIR = "deploy/docker/thor-local/qualification/candidate-oracle-adapter"
WORKLOAD_DIR = "deploy/docker/thor-local/qualification/remaining-entry-workloads"
PROTOCOL_DIR = "deploy/docker/thor-local/qualification/protocol-cases-v2-candidates"
LANE_DIR = "deploy/docker/thor-local/qualification/runtime-lanes"
GUARDED_DIR = (
    "deploy/docker/thor-local/qualification/advertised-entry-executors-74-successor"
)
WAVE8_DIR = (
    "deploy/docker/thor-local/qualification/successor-500-executable-subsets-wave1"
)
BUNDLE_DIR = (
    "deploy/docker/thor-local/qualification/runtime-approval-bundles-rebase-successor"
)
HISTORICAL_DIR = (
    "deploy/docker/thor-local/qualification/"
    "candidate-execution-binding-registry-successor"
)

MAPPING_PATH = f"{MAPPING_DIR}/mapping.json"
ADAPTER_PATH = f"{ADAPTER_DIR}/adapter.json"
WORKLOAD_PATH = f"{WORKLOAD_DIR}/workloads.json"
PROTOCOL_PATH = f"{PROTOCOL_DIR}/protocol-cases-v2-candidate.json"
LANE_PATH = f"{LANE_DIR}/runtime-lane-plan.json"
GUARDED_PATH = f"{GUARDED_DIR}/execution-receipt.json"
WAVE8_PATH = f"{WAVE8_DIR}/execution-receipt.json"
WAVE8_CONTRACT_PATH = f"{WAVE8_DIR}/contract.json"
WAVE8_SUCCESSOR_PATH = f"{WAVE8_DIR}/successor-capability-oracles.json"
BUNDLE_PATH = f"{BUNDLE_DIR}/contract.json"
LOCATOR_ARTIFACT_PATH = HERE / "locator-locks.json"
LOCATOR_SCHEMA_PATH = HERE / "locator-locks.schema.json"

EXPECTED_SOURCE_HASHES = {
    MAPPING_PATH: "cb9bea95b4cfeab7c44441854e331a7093667d6b379fe0555692e5105ce4507f",
    f"{MAPPING_DIR}/mapping.schema.json": "78c118cc062eee15992ad3fcd4fa2d3585e6b80dc5bea7e32806ade1f11ccaba",
    f"{MAPPING_DIR}/compiler.py": "39fa49a730fe5f6d5bff0a2285c9075cdf3707bd28caab5305329faf1d7ad884",
    ADAPTER_PATH: "59359d95ec768ab79f9c7a99404f2a7304addb018bbc3c591900d6ee7e9540b0",
    f"{ADAPTER_DIR}/adapter.schema.json": "d25c9636b4df221f2be8dd689e2f71c1a6fa9a10025a0ec14217631d922d1552",
    f"{ADAPTER_DIR}/compiler.py": "753a7b99ed6d9196680abcba589521d9bd9d40388e6ed7035cf6377005ea3605",
    WORKLOAD_PATH: "ca4170118a94a659acca600d9ab00dca6504544f062edabd5cef0ed3311e8312",
    f"{WORKLOAD_DIR}/workload.schema.json": "736f9295e4f89afbb1aaed7c086155e30a09b6dc2c583433b9cb98ad2c005c14",
    f"{WORKLOAD_DIR}/compiler.py": "0aa1460ed76decf402d770fa7fc0910dae34557a84271c87c64024e5d4b6fe63",
    PROTOCOL_PATH: "cea6cf41109654fa040f120c74a17b253c019b38cfb1a1e8229d370c2f10d5f7",
    f"{PROTOCOL_DIR}/protocol-cases-v2-candidate.schema.json": "399471d0efd73614e507426095390a4a2e731aa4970b916199344b89b0304fbb",
    f"{PROTOCOL_DIR}/compiler.py": "87e3fb6b0894c09ad91b2494bf3e4c6838639d3659eba934ea8ea6183bc961af",
    LANE_PATH: "bf863fac268d1247eda71b9edbfd497580453c52cd3ced7fcdb333386efa25c9",
    f"{LANE_DIR}/runtime-lane-plan.schema.json": "743c0397a35118b7b7ac42589f947ecb7b55dde37e452afb3b40921a10a91039",
    f"{LANE_DIR}/runtime_lane_compiler.py": "684dc7e0ba478697d73b6148725b7d29cf2619d394dc9ccdfdda998f08753372",
    GUARDED_PATH: "acfe8215c0666a990109e2e1d34a531ba5c2b3c2fa415f7cf901c5e7bddec99c",
    f"{GUARDED_DIR}/result.schema.json": "9776016ef702a0437e1926d28a243a5a6e1a135dfd83226c2a9718546c584a43",
    f"{GUARDED_DIR}/executor.py": "0edbe9bb5e29ffe1bd1a72439dd97ed861a14147b20939d514c96bd721af0198",
    WAVE8_CONTRACT_PATH: "fae464894d7d565a1078f852776bb005e0426c4280473d551bbec3e727e2d53c",
    f"{WAVE8_DIR}/contract.schema.json": "aeac007e154451fd33bf17f126b561518d7a2a4ff752b2aa683d56896b9bf84b",
    WAVE8_PATH: "ab07eac3e5c240f55d2480fe34aa5128be0cd62b3a64027e3ae689cb27bd0396",
    f"{WAVE8_DIR}/execution-receipt.schema.json": "f4071b29a45a5d487a241914ef7023fed39f52bc3103704f27ad76a86b3b4618",
    WAVE8_SUCCESSOR_PATH: "1a066029a04bc67bcefd4571f24fce1cda1df275ab48aed48f99ea7e274f10b5",
    f"{WAVE8_DIR}/successor-capability-oracles.schema.json": "ee7391aeb8cb9c433df77df378adcd7cfb0a91c070a1940132e9ab77cdeadbca",
    f"{WAVE8_DIR}/compiler.py": "b8243fc42ad522e0610d0ad076df3cee8019c048aa929cf4eef4b983ee1cd953",
    BUNDLE_PATH: "415931c48a231c150c62d90e134da5f60a75adb8bed653dcef45251ef6caf194",
    f"{BUNDLE_DIR}/contract.schema.json": "2f277445317a052be2399af5f4e6b4ea8c85e3998d5acd67f03aab24b1b2eabe",
    f"{BUNDLE_DIR}/compiler.py": "291cccb9d120e074e3139e6827efab530643085ac64d581c649bca682625883e",
}

EXPECTED_HISTORICAL_HASHES = {
    f"{HISTORICAL_DIR}/README.md": "ac4b39993a5911a36489ebdd80e522c3d41e254a18af08f282b221e25ee7a098",
    f"{HISTORICAL_DIR}/EVIDENCE.md": "e8d60d647e5cf6984625fe84b3d73e605c8478a6c6ef46459ede45ea5541c933",
    f"{HISTORICAL_DIR}/compiler.py": "fadfa7ff38585ce0604b0511113f12f1281016a3b39c08188022eda14144973d",
    f"{HISTORICAL_DIR}/locator-locks.json": "c8311f1dc9eca330a186c43e15766e2daf5418649e41258eb50baa6445a31708",
    f"{HISTORICAL_DIR}/locator-locks.schema.json": "3cad143f04ebb9a80b11e180aed9a6ccb573d247d52b617ea8caeb9805075cb2",
    f"{HISTORICAL_DIR}/registry.json": "59600e64e818b553039dd3d623d1a174714f6f51563da08251560c2994c7f544",
    f"{HISTORICAL_DIR}/registry.schema.json": "04eb378e9891a805069ad293a762c6e71c95498177baf0b5b21cf1db0c46ab7d",
    f"{HISTORICAL_DIR}/tests/test_compiler.py": "5913c9fae13040367d9d9728bf0d57e97cd7534deefd340c5ea81dac96b3e340",
}

EXPECTED_ACTION_COUNTS = {"oracle_only": 127, "protocol": 23, "workload": 58}
EXPECTED_OBSERVER_COUNTS = {
    "absent": 138,
    "guarded_adapter": 68,
    "production_subset": 2,
}
EXPECTED_LANE_COUNTS = {
    "exact_external": 4,
    "family_multi": 28,
    "family_single": 176,
}
EXPECTED_CROSS_TIER_COUNTS = {
    "both": 28,
    "enriched": 53,
    "observer": 42,
    "oracle": 85,
}
EXPECTED_STATIC_GAPS = [
    (101, 390, "manifest-entry.rt-cv-3d-mv3dt.05-associated-skill"),
    (195, 484, "manifest-entry.helm.00-helm-for-four-developer-workflows"),
    (196, 485, "manifest-entry.helm.01-helm-for-most-standalone-services"),
]
EXPECTED_EXTERNAL_IDS = [
    "manifest-entry.alert-notifications-slack.00-slack-notification",
    "manifest-entry.rt-vlm-models.04-remote-openai-compatible-endpoint",
    "manifest-entry.enterprise-rag.00-rag-report-generation",
    "manifest-entry.enterprise-rag.01-frag-retrieval-integration",
]
EXPECTED_PROTOCOL_REBASE_IDS = [
    "manifest-entry.video-summarization-file.03-structured-output",
    "manifest-entry.video-summarization-live.05-sse-mcp-server",
]

EMPTY_AUTHORITATIVE_BINDING = {
    "action_contract_sha256": None,
    "cleanup_executor": None,
    "cleanup_rollback_contract_sha256": None,
    "cleanup_targets": [],
    "compose_paths": [],
    "evidence_destination": None,
    "evidence_records": [],
    "executor": None,
    "postcondition_collectors": [],
    "profile_id": None,
    "profile_paths": [],
    "service_role_profile_binding_sha256": None,
    "service_roles": [],
}


class RegistryError(RuntimeError):
    """A source, identity, projection, or inertness invariant failed."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def strict_json(payload: bytes, label: str) -> dict[str, Any]:
    if len(payload) > MAX_BYTES:
        raise RegistryError(f"{label}: exceeds size bound")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise RegistryError(f"{label}: duplicate JSON key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda token: (_ for _ in ()).throw(
                RegistryError(f"{label}: non-finite JSON number {token}")
            ),
        )
    except RegistryError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RegistryError(f"{label}: invalid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise RegistryError(f"{label}: JSON root must be an object")
    return value


def _repo_path(relative: str) -> Path:
    pure = PurePosixPath(relative)
    if (
        pure.is_absolute()
        or not pure.parts
        or any(part in {"", ".", ".."} for part in pure.parts)
        or pure.as_posix() != relative
    ):
        raise RegistryError(f"unsafe repository path: {relative}")
    path = REPO_ROOT
    for part in pure.parts:
        path /= part
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise RegistryError(f"repository path unavailable: {relative}") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise RegistryError(f"repository path contains a symlink: {relative}")
    if not stat.S_ISREG(path.lstat().st_mode):
        raise RegistryError(f"repository source is not a regular file: {relative}")
    return path


def _read_regular(path: Path, label: str) -> bytes:
    try:
        before = path.lstat()
    except OSError as exc:
        raise RegistryError(f"{label}: unavailable") from exc
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise RegistryError(f"{label}: must be a regular non-symlink")
    if before.st_size > MAX_BYTES:
        raise RegistryError(f"{label}: exceeds size bound")
    payload = path.read_bytes()
    after = path.lstat()
    if (
        before.st_dev != after.st_dev
        or before.st_ino != after.st_ino
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or len(payload) != before.st_size
    ):
        raise RegistryError(f"{label}: changed while reading")
    return payload


def _validate_schema(value: Any, schema: dict[str, Any], label: str) -> None:
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise RegistryError(f"{label}: invalid JSON Schema") from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        first = errors[0]
        where = "/" + "/".join(str(part) for part in first.absolute_path)
        raise RegistryError(f"{label}: schema violation at {where}: {first.message}")


def _load_sources() -> tuple[dict[str, bytes], dict[str, dict[str, Any]]]:
    payloads: dict[str, bytes] = {}
    for relative, expected in {
        **EXPECTED_SOURCE_HASHES,
        **EXPECTED_HISTORICAL_HASHES,
    }.items():
        payload = _read_regular(_repo_path(relative), relative)
        actual = sha256(payload)
        if actual != expected:
            raise RegistryError(
                f"source drift for {relative}: expected {expected}, got {actual}"
            )
        payloads[relative] = payload

    sources: dict[str, dict[str, Any]] = {}
    specs = {
        "mapping": (MAPPING_PATH, f"{MAPPING_DIR}/mapping.schema.json"),
        "adapter": (ADAPTER_PATH, f"{ADAPTER_DIR}/adapter.schema.json"),
        "workloads": (WORKLOAD_PATH, f"{WORKLOAD_DIR}/workload.schema.json"),
        "protocol": (
            PROTOCOL_PATH,
            f"{PROTOCOL_DIR}/protocol-cases-v2-candidate.schema.json",
        ),
        "lanes": (LANE_PATH, f"{LANE_DIR}/runtime-lane-plan.schema.json"),
        "guarded": (GUARDED_PATH, f"{GUARDED_DIR}/result.schema.json"),
        "wave8_contract": (
            WAVE8_CONTRACT_PATH,
            f"{WAVE8_DIR}/contract.schema.json",
        ),
        "wave8": (WAVE8_PATH, f"{WAVE8_DIR}/execution-receipt.schema.json"),
        "wave8_successor": (
            WAVE8_SUCCESSOR_PATH,
            f"{WAVE8_DIR}/successor-capability-oracles.schema.json",
        ),
        "bundles": (BUNDLE_PATH, f"{BUNDLE_DIR}/contract.schema.json"),
        "historical_registry": (
            f"{HISTORICAL_DIR}/registry.json",
            f"{HISTORICAL_DIR}/registry.schema.json",
        ),
    }
    for name, (artifact_path, schema_path) in specs.items():
        value = strict_json(payloads[artifact_path], artifact_path)
        schema = strict_json(payloads[schema_path], schema_path)
        _validate_schema(value, schema, name)
        sources[name] = value
    return payloads, sources


SOURCE_ID_BY_PATH = {
    ADAPTER_PATH: "adapter",
    GUARDED_PATH: "guarded",
    LANE_PATH: "lanes",
    MAPPING_PATH: "mapping",
    PROTOCOL_PATH: "protocol",
    WAVE8_PATH: "wave8",
    WORKLOAD_PATH: "workloads",
}


def _locator(path: str, pointer: str, value: Any) -> dict[str, Any]:
    return {
        "json_pointer": pointer,
        "record_canonical_sha256": sha256(canonical_bytes(value)),
        "source_id": SOURCE_ID_BY_PATH[path],
    }


def _preserved_binding_semantics(row: dict[str, Any]) -> dict[str, Any]:
    """Return the meaning-bearing fields that must survive the rebase exactly."""
    return {
        "action_tier": row["action_projection"]["tier"],
        "admission_grade": row["admission_grade"],
        "authoritative_executable_binding": row["authoritative_executable_binding"],
        "candidate_id": row["candidate_id"],
        "complete_dependency_closure": row["complete_dependency_closure"],
        "cross_tier": row["cross_tier"],
        "execution_boundary": row["execution_boundary"],
        "lane_ids": row["lane_projection"]["lane_ids"],
        "lane_tier": row["lane_projection"]["tier"],
        "leaf_bundle_id": row["leaf_bundle_id"],
        "manifest_pointer": row["manifest_pointer"],
        "mapping_position": row["mapping_position"],
        "observer_tier": row["observer_projection"]["tier"],
        "oracle_id": row["oracle_id"],
        "oracle_index": row["oracle_index"],
        "registry_position": row["registry_position"],
        "semantic_surface_count": row["semantic_projection"][
            "implementation_surface_count"
        ],
        "semantic_surfaces_canonical_sha256": row["semantic_projection"][
            "implementation_surfaces_canonical_sha256"
        ],
        "warehouse_sample_bundle": row["warehouse_sample_bundle"],
    }


def _index_unique(items: list[dict[str, Any]], key: str, label: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for index, item in enumerate(items):
        item_key = item[key]
        if item_key in result:
            raise RegistryError(f"duplicate {label}: {item_key}")
        result[item_key] = index
    return result


def _bundle_closure(bundle_by_id: dict[str, dict[str, Any]], leaf: str) -> list[str]:
    included: set[str] = set()
    visiting: set[str] = set()

    def visit(bundle_id: str) -> None:
        if bundle_id in visiting:
            raise RegistryError(f"bundle dependency cycle at {bundle_id}")
        if bundle_id in included:
            return
        bundle = bundle_by_id.get(bundle_id)
        if bundle is None:
            raise RegistryError(f"unknown bundle {bundle_id}")
        visiting.add(bundle_id)
        for dependency in bundle["depends_on"]:
            visit(dependency)
        visiting.remove(bundle_id)
        included.add(bundle_id)

    visit(leaf)
    return [bundle_id for bundle_id in bundle_by_id if bundle_id in included]


def _normalize_locator(locator: str) -> tuple[str, str | None]:
    if not locator or locator.count("#") > 1:
        raise RegistryError(f"invalid implementation-surface locator: {locator!r}")
    base, separator, fragment = locator.partition("#")
    pure = PurePosixPath(base)
    if (
        pure.is_absolute()
        or not pure.parts
        or any(part in {"", ".", ".."} for part in pure.parts)
        or pure.as_posix() != base
        or (separator and not fragment)
    ):
        raise RegistryError(f"unsafe implementation-surface locator: {locator!r}")
    return base, fragment if separator else None


def compile_locator_locks(sources: dict[str, dict[str, Any]]) -> dict[str, Any]:
    mapping_rows = sources["mapping"]["mappings"]
    adapter_by_id = sources["adapter"]["candidate_adapters_by_capability_id"]
    lane_document = sources["lanes"]
    lane_rows_by_pointer = {
        row["manifest_json_pointer"]: row
        for row in lane_document["advertised_entry_bindings"]
    }
    lane_by_id = {lane["id"]: lane for lane in lane_document["lanes"]}
    locator_counts: Counter[str] = Counter()
    used_lane_ids: set[str] = set()
    for mapping_row in mapping_rows:
        if mapping_row["mapping_state"] != "mapped":
            continue
        candidate_id = mapping_row["capability_id"]
        semantic = adapter_by_id[candidate_id]
        locator_counts.update(semantic["implementation_surfaces"])
        used_lane_ids.update(
            lane_rows_by_pointer[mapping_row["manifest_pointer"]]["lane_ids"]
        )
    if (
        sum(locator_counts.values()) != 389
        or len(locator_counts) != 269
        or used_lane_ids
        != {
            "alerts",
            "base",
            "custom-data-warehouse",
            "external-optional",
            "lvs",
            "search",
            "standalone-services",
        }
    ):
        raise RegistryError("semantic locator or active lane denominator drifted")

    normalized: list[dict[str, Any]] = []
    semantic_base_paths: set[str] = set()
    for locator in sorted(locator_counts):
        base, fragment = _normalize_locator(locator)
        payload = _read_regular(_repo_path(base), base)
        semantic_base_paths.add(base)
        normalized.append(
            {
                "base_path": base,
                "fragment": fragment,
                "locator": locator,
                "occurrence_count": locator_counts[locator],
                "raw_sha256": sha256(payload),
            }
        )
    if len(semantic_base_paths) != 235:
        raise RegistryError("semantic base-file denominator drifted")
    semantic_files = [
        {
            "path": path,
            "raw_sha256": sha256(_read_regular(_repo_path(path), path)),
        }
        for path in sorted(semantic_base_paths)
    ]

    lane_path_counts: Counter[str] = Counter()
    for lane_id in sorted(used_lane_ids):
        lane = lane_by_id.get(lane_id)
        if lane is None:
            raise RegistryError(f"missing active lane definition: {lane_id}")
        lane_path_counts.update(lane["profile_paths"])
        lane_path_counts.update(lane["service_compose_paths"])
    if sum(lane_path_counts.values()) != 45 or len(lane_path_counts) != 26:
        raise RegistryError("active-lane file denominator drifted")
    lane_files = [
        {
            "occurrence_count": lane_path_counts[path],
            "path": path,
            "raw_sha256": sha256(_read_regular(_repo_path(path), path)),
        }
        for path in sorted(lane_path_counts)
    ]
    return {
        "locator_lock_id": "thor-vss-3.2.1-candidate-execution-projection-locators",
        "schema_version": 1,
        "mode": "read_only_direct_source_locks",
        "semantic_locators": normalized,
        "semantic_base_files": semantic_files,
        "active_lane_ids": sorted(used_lane_ids),
        "active_lane_files": lane_files,
        "summary": {
            "active_lane_file_references": 45,
            "active_lane_unique_files": 26,
            "semantic_base_files": 235,
            "semantic_locator_occurrences": 389,
            "semantic_unique_locators": 269,
        },
        "warehouse_sample_bundle": "excluded",
    }


def _load_locator_locks(
    sources: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], bytes]:
    artifact_payload = _read_regular(LOCATOR_ARTIFACT_PATH, "locator locks")
    schema_payload = _read_regular(LOCATOR_SCHEMA_PATH, "locator-lock schema")
    artifact = strict_json(artifact_payload, "locator locks")
    schema = strict_json(schema_payload, "locator-lock schema")
    _validate_schema(artifact, schema, "locator locks")
    expected = compile_locator_locks(sources)
    canonical = (
        json.dumps(expected, indent=2, sort_keys=True, ensure_ascii=True).encode(
            "utf-8"
        )
        + b"\n"
    )
    if artifact != expected or artifact_payload != canonical:
        raise RegistryError("checked locator locks are stale or non-canonical")
    return artifact, artifact_payload


def compile_registry() -> dict[str, Any]:
    _, sources = _load_sources()
    locator_locks, locator_payload = _load_locator_locks(sources)
    mapping = sources["mapping"]
    adapter = sources["adapter"]
    workloads = sources["workloads"]
    protocol = sources["protocol"]
    lanes = sources["lanes"]
    guarded = sources["guarded"]
    wave8_contract = sources["wave8_contract"]
    wave8 = sources["wave8"]
    wave8_successor = sources["wave8_successor"]
    bundles = sources["bundles"]
    historical_registry = sources["historical_registry"]

    mapping_rows = mapping["mappings"]
    adapter_by_id = adapter["candidate_adapters_by_capability_id"]
    workload_rows = workloads["workloads"]
    protocol_bindings = protocol["bindings"]
    protocol_cases = protocol["cases"]
    lane_rows = lanes["advertised_entry_bindings"]
    guarded_rows = guarded["results"]
    wave8_rows = wave8["entries"]
    bundle_by_id = {bundle["id"]: bundle for bundle in bundles["bundles"]}
    if len(bundle_by_id) != 16 or len(bundle_by_id) != len(bundles["bundles"]):
        raise RegistryError("expected exact 16-bundle acyclic contract")
    lane_by_id = {lane["id"]: lane for lane in lanes["lanes"]}

    workload_index = _index_unique(workload_rows, "candidate_id", "workload")
    protocol_binding_index = _index_unique(
        protocol_bindings, "capability_id", "protocol binding"
    )
    protocol_case_index = _index_unique(
        protocol_cases, "capability_id", "protocol case"
    )
    lane_index = _index_unique(lane_rows, "manifest_json_pointer", "lane pointer")
    guarded_index = _index_unique(
        guarded_rows, "proposed_capability_id", "guard result"
    )
    wave8_index = _index_unique(wave8_rows, "capability_id", "Wave8 result")

    static_gaps = [
        (position, row["oracle_index"], row["capability_id"])
        for position, row in enumerate(mapping_rows)
        if row["mapping_state"] == "static_nonactivating"
    ]
    if static_gaps != EXPECTED_STATIC_GAPS:
        raise RegistryError("static gap positions drifted")
    mapped = [
        (position, row)
        for position, row in enumerate(mapping_rows)
        if row["mapping_state"] == "mapped"
    ]
    if len(mapping_rows) != 211 or len(mapped) != 208:
        raise RegistryError(
            "expected exact 211 mapping rows with 208 mapped candidates"
        )
    mapped_ids = {row["capability_id"] for _, row in mapped}
    if set(adapter_by_id) != mapped_ids | {item[2] for item in EXPECTED_STATIC_GAPS}:
        raise RegistryError("candidate adapter denominator drifted")

    if guarded["can_mark_passed_current"] or guarded["runtime_evidence"]:
        raise RegistryError("guarded adapter receipt contains promotion/evidence")
    if wave8["official_capability_effect"] != "none_candidate_only":
        raise RegistryError("Wave8 receipt claims official capability effect")
    if wave8["runtime_evidence"]:
        raise RegistryError("Wave8 receipt contains runtime evidence")
    wave8_ids = {row["capability_id"] for row in wave8_rows}
    if len(wave8_ids) != 2 or not wave8_ids <= set(guarded_index):
        raise RegistryError("Wave8/guarded observer overlap drifted")
    if (
        wave8_contract["contract_id"]
        != "successor-500-executable-subsets-wave1-2026-08-01"
        or wave8_contract["policy"]["official_capability_effect"]
        != "none_candidate_only"
        or wave8_contract["policy"]["runtime_evidence"]
        or wave8_successor["counts"]["runtime_promotions"] != 0
        or wave8_successor["counts"]["mutated_oracle_rows"] != 0
        or wave8_successor["global_invariants"]["runtime_state_changed"]
        or wave8_successor["global_invariants"]["runtime_evidence_added"]
        or {row["capability_id"] for row in wave8_successor["annotations"]} != wave8_ids
        or {row["receipt_id"] for row in wave8_successor["annotations"]}
        != {wave8["receipt_id"]}
    ):
        raise RegistryError("Wave1 contract/receipt/successor chain drifted")
    if (
        adapter["policy"]
        != {
            "can_mark_passed_current": False,
            "can_modify_live_ledgers_or_oracles": False,
            "candidate_only": True,
            "executor_materialization": "absent",
            "runtime_evidence": [],
            "warehouse_sample_bundle": "excluded",
        }
        or workloads["policy"]["can_promote_runtime_state"]
        or workloads["policy"]["runtime_evidence"]
        or workloads["policy"]["warehouse_sample_bundle"] != "excluded"
        or protocol["policy"]["can_promote_runtime_state"]
        or protocol["policy"]["runtime_evidence"]
        or protocol["policy"]["warehouse_sample_bundle"] != "excluded"
        or lanes["policy"]["runtime_evidence_created"]
        or lanes["policy"]["required_cloud_inference"]
        or lanes["policy"]["warehouse_sample_bundle"] != "excluded"
    ):
        raise RegistryError("projection source inertness policy drifted")

    registry_rows: list[dict[str, Any]] = []
    for registry_position, (mapping_position, mapping_row) in enumerate(mapped):
        candidate_id = mapping_row["capability_id"]
        if mapping_row["oracle_index"] != 289 + mapping_position:
            raise RegistryError(f"oracle index/order drift: {candidate_id}")
        expected_closure = _bundle_closure(bundle_by_id, mapping_row["leaf_bundle_id"])
        if mapping_row["dependency_closure"] != expected_closure:
            raise RegistryError(f"approval dependency closure drift: {candidate_id}")
        semantic = adapter_by_id.get(candidate_id)
        if semantic is None:
            raise RegistryError(f"missing semantic adapter: {candidate_id}")
        if (
            semantic["capability_id"] != candidate_id
            or semantic["oracle_id"] != mapping_row["oracle_id"]
            or semantic["manifest_pointer"] != mapping_row["manifest_pointer"]
            or semantic["execution_boundary"] != mapping_row["execution_boundary"]
        ):
            raise RegistryError(f"semantic adapter identity drift: {candidate_id}")
        if (
            mapping_row["required_cloud_inference"]
            or mapping_row["warehouse_sample_bundle"]
            or semantic["can_promote_runtime_state"]
            or semantic["evidence"]
            or semantic["execution_bounds"]["executor"] is not None
            or semantic["cleanup"]["executor"] is not None
            or semantic["ledger_binding"]["contract"]["warehouse_sample_bundle"]
            != "excluded"
        ):
            raise RegistryError(f"candidate projection inertness drift: {candidate_id}")
        implementation_surfaces = semantic["implementation_surfaces"]
        if (
            len(implementation_surfaces) != mapping_row["implementation_surface_count"]
            or sha256(canonical_bytes(implementation_surfaces))
            != mapping_row["implementation_surfaces_canonical_sha256"]
        ):
            raise RegistryError(
                f"implementation-surface identity drift: {candidate_id}"
            )

        binding_kind = mapping_row["binding_kind"]
        action_locators: list[dict[str, Any]] = []
        if binding_kind == "workload":
            action_tier = "workload"
            index = workload_index.get(candidate_id)
            if index is None:
                raise RegistryError(f"missing workload projection: {candidate_id}")
            workload = workload_rows[index]
            if workload["manifest_pointer"] != mapping_row["manifest_pointer"]:
                raise RegistryError(f"workload pointer drift: {candidate_id}")
            action_binding_sha256 = sha256(canonical_bytes(workload))
            if (
                action_binding_sha256
                != mapping_row["workload_binding_canonical_sha256"]
                or mapping_row["protocol_binding_canonical_sha256"] is not None
            ):
                raise RegistryError(f"workload binding hash drift: {candidate_id}")
            action_locators.append(
                _locator(WORKLOAD_PATH, f"/workloads/{index}", workload)
            )
        elif binding_kind == "protocol":
            action_tier = "protocol"
            binding_index = protocol_binding_index.get(candidate_id)
            case_index = protocol_case_index.get(candidate_id)
            if binding_index is None or case_index is None:
                raise RegistryError(f"missing protocol projection: {candidate_id}")
            binding = protocol_bindings[binding_index]
            case = protocol_cases[case_index]
            if (
                binding["case_id"] != case["case_id"]
                or case["candidate_contract"]["manifest_pointer"]
                != mapping_row["manifest_pointer"]
                or binding["activation_supported"]
                or case["activation"]["supported"]
                or case["activation"]["executor_binding"] is not None
            ):
                raise RegistryError(f"protocol planning boundary drift: {candidate_id}")
            action_binding_sha256 = sha256(canonical_bytes(binding))
            if (
                action_binding_sha256
                != mapping_row["protocol_binding_canonical_sha256"]
                or mapping_row["workload_binding_canonical_sha256"] is not None
            ):
                raise RegistryError(f"protocol binding hash drift: {candidate_id}")
            action_locators.extend(
                [
                    _locator(
                        PROTOCOL_PATH,
                        f"/bindings/{binding_index}",
                        binding,
                    ),
                    _locator(PROTOCOL_PATH, f"/cases/{case_index}", case),
                ]
            )
        elif binding_kind == "none":
            action_tier = "oracle_only"
            action_binding_sha256 = None
            if (
                mapping_row["workload_binding_canonical_sha256"] is not None
                or mapping_row["protocol_binding_canonical_sha256"] is not None
            ):
                raise RegistryError(f"oracle-only binding hash drift: {candidate_id}")
        else:
            raise RegistryError(f"unknown binding kind: {candidate_id}")
        if (candidate_id in workload_index) != (action_tier == "workload"):
            raise RegistryError(f"workload cross-tier mismatch: {candidate_id}")
        if (candidate_id in protocol_binding_index) != (action_tier == "protocol"):
            raise RegistryError(f"protocol cross-tier mismatch: {candidate_id}")

        observer_locators: list[dict[str, Any]] = []
        if candidate_id in wave8_index:
            observer_tier = "production_subset"
            index = wave8_index[candidate_id]
            observation = wave8_rows[index]
            if (
                observation["candidate_state"]
                != "candidate_executable_subset_non_advancing"
            ):
                raise RegistryError(f"Wave8 candidate state drift: {candidate_id}")
            observer_locators.append(
                _locator(WAVE8_PATH, f"/entries/{index}", observation)
            )
            guard_index = guarded_index[candidate_id]
            guard_observation = guarded_rows[guard_index]
            if (
                guard_observation["can_mark_passed_current"]
                or guard_observation["runtime_evidence"]
                or guard_observation["historical_execute_or_main_called"]
            ):
                raise RegistryError(
                    f"overlapping guard observation advanced state: {candidate_id}"
                )
            observer_locators.append(
                _locator(
                    GUARDED_PATH,
                    f"/results/{guard_index}",
                    guard_observation,
                )
            )
        elif candidate_id in guarded_index:
            observer_tier = "guarded_adapter"
            index = guarded_index[candidate_id]
            observation = guarded_rows[index]
            if (
                observation["can_mark_passed_current"]
                or observation["runtime_evidence"]
                or observation["historical_execute_or_main_called"]
            ):
                raise RegistryError(
                    f"guard observation advanced runtime state: {candidate_id}"
                )
            observer_locators.append(
                _locator(GUARDED_PATH, f"/results/{index}", observation)
            )
        else:
            observer_tier = "absent"

        lane_row_index = lane_index.get(mapping_row["manifest_pointer"])
        if lane_row_index is None:
            raise RegistryError(f"missing lane projection: {candidate_id}")
        lane_row = lane_rows[lane_row_index]
        if lane_row["feature_id"] != mapping_row["feature_id"]:
            raise RegistryError(f"lane feature drift: {candidate_id}")
        if mapping_row["execution_boundary"] == "external":
            lane_tier = "exact_external"
            if (
                lane_row["lane_ids"] != ["external-optional"]
                or lane_row["lane_binding_scope"]
                != "entry_specific_gap_acceptance_boundary"
            ):
                raise RegistryError(f"external lane drift: {candidate_id}")
        else:
            lane_tier = (
                "family_single" if len(lane_row["lane_ids"]) == 1 else "family_multi"
            )
            if (
                not lane_row["lane_ids"]
                or lane_row["lane_binding_scope"]
                != "feature_family_reviewed_not_entry_specific"
            ):
                raise RegistryError(f"empty family lane projection: {candidate_id}")
        deployment_source_paths = sorted(
            {
                path
                for lane_id in lane_row["lane_ids"]
                for path in (
                    lane_by_id[lane_id]["profile_paths"]
                    + lane_by_id[lane_id]["service_compose_paths"]
                )
            }
        )

        has_action = action_tier != "oracle_only"
        has_observer = observer_tier != "absent"
        cross_tier = (
            "both"
            if has_action and has_observer
            else "enriched"
            if has_action
            else "observer"
            if has_observer
            else "oracle"
        )
        authoritative = dict(EMPTY_AUTHORITATIVE_BINDING)
        registry_rows.append(
            {
                "action_projection": {
                    "binding_canonical_sha256": action_binding_sha256,
                    "source_locators": action_locators,
                    "tier": action_tier,
                },
                "admission_grade": False,
                "authoritative_executable_binding": authoritative,
                "candidate_id": candidate_id,
                "candidate_record_canonical_sha256": mapping_row[
                    "candidate_record_canonical_sha256"
                ],
                "complete_dependency_closure": mapping_row["dependency_closure"],
                "cross_tier": cross_tier,
                "execution_boundary": mapping_row["execution_boundary"],
                "lane_projection": {
                    "deployment_source_path_count": len(deployment_source_paths),
                    "deployment_source_paths_canonical_sha256": sha256(
                        canonical_bytes(deployment_source_paths)
                    ),
                    "lane_ids": lane_row["lane_ids"],
                    "source_locator": _locator(
                        LANE_PATH,
                        f"/advertised_entry_bindings/{lane_row_index}",
                        lane_row,
                    ),
                    "tier": lane_tier,
                },
                "leaf_bundle_id": mapping_row["leaf_bundle_id"],
                "manifest_pointer": mapping_row["manifest_pointer"],
                "mapping_locator": _locator(
                    MAPPING_PATH,
                    f"/mappings/{mapping_position}",
                    mapping_row,
                ),
                "mapping_position": mapping_position,
                "observer_projection": {
                    "source_locators": observer_locators,
                    "tier": observer_tier,
                },
                "oracle_id": mapping_row["oracle_id"],
                "oracle_index": mapping_row["oracle_index"],
                "registry_position": registry_position,
                "semantic_projection": {
                    "implementation_surface_count": len(implementation_surfaces),
                    "implementation_surfaces_canonical_sha256": sha256(
                        canonical_bytes(implementation_surfaces)
                    ),
                    "source_locator": _locator(
                        ADAPTER_PATH,
                        "/candidate_adapters_by_capability_id/" + candidate_id,
                        semantic,
                    ),
                    "tier": "candidate_oracle_adapter",
                },
                "warehouse_sample_bundle": "excluded",
            }
        )

    action_counts = dict(
        sorted(
            Counter(row["action_projection"]["tier"] for row in registry_rows).items()
        )
    )
    observer_counts = dict(
        sorted(
            Counter(row["observer_projection"]["tier"] for row in registry_rows).items()
        )
    )
    lane_counts = dict(
        sorted(Counter(row["lane_projection"]["tier"] for row in registry_rows).items())
    )
    cross_tier_counts = dict(
        sorted(Counter(row["cross_tier"] for row in registry_rows).items())
    )
    if action_counts != EXPECTED_ACTION_COUNTS:
        raise RegistryError(f"action projection counts drifted: {action_counts}")
    if observer_counts != EXPECTED_OBSERVER_COUNTS:
        raise RegistryError(f"observer projection counts drifted: {observer_counts}")
    if lane_counts != EXPECTED_LANE_COUNTS:
        raise RegistryError(f"lane projection counts drifted: {lane_counts}")
    if cross_tier_counts != EXPECTED_CROSS_TIER_COUNTS:
        raise RegistryError(f"cross-tier counts drifted: {cross_tier_counts}")
    external_ids = [
        row["candidate_id"]
        for row in registry_rows
        if row["execution_boundary"] == "external"
    ]
    if external_ids != EXPECTED_EXTERNAL_IDS:
        raise RegistryError(f"external candidate order drifted: {external_ids}")
    if any(
        row["admission_grade"]
        or row["authoritative_executable_binding"] != EMPTY_AUTHORITATIVE_BINDING
        for row in registry_rows
    ):
        raise RegistryError("authoritative executable binding was invented")

    historical_rows = historical_registry["bindings"]
    old_semantics = [_preserved_binding_semantics(row) for row in historical_rows]
    new_semantics = [_preserved_binding_semantics(row) for row in registry_rows]
    if old_semantics != new_semantics:
        raise RegistryError("historical unresolved/authoritative semantics drifted")
    changed_protocol_ids = [
        new["candidate_id"]
        for old, new in zip(historical_rows, registry_rows, strict=True)
        if old["action_projection"]["binding_canonical_sha256"]
        != new["action_projection"]["binding_canonical_sha256"]
    ]
    if changed_protocol_ids != EXPECTED_PROTOCOL_REBASE_IDS:
        raise RegistryError(
            f"protocol rebase candidate set drifted: {changed_protocol_ids}"
        )
    preserved_semantics_sha256 = sha256(canonical_bytes(old_semantics))

    return {
        "registry_id": (
            "thor-vss-3.2.1-candidate-execution-binding-registry-rebase-successor"
        ),
        "schema_version": 1,
        "mode": "inert_read_only_projection_registry_no_execution",
        "target": mapping["target"],
        "source_locks": [
            {"path": path, "raw_sha256": expected}
            for path, expected in EXPECTED_SOURCE_HASHES.items()
        ],
        "source_identities": {
            "candidate_adapter_id": adapter["adapter_id"],
            "guarded_execution_payload_sha256": guarded["execution_payload_sha256"],
            "mapping_id": mapping["mapping_id"],
            "approval_bundle_contract_id": bundles["contract_id"],
            "locator_locks_raw_sha256": sha256(locator_payload),
            "protocol_candidate_payload_sha256": protocol["candidate_payload_sha256"],
            "runtime_lane_plan_id": lanes["plan_id"],
            "wave8_receipt_id": wave8["receipt_id"],
            "wave8_contract_id": wave8_contract["contract_id"],
            "wave8_successor_artifact_id": wave8_successor["artifact_id"],
            "workload_payload_sha256": workloads["payload_sha256"],
        },
        "rebase_provenance": {
            "historical_package_locks": [
                {"path": path, "raw_sha256": expected}
                for path, expected in EXPECTED_HISTORICAL_HASHES.items()
            ],
            "historical_registry_id": historical_registry["registry_id"],
            "historical_binding_rows_canonical_sha256": historical_registry[
                "binding_rows_canonical_sha256"
            ],
            "preserved_binding_semantics_canonical_sha256": (
                preserved_semantics_sha256
            ),
            "protocol_rebase_candidate_ids": EXPECTED_PROTOCOL_REBASE_IDS,
            "mapping_v2_raw_sha256": EXPECTED_SOURCE_HASHES[MAPPING_PATH],
            "mapping_v2_schema_raw_sha256": EXPECTED_SOURCE_HASHES[
                f"{MAPPING_DIR}/mapping.schema.json"
            ],
            "runtime_bundles_raw_sha256": EXPECTED_SOURCE_HASHES[BUNDLE_PATH],
            "runtime_bundles_schema_raw_sha256": EXPECTED_SOURCE_HASHES[
                f"{BUNDLE_DIR}/contract.schema.json"
            ],
            "wave1_contract_raw_sha256": EXPECTED_SOURCE_HASHES[WAVE8_CONTRACT_PATH],
            "wave1_receipt_raw_sha256": EXPECTED_SOURCE_HASHES[WAVE8_PATH],
            "wave1_successor_raw_sha256": EXPECTED_SOURCE_HASHES[WAVE8_SUCCESSOR_PATH],
        },
        "policy": {
            "authoritative_bindings_present": 0,
            "compiler_can_execute": False,
            "historical_executors_invoked": False,
            "observer_projection_is_runtime_evidence": False,
            "planning_projection_is_authoritative_binding": False,
            "required_cloud_inference": False,
            "warehouse_sample_bundle": "excluded",
        },
        "static_gaps": [
            {
                "candidate_id": candidate_id,
                "mapping_position": position,
                "oracle_index": oracle_index,
                "state": "static_nonactivating_not_in_registry",
            }
            for position, oracle_index, candidate_id in EXPECTED_STATIC_GAPS
        ],
        "external_candidates": EXPECTED_EXTERNAL_IDS,
        "projection_locator_lock_identity": {
            "active_lane_unique_files": 26,
            "locator_lock_id": locator_locks["locator_lock_id"],
            "raw_sha256": sha256(locator_payload),
            "semantic_base_files": 235,
            "semantic_unique_locators": 269,
        },
        "bindings": registry_rows,
        "binding_rows_canonical_sha256": sha256(canonical_bytes(registry_rows)),
        "summary": {
            "action_projection_counts": action_counts,
            "admission_grade_bindings": 0,
            "executable_bindings": 0,
            "promotion_bindings": 0,
            "authoritative_binding_counts": {
                "action_contracts": 0,
                "cleanup_executors": 0,
                "cleanup_rollback_contracts": 0,
                "cleanup_targets": 0,
                "compose_paths": 0,
                "evidence_destinations": 0,
                "evidence_records": 0,
                "executors": 0,
                "postcondition_collectors": 0,
                "profile_ids": 0,
                "profile_paths": 0,
                "service_role_profile_bindings": 0,
                "service_roles": 0,
            },
            "binding_count": 208,
            "cross_tier_counts": cross_tier_counts,
            "external_candidate_count": 4,
            "lane_projection_counts": lane_counts,
            "observer_projection_counts": observer_counts,
            "static_gap_count": 3,
        },
    }


def check() -> dict[str, Any]:
    expected = compile_registry()
    artifact_payload = _read_regular(ARTIFACT_PATH, "registry artifact")
    schema_payload = _read_regular(SCHEMA_PATH, "registry schema")
    artifact = strict_json(artifact_payload, "registry artifact")
    schema = strict_json(schema_payload, "registry schema")
    _validate_schema(artifact, schema, "registry artifact")
    canonical = (
        json.dumps(expected, indent=2, sort_keys=True, ensure_ascii=True).encode(
            "utf-8"
        )
        + b"\n"
    )
    if artifact != expected or artifact_payload != canonical:
        raise RegistryError("checked registry is stale or non-canonical")
    return {
        "admission_grade_bindings": 0,
        "binding_count": 208,
        "binding_rows_canonical_sha256": artifact["binding_rows_canonical_sha256"],
        "registry_raw_sha256": sha256(artifact_payload),
        "status": "ok",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="validate checked registry"
    )
    args = parser.parse_args(argv)
    if not args.check:
        parser.error("the only supported mode is --check")
    try:
        print(json.dumps(check(), indent=2, sort_keys=True))
    except (OSError, RegistryError) as exc:
        print(
            f"candidate execution-binding registry validation failed: {exc}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
