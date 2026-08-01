#!/usr/bin/env python3
"""Execute the networkless synthetic-data static wiring contract."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from validator import (
    DEFAULT_CONTRACT,
    HERE,
    QualificationError,
    canonical_bytes,
    validate_contract,
    validate_schema,
)

sys.dont_write_bytecode = True

RESULT_SCHEMA = HERE / "result.schema.json"


def execute(contract_path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    """Run the read-only validator twice and return a schema-checked result."""
    first = validate_contract(contract_path)
    second = validate_contract(contract_path)
    if canonical_bytes(first) != canonical_bytes(second):
        raise QualificationError("independent static observations are not deterministic")
    result = {
        "schema_version": 1,
        "package_id": "thor-synthetic-data-entry-static-contract-v1",
        "mode": "candidate_only_canonical_source_wiring",
        "status": "pass",
        "scope": "static_wiring_only",
        "observations": first,
        "determinism": {
            "independent_runs": 2,
            "byte_identical": True,
        },
        "confinement": {
            "network_calls": 0,
            "docker_calls": 0,
            "subprocess_calls": 0,
            "downloads": 0,
            "service_lifecycle_calls": 0,
            "product_imports": 0,
            "filesystem_writes": 0,
            "warehouse_sample_bundle": "excluded",
        },
        "runtime_evidence_created": False,
        "runtime_state_promoted": False,
        "official_capability_effect": "none_static_contract_only",
        "result": "static_source_wiring_verified_runtime_open",
    }
    validate_schema(result, RESULT_SCHEMA, "result")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate and emit deterministic canonical JSON",
    )
    args = parser.parse_args(argv)
    try:
        result = execute(args.contract)
    except QualificationError as exc:
        print(f"qualification failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
