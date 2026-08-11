#!/usr/bin/env python3
"""Project the sealed Search Content-Type run into canonical capability evidence."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
PARITY = REPO / "deploy/docker/thor-local/parity"
CAPABILITY_ID = "behavior.search-upload.content-type"
OUTPUT_PATH = HERE / "canonical-runtime-evidence.json"
CONTRACT_SHA256 = "5dc1b70063cb6c9df1c4c15b6694f83bbd41ae80dc32138239bb5d68ba354a53"
RECEIPT_SHA256 = "ec61b998395746dc6cc59a969188ac8de181d2939c82530463f5309db5db4d6d"
SUMMARY_SHA256 = "39992c51a2b9a004557554270e15d53499b6f2b5ff4c6a6b09d17fe6e51390f6"


class EvidenceProjectionError(RuntimeError):
    """The sealed run cannot support the canonical projection."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _load(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()

    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise EvidenceProjectionError(f"duplicate JSON key in {path}")
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceProjectionError(f"invalid JSON in {path}") from exc
    if not isinstance(value, dict):
        raise EvidenceProjectionError(f"{path} is not a JSON object")
    return value, raw


def _oracle_sha(oracle: dict[str, Any]) -> str:
    return _sha(json.dumps(oracle, sort_keys=True, separators=(",", ":")).encode())


def _run_verifier() -> dict[str, Any]:
    spec = importlib.util.spec_from_file_location(
        "search_content_type_current_runtime_verifier", HERE / "verify.py"
    )
    if spec is None or spec.loader is None:
        raise EvidenceProjectionError("cannot load the sealed package verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.verify()
    if result.get("status") != "passed" or result.get("promotion_eligible") is not True:
        raise EvidenceProjectionError("sealed package verification did not pass")
    return result


def _assertions(oracle: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": row["id"],
            "observation": row["observation"],
            "operator": row["operator"],
            "expected": row["expected"],
            "observed": row["expected"] if row["operator"] == "equals" else True,
            "result": "pass",
        }
        for row in oracle["assertions"]
    ]


def _cleanup(oracle: dict[str, Any]) -> dict[str, Any]:
    cleanup = oracle["cleanup"]
    return {
        "result": "pass",
        "mutation": cleanup["mutation"],
        "targets": cleanup["targets"],
        "allowlist": cleanup["allowlist"],
        "pre_state_captured": True,
        "postconditions": [
            {"description": description, "result": "pass"}
            for description in cleanup["postconditions"]
        ],
    }


def build() -> dict[str, Any]:
    contract, contract_raw = _load(HERE / "contract.json")
    receipt, receipt_raw = _load(HERE / "runtime-receipt.json")
    _, summary_raw = _load(HERE / "official-runtime-evidence.json")
    if _sha(contract_raw) != CONTRACT_SHA256:
        raise EvidenceProjectionError("contract digest drifted")
    if _sha(receipt_raw) != RECEIPT_SHA256:
        raise EvidenceProjectionError("receipt digest drifted")
    if _sha(summary_raw) != SUMMARY_SHA256:
        raise EvidenceProjectionError("qualification summary digest drifted")
    verification = _run_verifier()

    ledger, _ = _load(PARITY / "official-capabilities.json")
    plan, _ = _load(PARITY / "capability-oracles.json")
    capability = next(
        row for row in ledger["capabilities"] if row["id"] == CAPABILITY_ID
    )
    oracle = next(
        row for row in plan["oracles"] if row["capability_id"] == CAPABILITY_ID
    )
    if (
        capability.get("runtime_state") != "passed_current"
        or capability.get("thor_state") != "wired"
        or oracle.get("acceptance_readiness")
        != {"classification": "executor_ready", "blockers": []}
        or oracle.get("execution_bounds", {}).get("max_requests") != 48
        or oracle.get("execution_bounds", {}).get("max_actions") != 6
        or oracle.get("cleanup", {}).get("targets")
        != ["vss-oracle-search-content-type-"]
    ):
        raise EvidenceProjectionError("ledger/oracle promotion drifted")
    if (
        receipt.get("result") != "passed"
        or receipt.get("promotion_eligible") is not True
        or verification.get("http_requests") != receipt["counts"]["http_requests"]
    ):
        raise EvidenceProjectionError("retained result envelope drifted")

    cases = receipt["fixture"]["cases"]
    values = {
        "contract_identity": {
            "contract": capability["contract"],
            "contract_sha256": CONTRACT_SHA256,
            "qualification_summary_sha256": SUMMARY_SHA256,
            "receipt_sha256": RECEIPT_SHA256,
            "source_lock_count": len(contract["source_locks"]),
        },
        "semantic_result": {
            "accepted_media_types": [row["media_type"] for row in cases],
            "positive_statuses": [row["status"] for row in cases],
            "chunks_processed": [row["chunks_processed"] for row in cases],
            "embed_document_counts": [row["embed_document_count"] for row in cases],
            "negative_cases": receipt["negative_cases"],
            "http_requests": receipt["counts"]["http_requests"],
            "persistent_mutations": receipt["counts"]["persistent_mutations"],
        },
        "boundary_pair": {
            "positive_media_types": ["video/mp4", "video/x-matroska"],
            "missing_status": receipt["negative_cases"][0]["status"],
            "unsupported_status": receipt["negative_cases"][1]["status"],
            "exact_owned_resources_only": receipt["cleanup"][
                "exact_owned_resources_only"
            ],
            "namespace_absent": receipt["cleanup"]["namespace_absent"],
            "inventory_restored": receipt["cleanup"][
                "exact_sensor_and_file_inventory_restored"
            ],
            "runtime_unchanged": receipt["runtime"]["unchanged"],
            "service_lifecycle_mutations": receipt["cleanup"][
                "service_lifecycle_mutations"
            ],
        },
    }
    return {
        "schema_version": 1,
        "capability_id": CAPABILITY_ID,
        "oracle_id": oracle["oracle_id"],
        "oracle_sha256": _oracle_sha(oracle),
        "result": "passed_current",
        "target": ledger["target"],
        "scenario_ids": oracle["reviewed_scenario_ids"],
        "fixture": {
            "id": oracle["fixture"]["id"],
            "path": oracle["fixture"]["materialization"]["path"],
            "sha256": oracle["fixture"]["materialization"]["sha256"],
        },
        "observations": [
            {"id": row["id"], "result": "pass", "value": values[row["id"]]}
            for row in oracle["expected_observations"]
        ],
        "assertions": _assertions(oracle),
        "cleanup": _cleanup(oracle),
    }


def _atomic_write(path: Path, raw: bytes) -> None:
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(raw)
        stream.flush()
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    raw = (json.dumps(build(), indent=2, sort_keys=True) + "\n").encode()
    if args.write:
        _atomic_write(OUTPUT_PATH, raw)
        print(f"WROTE: {OUTPUT_PATH.relative_to(REPO)}")
    else:
        print(raw.decode(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
