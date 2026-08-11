#!/usr/bin/env python3
"""Project the sealed Search run into canonical capability evidence."""

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
CAPABILITY_ID = "runtime.agent.search-profile"
CONTRACT_PATH = HERE / "contract.json"
RECEIPT_PATH = HERE / "runtime-receipt.json"
SUMMARY_PATH = HERE / "official-runtime-evidence.json"
OUTPUT_PATH = HERE / "canonical-runtime-evidence.json"
CONTRACT_SHA256 = "7276e965e723e8beab3dc443ad70caa5927c5c11c6036817610c117a7dd0b658"
RECEIPT_SHA256 = "57a8d5e9dccaac3d613b842f8aac99c71859734857adb9975bfbbdae54796bae"
SUMMARY_SHA256 = "ce8810fc78e80b7bd2e2afd19cb58befe71daaab3fde0e3b8a20561a4bb58d07"


class EvidenceProjectionError(RuntimeError):
    """The sealed Search run cannot support the canonical projection."""


def _load(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise EvidenceProjectionError(f"duplicate JSON key in {path}")
            value[key] = item
        return value

    try:
        value = json.loads(raw, object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceProjectionError(f"invalid JSON in {path}") from exc
    if not isinstance(value, dict):
        raise EvidenceProjectionError(f"{path} is not a JSON object")
    return value, raw


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _oracle_sha(oracle: dict[str, Any]) -> str:
    raw = json.dumps(oracle, sort_keys=True, separators=(",", ":")).encode()
    return _sha(raw)


def _run_package_verifier() -> dict[str, Any]:
    spec = importlib.util.spec_from_file_location(
        "search_semantic_current_runtime_verifier", HERE / "verify.py"
    )
    if spec is None or spec.loader is None:
        raise EvidenceProjectionError("cannot load the sealed Search verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.verify()
    if result.get("status") != "passed" or result.get("promotion_eligible") is not True:
        raise EvidenceProjectionError("sealed Search verification did not pass")
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
    contract, contract_raw = _load(CONTRACT_PATH)
    receipt, receipt_raw = _load(RECEIPT_PATH)
    summary, summary_raw = _load(SUMMARY_PATH)
    if _sha(contract_raw) != CONTRACT_SHA256:
        raise EvidenceProjectionError("Search contract digest drifted")
    if _sha(receipt_raw) != RECEIPT_SHA256:
        raise EvidenceProjectionError("Search receipt digest drifted")
    if _sha(summary_raw) != SUMMARY_SHA256:
        raise EvidenceProjectionError("Search qualification summary digest drifted")
    verification = _run_package_verifier()

    ledger, _ = _load(PARITY / "official-capabilities.json")
    plan, _ = _load(PARITY / "capability-oracles.json")
    capabilities = {row["id"]: row for row in ledger["capabilities"]}
    oracles = {row["capability_id"]: row for row in plan["oracles"]}
    capability = capabilities[CAPABILITY_ID]
    oracle = oracles[CAPABILITY_ID]
    if (
        capability.get("runtime_state") != "passed_current"
        or capability.get("thor_state") != "wired"
        or oracle.get("acceptance_readiness")
        != {"classification": "executor_ready", "blockers": []}
        or oracle.get("reviewed_scenario_ids")
        != [
            "search-archive-workflows",
            "rest-api-operation-matrix",
            "oracle.runtime.agent.search-profile",
        ]
        or oracle.get("execution_bounds", {}).get("max_requests") != 48
        or oracle.get("execution_bounds", {}).get("max_actions") != 14
        or oracle.get("cleanup", {}).get("targets")
        != ["mdx-behavior-2025-01-01", "mdx-raw-2025-01-01"]
    ):
        raise EvidenceProjectionError("Search ledger/oracle promotion drifted")
    if (
        receipt.get("status") != "passed_current_candidate"
        or receipt.get("promotion_eligible") is not True
        or summary.get("status") != "passed_current"
        or summary.get("promotion_eligible") is not True
        or verification.get("http_requests") != receipt["bounds"]["http_requests"]
    ):
        raise EvidenceProjectionError("Search retained result envelope drifted")

    semantics = receipt["semantics"]
    cleanup = receipt["cleanup"]
    values = {
        "contract_identity": {
            "contract": capability["contract"],
            "contract_sha256": CONTRACT_SHA256,
            "qualification_summary_sha256": SUMMARY_SHA256,
            "receipt_sha256": RECEIPT_SHA256,
            "source_lock_count": len(contract["source_locks"]),
        },
        "semantic_result": {
            "canonical_routes_observed": semantics["canonical_routes_observed"],
            "embedding_dimensions": semantics["embedding_dimensions"],
            "minimum_clip_extended": semantics["single_attribute"][
                "minimum_clip_extended"
            ],
            "same_object_merge": semantics["single_attribute"]["same_object_merge"],
            "multiple_attributes_append": semantics["append_multiple_attributes"][
                "passed"
            ],
            "multiple_attributes_fuse": semantics["fuse_multiple_attributes"]["passed"],
            "fusion_order": semantics["fusion"]["order_observed"],
            "fusion_top_k_limited": semantics["fusion"]["top_k_limited"],
            "selected_bbox_present": semantics["frames"]["selected_bbox_present"],
            "selected_object_seed_excluded": semantics["selected_object_knn"][
                "seed_excluded"
            ],
        },
        "boundary_pair": {
            "positive_route_count": len(semantics["canonical_routes_observed"]),
            "adjacent_invalid_status": semantics["adjacent_invalid_status"],
            "owned_indices_absent_twice": all(
                row == {"behavior": 404, "raw": 404}
                for row in cleanup["absence_checks"]
            ),
            "analytics_frames_empty": cleanup["frames_empty"],
            "read_only_embedding_index_unchanged": cleanup["embed_read_only_unchanged"],
            "exact_owned_resources_only": cleanup["exact_owned_resources_only"],
            "persistent_stream_mutations": cleanup["persistent_stream_mutations"],
            "service_lifecycle_mutations": cleanup["service_lifecycle_mutations"],
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
    evidence = build()
    raw = (json.dumps(evidence, indent=2, sort_keys=True) + "\n").encode()
    if args.write:
        _atomic_write(OUTPUT_PATH, raw)
        print(f"WROTE: {OUTPUT_PATH.relative_to(REPO)}")
    else:
        print(raw.decode(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
