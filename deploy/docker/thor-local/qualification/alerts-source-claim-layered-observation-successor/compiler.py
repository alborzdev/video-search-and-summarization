#!/usr/bin/env python3
"""Validate the layered Alerts then source-claim ledger transition read-only."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4].resolve(strict=True)
ARTIFACT_PATH = HERE / "layered-observation.json"
SCHEMA_PATH = HERE / "layered-observation.schema.json"
MAX_BYTES = 96_000_000

OFFICIAL_PATH = "deploy/docker/thor-local/parity/official-capabilities.json"
ORACLES_PATH = "deploy/docker/thor-local/parity/capability-oracles.json"
MANIFEST_PATH = "deploy/docker/thor-local/parity/manifest.json"
ACCEPTANCE_PATH = "deploy/docker/thor-local/qualification/acceptance_inventory.json"
SOURCE_DIR = "deploy/docker/thor-local/qualification/source-claim-hash-repair-successor"
ALERTS_DIR = "deploy/docker/thor-local/qualification/alerts-current-contract-successor"
SOURCE_COMPILER_PATH = f"{SOURCE_DIR}/integrate_live.py"
SOURCE_RECEIPT_PATH = f"{SOURCE_DIR}/live-integration-receipt.json"
SOURCE_RECEIPT_SCHEMA_PATH = f"{SOURCE_DIR}/live-integration-receipt.schema.json"
ALERTS_COMPILER_PATH = f"{ALERTS_DIR}/integrate_live.py"
ALERTS_RECEIPT_PATH = f"{ALERTS_DIR}/live-integration-receipt.json"

CURRENT_OFFICIAL_SHA256 = (
    "61c2a4c0bc9d23940d954311f93824dc55c18cfc58caca002162cc1ef6808098"
)
ALERTS_POST_OFFICIAL_SHA256 = (
    "fb1638a82e8bf04b0b07482fc016184c3abc6bc692ca8a11fa94681837953055"
)
ALERTS_PREDECESSOR_OFFICIAL_SHA256 = (
    "d1a047345a309d675f692756fc2d9b56159c53840b6328264bb3cefb07f0cce6"
)
ALERTS_POST_ORACLES_SHA256 = (
    "24214553cbd669eb80efa7b4a602ac52328e00bd43241c839b43b10d05e22e8e"
)
ALERTS_PREDECESSOR_ORACLES_SHA256 = (
    "4625c8efb38df757ed90483826df9064717cf131f52d7500ef8eec39510e0804"
)

EXPECTED_SOURCE_HASHES = {
    OFFICIAL_PATH: CURRENT_OFFICIAL_SHA256,
    ORACLES_PATH: ALERTS_POST_ORACLES_SHA256,
    MANIFEST_PATH: "1f56d63437bd7742cf7488b9bd85b25fc886cdaf39a3c2b46aabecbc6b7201ce",
    ACCEPTANCE_PATH: "79001985f9cc9d0dbb64adea2a014aaedacd0b0411d8becb5b311c8697a563a5",
    SOURCE_COMPILER_PATH: "e497cfa580166bf2a85094353960a32786803c60481aecd02db562f349c23f45",
    SOURCE_RECEIPT_PATH: "edc3c30ef79a720551fb16682555dc66d01533efd11a3ee40a6386883cde680d",
    SOURCE_RECEIPT_SCHEMA_PATH: "eeb6da94937432bbb88b5d526c7365807d64b3a959d7fdaa4f114e5539d0b387",
    f"{SOURCE_DIR}/tests/test_integration.py": (
        "aa540dfa20abe85cbf9ffdec8d1f714976d9898d2b2e7c43c1ee07950b083d27"
    ),
    ALERTS_COMPILER_PATH: "211e995d69bbed7d19af30a9cdde05886c68b69997256867fa0745dfec36296e",
    ALERTS_RECEIPT_PATH: "ad4e461066e658b1cbc016a4ab5bc209a7c4e1c3246306367bb6c4aeca32c8e9",
    f"{ALERTS_DIR}/tests/test_integration.py": (
        "028a70dbb50aca5815a8ceb08c1f599d4a967a6dc25c8b048deb747a5347b6a0"
    ),
}


class ObservationError(RuntimeError):
    """A source, layered transition, schema, or inertness invariant failed."""


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def strict_json(payload: bytes, label: str) -> dict[str, Any]:
    if len(payload) > MAX_BYTES:
        raise ObservationError(f"{label}: exceeds size bound")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ObservationError(f"{label}: duplicate key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda token: (_ for _ in ()).throw(
                ObservationError(f"{label}: non-finite value {token}")
            ),
        )
    except ObservationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ObservationError(f"{label}: invalid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ObservationError(f"{label}: JSON root must be an object")
    return value


def _repo_path(relative: str) -> Path:
    pure = PurePosixPath(relative)
    if (
        pure.is_absolute()
        or not pure.parts
        or any(part in {"", ".", ".."} for part in pure.parts)
        or pure.as_posix() != relative
    ):
        raise ObservationError(f"unsafe repository path: {relative}")
    path = REPO_ROOT
    for part in pure.parts:
        path /= part
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise ObservationError(f"source path contains symlink: {relative}")
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ObservationError(f"source is not a regular file: {relative}")
    return path


def _read_regular(path: Path, label: str) -> bytes:
    relative = path.relative_to(REPO_ROOT)
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_BYTES:
            raise ObservationError(f"{label}: invalid file type or size")
        payload = os.read(descriptor, before.st_size + 1)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    current = (REPO_ROOT / relative).lstat()
    identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    if identity != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise ObservationError(f"{label}: changed while reading")
    if identity != (
        current.st_dev,
        current.st_ino,
        current.st_size,
        current.st_mtime_ns,
    ):
        raise ObservationError(f"{label}: path identity changed while reading")
    if len(payload) != before.st_size:
        raise ObservationError(f"{label}: short or long read")
    return payload


def _validate_schema(value: Any, schema: dict[str, Any], label: str) -> None:
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ObservationError(f"{label}: invalid JSON Schema") from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        first = errors[0]
        where = "/" + "/".join(str(part) for part in first.absolute_path)
        raise ObservationError(f"{label}: schema violation at {where}: {first.message}")


def _load_module(relative: str, name: str) -> Any:
    path = _repo_path(relative)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ObservationError(f"cannot load locked module: {relative}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_sources() -> tuple[dict[str, bytes], list[dict[str, str]]]:
    payloads: dict[str, bytes] = {}
    locks: list[dict[str, str]] = []
    for relative, expected in EXPECTED_SOURCE_HASHES.items():
        payload = _read_regular(_repo_path(relative), relative)
        actual = sha256(payload)
        if actual != expected:
            raise ObservationError(
                f"source drift for {relative}: expected {expected}, got {actual}"
            )
        payloads[relative] = payload
        locks.append({"path": relative, "raw_sha256": actual})
    source_receipt = strict_json(payloads[SOURCE_RECEIPT_PATH], "source receipt")
    source_schema = strict_json(
        payloads[SOURCE_RECEIPT_SCHEMA_PATH], "source receipt schema"
    )
    _validate_schema(source_receipt, source_schema, "source receipt")
    return payloads, locks


def _compile_layers() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    payloads, locks = _load_sources()
    source = _load_module(SOURCE_COMPILER_PATH, "locked_source_claim_successor")
    alerts = _load_module(ALERTS_COMPILER_PATH, "locked_alerts_successor")
    current_official = payloads[OFFICIAL_PATH]
    current_oracles = payloads[ORACLES_PATH]

    alerts_post = source._normalize_predecessor(current_official)
    if sha256(alerts_post) != ALERTS_POST_OFFICIAL_SHA256:
        raise ObservationError("source-claim rollback did not reach Alerts post-state")
    source_before = strict_json(alerts_post, "Alerts post official ledger")
    source_after = strict_json(current_official, "current official ledger")
    source_pointers = sorted(source._leaf_diffs(source_before, source_after))
    expected_source_pointers = sorted(
        row["semantic_pointer"]
        for row in strict_json(payloads[SOURCE_RECEIPT_PATH], "source receipt")[
            "changes"
        ]
    )
    if source_pointers != expected_source_pointers or len(source_pointers) != 6:
        raise ObservationError("source-claim six-leaf transition drifted")

    official_descriptor = alerts.TARGETS[OFFICIAL_PATH]
    alerts_predecessor = alerts._normalize_predecessor(
        alerts_post, OFFICIAL_PATH, official_descriptor
    )
    if sha256(alerts_predecessor) != ALERTS_PREDECESSOR_OFFICIAL_SHA256:
        raise ObservationError("Alerts official rollback digest drifted")
    alerts_official_pointers = sorted(
        alerts._leaf_diffs(
            strict_json(alerts_predecessor, "Alerts official predecessor"),
            source_before,
        )
    )
    if alerts_official_pointers != sorted(official_descriptor["semantic_pointers"]):
        raise ObservationError("Alerts official two-leaf transition drifted")

    oracle_descriptor = alerts.TARGETS[ORACLES_PATH]
    oracle_predecessor = alerts._normalize_predecessor(
        current_oracles, ORACLES_PATH, oracle_descriptor
    )
    if sha256(oracle_predecessor) != ALERTS_PREDECESSOR_ORACLES_SHA256:
        raise ObservationError("Alerts oracle rollback digest drifted")
    alerts_oracle_pointers = sorted(
        alerts._leaf_diffs(
            strict_json(oracle_predecessor, "Alerts oracle predecessor"),
            strict_json(current_oracles, "Alerts oracle post-state"),
        )
    )
    if alerts_oracle_pointers != sorted(oracle_descriptor["semantic_pointers"]):
        raise ObservationError("Alerts oracle ten-leaf transition drifted")

    alerts_receipt = strict_json(payloads[ALERTS_RECEIPT_PATH], "Alerts receipt")
    source_receipt = strict_json(payloads[SOURCE_RECEIPT_PATH], "source receipt")
    if (
        alerts_receipt["outputs"][OFFICIAL_PATH] != ALERTS_POST_OFFICIAL_SHA256
        or alerts_receipt["outputs"][ORACLES_PATH] != ALERTS_POST_ORACLES_SHA256
        or source_receipt["target"]["predecessor_raw_sha256"]
        != ALERTS_POST_OFFICIAL_SHA256
        or source_receipt["target"]["successor_raw_sha256"] != CURRENT_OFFICIAL_SHA256
    ):
        raise ObservationError("receipt chain identities do not compose")
    if (
        alerts_receipt["boundaries"]["runtime_evidence_added"]
        or alerts_receipt["boundaries"]["passed_current_allowed"]
        or source_receipt["boundaries"]["runtime_evidence_added"]
        or source_receipt["boundaries"]["passed_current_allowed"]
    ):
        raise ObservationError("layered receipt chain claims evidence or promotion")

    layers = [
        {
            "layer_id": "source-claim-hash-repair",
            "input_raw_sha256": CURRENT_OFFICIAL_SHA256,
            "rollback_raw_sha256": ALERTS_POST_OFFICIAL_SHA256,
            "semantic_leaf_count": 6,
            "semantic_pointers": source_pointers,
            "receipt_raw_sha256": EXPECTED_SOURCE_HASHES[SOURCE_RECEIPT_PATH],
        },
        {
            "layer_id": "alerts-current-contract-official",
            "input_raw_sha256": ALERTS_POST_OFFICIAL_SHA256,
            "rollback_raw_sha256": ALERTS_PREDECESSOR_OFFICIAL_SHA256,
            "semantic_leaf_count": 2,
            "semantic_pointers": alerts_official_pointers,
            "receipt_raw_sha256": EXPECTED_SOURCE_HASHES[ALERTS_RECEIPT_PATH],
        },
        {
            "layer_id": "alerts-current-contract-oracles",
            "input_raw_sha256": ALERTS_POST_ORACLES_SHA256,
            "rollback_raw_sha256": ALERTS_PREDECESSOR_ORACLES_SHA256,
            "semantic_leaf_count": 10,
            "semantic_pointers": alerts_oracle_pointers,
            "receipt_raw_sha256": EXPECTED_SOURCE_HASHES[ALERTS_RECEIPT_PATH],
        },
    ]
    return layers, locks


def compile_observation() -> dict[str, Any]:
    layers, locks = _compile_layers()
    return {
        "observation_id": "thor-vss-3.2.1-alerts-source-claim-layered-observation",
        "schema_version": 1,
        "mode": "read_only_layered_transition_observation_no_writes",
        "source_locks": locks,
        "layers": layers,
        "layer_rows_canonical_sha256": sha256(canonical_bytes(layers)),
        "policy": {
            "writes_performed": False,
            "runtime_evidence_added": False,
            "passed_current_promotions": 0,
            "network_allowed": False,
            "docker_allowed": False,
            "services_allowed": False,
            "warehouse_sample_bundle": "excluded",
        },
        "summary": {
            "layer_count": 3,
            "semantic_leaf_count": 18,
            "current_official_raw_sha256": CURRENT_OFFICIAL_SHA256,
            "alerts_post_official_raw_sha256": ALERTS_POST_OFFICIAL_SHA256,
            "alerts_predecessor_official_raw_sha256": (
                ALERTS_PREDECESSOR_OFFICIAL_SHA256
            ),
            "runtime_evidence_records": 0,
            "promotions": 0,
        },
    }


def validate() -> dict[str, Any]:
    expected = compile_observation()
    artifact_payload = _read_regular(ARTIFACT_PATH, "layered observation")
    schema_payload = _read_regular(SCHEMA_PATH, "layered observation schema")
    artifact = strict_json(artifact_payload, "layered observation")
    schema = strict_json(schema_payload, "layered observation schema")
    _validate_schema(artifact, schema, "layered observation")
    canonical = (
        json.dumps(expected, indent=2, sort_keys=True, ensure_ascii=True).encode()
        + b"\n"
    )
    if artifact != expected or artifact_payload != canonical:
        raise ObservationError("layered observation is stale or non-canonical")
    return {
        "status": "ok",
        "layer_count": 3,
        "semantic_leaf_count": 18,
        "observation_raw_sha256": sha256(artifact_payload),
        "writes_performed": False,
    }


def plan() -> dict[str, Any]:
    artifact = compile_observation()
    return {
        "lifecycle": "prospective_layered_observation",
        "layer_count": artifact["summary"]["layer_count"],
        "semantic_leaf_count": artifact["summary"]["semantic_leaf_count"],
        "writes_performed": False,
    }


def review() -> dict[str, Any]:
    artifact = compile_observation()
    return {
        "lifecycle": "layered_observation_reviewed",
        "layers": artifact["layers"],
        "writes_performed": False,
    }


def rollback_plan() -> dict[str, Any]:
    artifact = compile_observation()
    return {
        "lifecycle": "layered_rollback_observed_not_executed",
        "rollback_chain": [
            {
                "from": row["input_raw_sha256"],
                "to": row["rollback_raw_sha256"],
                "layer_id": row["layer_id"],
            }
            for row in artifact["layers"]
        ],
        "writes_performed": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("plan", "review", "validate", "rollback-plan")
    )
    args = parser.parse_args(argv)
    try:
        result = {
            "plan": plan,
            "review": review,
            "validate": validate,
            "rollback-plan": rollback_plan,
        }[args.command]()
        print(json.dumps(result, indent=2, sort_keys=True))
    except (KeyError, OSError, ObservationError) as exc:
        print(f"layered observation validation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
