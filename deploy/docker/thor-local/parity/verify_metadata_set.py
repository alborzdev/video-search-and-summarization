#!/usr/bin/env python3
"""Authoritatively validate one resolved, atomic Thor metadata snapshot."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from typing import Any, Mapping, Protocol

import capability_oracles
from metadata_sets import MetadataSnapshot, resolve_metadata_set
import verify_official_capabilities


sys.dont_write_bytecode = True


class MetadataSetVerificationError(ValueError):
    """A resolved snapshot or validator result is internally inconsistent."""


class _V2Validator(Protocol):
    def validate(
        self,
        plan: dict[str, Any],
        ledger: dict[str, Any],
        acceptance: dict[str, Any] | None = None,
        schema: dict[str, Any] | None = None,
    ) -> dict[str, int]: ...


def _load_v2_validator() -> _V2Validator:
    try:
        module = importlib.import_module("capability_oracles_v2")
    except ImportError as exc:
        raise MetadataSetVerificationError(
            "v2 capability-oracle validator is unavailable"
        ) from exc
    if not callable(getattr(module, "validate", None)):
        raise MetadataSetVerificationError(
            "v2 capability-oracle validator has no validate API"
        )
    return module


def _objects(value: Any, field: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise MetadataSetVerificationError(f"{field} must be a list of objects")
    return value


def _validator_counts(value: Any, label: str) -> dict[str, int]:
    if not isinstance(value, dict) or any(
        not isinstance(key, str)
        or not key
        or not isinstance(count, int)
        or isinstance(count, bool)
        or count < 0
        for key, count in value.items()
    ):
        raise MetadataSetVerificationError(
            f"{label} returned malformed validation counts"
        )
    return dict(value)


def _expected_counts(value: Mapping[str, int]) -> dict[str, int]:
    counts = dict(value)
    if set(counts) != {"capabilities", "oracles", "feature_families"} or any(
        not isinstance(count, int) or isinstance(count, bool) or count < 1
        for count in counts.values()
    ):
        raise MetadataSetVerificationError("snapshot expected counts are malformed")
    return counts


def verify_metadata_set(set_id: str | None = None) -> dict[str, Any]:
    """Resolve and authoritatively validate one complete metadata snapshot."""
    snapshot: MetadataSnapshot = resolve_metadata_set(set_id)
    manifest = snapshot.document("manifest")
    ledger = snapshot.document("official_capabilities")
    oracle_plan = snapshot.document("capability_oracles")
    acceptance = snapshot.document("acceptance_inventory")
    oracle_schema = snapshot.schema("capability_oracles_schema")

    capabilities = _objects(ledger.get("capabilities"), "capabilities")
    oracles = _objects(oracle_plan.get("oracles"), "oracles")
    features = _objects(manifest.get("features"), "features")
    expected = _expected_counts(snapshot.expected_counts)
    observed = {
        "capabilities": len(capabilities),
        "oracles": len(oracles),
        "feature_families": len(features),
    }
    if observed != expected:
        raise MetadataSetVerificationError(
            f"resolved snapshot count drift: expected={expected}, observed={observed}"
        )

    official_counts = _validator_counts(
        verify_official_capabilities.validate(
            ledger=ledger,
            manifest=manifest,
            acceptance=acceptance,
            oracle_plan=oracle_plan,
            oracle_schema=oracle_schema,
            repo_root=verify_official_capabilities.REPO_ROOT,
        ),
        "official capability validator",
    )
    populated_families = len({item.get("feature_id") for item in capabilities})
    if (
        official_counts.get("capabilities") != observed["capabilities"]
        or official_counts.get("feature_families") != populated_families
    ):
        raise MetadataSetVerificationError(
            "official validator counts differ from resolved snapshot"
        )

    oracle_schema_version = oracle_plan.get("schema_version")
    if oracle_schema_version == 1:
        oracle_counts_raw = capability_oracles.validate(
            plan=oracle_plan,
            ledger=ledger,
            repo_root=capability_oracles.REPO_ROOT,
        )
        oracle_validator = "capability_oracles.v1"
    elif oracle_schema_version == 2:
        oracle_counts_raw = _load_v2_validator().validate(
            oracle_plan,
            ledger,
            acceptance,
            oracle_schema,
        )
        oracle_validator = "capability_oracles_v2"
    else:
        raise MetadataSetVerificationError(
            f"unsupported capability-oracle schema_version: {oracle_schema_version!r}"
        )
    oracle_counts = _validator_counts(oracle_counts_raw, "oracle validator")
    if (
        oracle_counts.get("capabilities") != observed["capabilities"]
        or oracle_counts.get("oracles") != observed["oracles"]
    ):
        raise MetadataSetVerificationError(
            "oracle validator counts differ from resolved snapshot"
        )

    return {
        "set_id": snapshot.set_id,
        "descriptor_raw_sha256": snapshot.descriptor_raw_sha256,
        "oracle_schema_version": oracle_schema_version,
        "oracle_validator": oracle_validator,
        "counts": observed,
        "official_validator_counts": official_counts,
        "oracle_validator_counts": oracle_counts,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set", dest="set_id", help="explicit registered set id")
    parser.add_argument("--json", action="store_true", help="print exact JSON counts")
    args = parser.parse_args(argv)
    try:
        report = verify_metadata_set(args.set_id)
    except (ImportError, KeyError, OSError, TypeError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    else:
        counts = report["counts"]
        print(
            "PASS: authoritative atomic metadata set "
            f"{report['set_id']}; capabilities={counts['capabilities']}, "
            f"oracles={counts['oracles']}, "
            f"families={counts['feature_families']}, "
            f"oracle_schema_version={report['oracle_schema_version']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
