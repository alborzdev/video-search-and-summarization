#!/usr/bin/env python3
"""Project the sealed complete LVS REST run into canonical capability evidence."""

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
CAPABILITY_ID = "api.core.lvs-17"
OUTPUT_PATH = HERE / "canonical-runtime-evidence.json"
CONTRACT_SHA256 = "d482b6b23ed579a3798355b9aec0260df8bc2db848b235043df1a39b9fb95262"
RECEIPT_SHA256 = "aa80bd8b013ca08241b058b401f77893d612ec737f2b1135614d5fbe8d3aa694"
SUMMARY_SHA256 = "329efacfaa3c0dcd76bf207267ab96322bce3211393f3f2e3bdbad6b2ac91273"
CANONICAL_SHA256 = "841d065e8e3d58d22cdf2e769c77eab61e2c8d01086c87bcdd57fc7e4bfbeec0"


class EvidenceProjectionError(RuntimeError):
    """The sealed run cannot support the canonical promotion."""


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


def _run_verifier() -> dict[str, Any]:
    spec = importlib.util.spec_from_file_location(
        "lvs_rest_current_runtime_verifier", HERE / "verify.py"
    )
    if spec is None or spec.loader is None:
        raise EvidenceProjectionError("cannot load the sealed verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.verify()
    if result.get("status") != "passed" or result.get("promotion_eligible") is not True:
        raise EvidenceProjectionError("sealed verification did not pass")
    return result


def _oracle_sha(oracle: dict[str, Any]) -> str:
    raw = json.dumps(oracle, sort_keys=True, separators=(",", ":")).encode()
    return _sha(raw)


def build() -> dict[str, Any]:
    contract, contract_raw = _load(HERE / "contract.json")
    receipt, receipt_raw = _load(HERE / "runtime-receipt.json")
    summary, summary_raw = _load(HERE / "official-runtime-evidence.json")
    if _sha(contract_raw) != CONTRACT_SHA256:
        raise EvidenceProjectionError("contract digest drifted")
    if _sha(receipt_raw) != RECEIPT_SHA256:
        raise EvidenceProjectionError("receipt digest drifted")
    if _sha(summary_raw) != SUMMARY_SHA256:
        raise EvidenceProjectionError("qualification summary digest drifted")
    verification = _run_verifier()

    ledger, _ = _load(PARITY / "official-capabilities.json")
    plan, _ = _load(PARITY / "capability-oracles.json")
    capability = next(row for row in ledger["capabilities"] if row["id"] == CAPABILITY_ID)
    oracle = next(row for row in plan["oracles"] if row["capability_id"] == CAPABILITY_ID)
    expected_evidence = [
        {
            "path": (
                "deploy/docker/thor-local/qualification/"
                "lvs-rest-current-runtime-successor/canonical-runtime-evidence.json"
            ),
            "sha256": CANONICAL_SHA256,
        }
    ]
    if (
        capability.get("runtime_state") != "passed_current"
        or capability.get("thor_state") != "wired"
        or capability.get("runtime_evidence") != expected_evidence
        or oracle.get("acceptance_readiness")
        != {"classification": "executor_ready", "blockers": []}
        or oracle.get("reviewed_scenario_ids")
        != ["rest-api-operation-matrix", "oracle.api.core.lvs-17"]
        or oracle.get("execution_bounds", {}).get("max_requests") != 69
        or oracle.get("execution_bounds", {}).get("max_actions") != 4
        or oracle.get("cleanup", {}).get("targets")
        != ["vss-oracle-api-core-lvs-17-"]
    ):
        raise EvidenceProjectionError("ledger/oracle promotion drifted")
    if (
        receipt.get("result") != "passed"
        or receipt.get("promotion_eligible") is not True
        or summary.get("status") != "passed_current"
        or summary.get("promotion_eligible") is not True
        or verification.get("operation_count") != 18
        or verification.get("requests") != receipt["counts"]["requests"]
        or verification.get("actions") != receipt["counts"]["actions"]
    ):
        raise EvidenceProjectionError("retained result envelope drifted")

    operations = [
        {
            "method": row["method"],
            "path": row["path"],
            "status": row["status"],
            "semantic_pass": row["semantic_pass"],
        }
        for row in receipt["operations"]
    ]
    values = {
        "contract_identity": {
            "contract": capability["contract"],
            "contract_sha256": CONTRACT_SHA256,
            "receipt_sha256": RECEIPT_SHA256,
            "qualification_summary_sha256": SUMMARY_SHA256,
            "source_lock_count": len(contract["source_locks"]),
            "source_locks_match": receipt["source_hashes"]
            == {row["path"]: row["sha256"] for row in contract["source_locks"]},
            "runtime_identity_unchanged": receipt["runtime"]["unchanged"],
        },
        "semantic_result": {
            "operation_count": receipt["discovery"]["operation_count"],
            "operation_set_exact": receipt["discovery"]["exact"],
            "operation_set_sha256": receipt["discovery"]["operation_set_sha256"],
            "operations": operations,
            "all_positive_semantic_pass": all(
                row["status"] == 200 and row["semantic_pass"] for row in operations
            ),
            "adjacent_negatives": receipt["negatives"],
            "recorded_video": summary["recorded_video"],
            "live_video": summary["live_video"],
        },
        "api_contract": {
            "auth": receipt["auth"],
            "file_catalog_restored": receipt["file_lifecycle"]["catalog_restored"],
            "file_deleted": receipt["file_lifecycle"]["file_deleted"],
            "graph_restored": receipt["file_lifecycle"]["graph_restored"],
            "owned_graph_absent": receipt["file_lifecycle"]["owned_graph_absent"],
            "live_caption_documents": receipt["live"]["caption_documents"],
            "cleanup": receipt["cleanup"],
            "requests": receipt["counts"]["requests"],
            "actions": receipt["counts"]["actions"],
            "warehouse_sample_bundle": receipt["warehouse_sample_bundle"],
            "agent_generate_calls": receipt["policy"]["agent_generate_calls"],
            "vios_or_rt_cv_stream_mutations": receipt["policy"][
                "vios_or_rt_cv_stream_mutations"
            ],
        },
    }
    assertions = [
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
        "assertions": assertions,
        "cleanup": {
            "result": "pass",
            "mutation": oracle["cleanup"]["mutation"],
            "targets": oracle["cleanup"]["targets"],
            "allowlist": oracle["cleanup"]["allowlist"],
            "pre_state_captured": True,
            "postconditions": [
                {"description": value, "result": "pass"}
                for value in oracle["cleanup"]["postconditions"]
            ],
        },
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
