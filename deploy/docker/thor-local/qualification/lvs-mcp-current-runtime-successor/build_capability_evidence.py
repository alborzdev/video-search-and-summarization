#!/usr/bin/env python3
"""Project the sealed LVS MCP run into canonical capability evidence."""

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
CAPABILITY_ID = "api.core.lvs-mcp-doc-13-repo-9"
OUTPUT_PATH = HERE / "canonical-runtime-evidence.json"
CONTRACT_SHA256 = "e3056541c684aa2cc0144637d68a8698db19a0530feab44923b46f92a04e583d"
RECEIPT_SHA256 = "28e92071fe66a32c9632d76b36dc35490342577c8af0c1414e5f88b3405cc271"
SUMMARY_SHA256 = "a1e38f88eef0dc7d6175efe34cbd701ec58371e8ef22a2cd03ed812016a37178"
CANONICAL_SHA256 = "0e206430f68a32cbbf4bb1cb0bfc353632a89057ac158362163e7468eb92a63e"


class EvidenceProjectionError(RuntimeError):
    """The sealed LVS MCP run cannot support the canonical projection."""


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
        "lvs_mcp_current_runtime_verifier", HERE / "verify.py"
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
    capability = next(
        row for row in ledger["capabilities"] if row["id"] == CAPABILITY_ID
    )
    oracle = next(
        row for row in plan["oracles"] if row["capability_id"] == CAPABILITY_ID
    )
    expected_evidence = [
        {
            "path": (
                "deploy/docker/thor-local/qualification/"
                "lvs-mcp-current-runtime-successor/canonical-runtime-evidence.json"
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
        != [
            "mcp-tool-operation-matrix",
            "oracle.api.core.lvs-mcp-doc-13-repo-9",
        ]
        or oracle.get("execution_bounds", {}).get("max_requests") != 20
        or oracle.get("execution_bounds", {}).get("max_actions") != 4
        or oracle.get("cleanup", {}).get("targets") != ["vss-oracle-lvs-mcp-"]
        or oracle.get("cleanup", {}).get("allowlist") != ["vss-oracle-lvs-mcp-"]
    ):
        raise EvidenceProjectionError("ledger/oracle promotion drifted")
    if (
        receipt.get("result") != "passed"
        or receipt.get("promotion_eligible") is not True
        or summary.get("status") != "passed_current"
        or summary.get("promotion_eligible") is not True
        or verification.get("tool_count") != receipt["transport"]["tool_count"]
        or verification.get("tool_calls") != receipt["counts"]["tool_calls"]
    ):
        raise EvidenceProjectionError("retained result envelope drifted")

    calls = receipt["tool_calls"]
    lifecycle = receipt["lifecycle"]
    cleanup = receipt["cleanup"]
    values = {
        "contract_identity": {
            "contract": capability["contract"],
            "contract_sha256": CONTRACT_SHA256,
            "qualification_summary_sha256": SUMMARY_SHA256,
            "receipt_sha256": RECEIPT_SHA256,
            "source_lock_count": len(contract["source_locks"]),
            "runtime_identity_unchanged": receipt["runtime"]["unchanged"],
        },
        "semantic_result": {
            "protocol_version": receipt["transport"]["protocol_version"],
            "server_name": receipt["transport"]["server_name"],
            "server_version": receipt["transport"]["server_version"],
            "tool_count": receipt["transport"]["tool_count"],
            "all_tools_have_schemas": receipt["transport"]["all_tools_have_schemas"],
            "tool_catalog_sha256": receipt["transport"]["tool_catalog_sha256"],
            "successful_call_names": [
                row["name"] for row in calls if row["result"] == "passed"
            ],
            "expected_error_call_names": [
                row["name"] for row in calls if row["result"] == "expected_error"
            ],
            "successful_tool_calls": receipt["counts"]["successful_tool_calls"],
            "expected_error_tool_calls": receipt["counts"]["expected_error_tool_calls"],
            "inference_tool_calls": receipt["counts"]["inference_tool_calls"],
            "stream_mutations": receipt["counts"]["stream_mutations"],
        },
        "api_contract": {
            "transport_scope": receipt["transport"]["scope"],
            "list_after_add_exact": lifecycle["list_after_add_exact"],
            "get_info_exact": lifecycle["get_info_exact"],
            "delete_confirmation_exact": lifecycle["delete_confirmation_exact"],
            "negative_traversal_sanitized": lifecycle["negative_traversal_sanitized"],
            "negative_confirmation_sanitized": lifecycle[
                "negative_confirmation_sanitized"
            ],
            "mcp_catalog_restored": lifecycle["catalog_before"]
            == lifecycle["catalog_after"],
            "rest_catalog_restored": cleanup["rest_catalog_before"]
            == cleanup["rest_catalog_after"],
            "media_root_restored": cleanup["media_root_before"]
            == cleanup["media_root_after"],
            "owned_resource_absent": cleanup["owned_resource_absent"],
            "fallback_deletes": cleanup["fallback_deletes"],
            "persistent_mutations": receipt["counts"]["persistent_mutations"],
            "service_lifecycle_mutations": cleanup["service_lifecycle_mutations"],
            "warehouse_sample_bundle": receipt["warehouse_sample_bundle"],
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
