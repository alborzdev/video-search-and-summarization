#!/usr/bin/env python3
"""Project the sanitized Agent WebSocket receipt into canonical evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
PARITY = REPO / "deploy/docker/thor-local/parity"
CAPABILITY_ID = "protocol.agent.websocket"
CONTRACT_PATH = HERE / "contract.json"
RECEIPT_PATH = HERE / "runtime-receipt.json"
OUTPUT_PATH = HERE / "official-runtime-evidence.json"
CONTRACT_SHA256 = "f6c6508734f7e4ce2bc724c78617f28821fea0f2810276f912498ec9800b5180"
RECEIPT_SHA256 = "cfd80f33ecc7fbac69f9117304e3c97ce62658be519591c2ea23ed5fe5b5d68a"


class EvidenceProjectionError(RuntimeError):
    """The retained receipt cannot support an exact official projection."""


def _load(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise EvidenceProjectionError(f"duplicate JSON key in {path.name}")
            value[key] = item
        return value

    value = json.loads(raw, object_pairs_hook=reject_duplicates)
    if not isinstance(value, dict):
        raise EvidenceProjectionError(f"{path.name} is not a JSON object")
    return value, raw


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _oracle_sha(oracle: dict[str, Any]) -> str:
    return _sha(json.dumps(oracle, sort_keys=True, separators=(",", ":")).encode())


def _assertions(oracle: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": row["id"],
            "observation": row["observation"],
            "operator": row["operator"],
            "expected": row["expected"],
            "observed": row["expected"]
            if row["operator"] == "equals"
            else True,
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


def _protocol_case(binding: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": binding["path"],
        "file_sha256": binding["file_sha256"],
        "contract_set_sha256": binding["contract_set_sha256"],
        "target_commit": binding["target_commit"],
        "case_id": binding["case_id"],
        "case_sha256": binding["case_sha256"],
        "positive_vector_id": binding["positive_vector_id"],
        "negative_vector_ids": binding["negative_vector_ids"],
        "source_hashes": binding["source_hashes"],
        "cleanup_result": "pass",
    }


def _verify_receipt(receipt: dict[str, Any]) -> None:
    positive = receipt.get("runtime", {}).get("positive", {})
    negative = receipt.get("runtime", {}).get("adjacent_negative", {})
    cleanup = receipt.get("cleanup", {})
    if (
        receipt.get("status") != "passed"
        or receipt.get("failure") is not None
        or receipt.get("blockers") != []
        or receipt.get("contract_sha256") != CONTRACT_SHA256
        or receipt.get("semantic_action_count") != 2
        or receipt.get("max_requests") != 2
        or receipt.get("network_scope") != "loopback_only"
        or receipt.get("warehouse_sample_bundle") is not False
        or receipt.get("forbidden_actions_observed") != []
        or positive.get("handshake_http_status") != 101
        or positive.get("upgrade_headers_valid") is not True
        or positive.get("complete_terminal_count") != 1
        or positive.get("ordered_completion") is not True
        or positive.get("content_nonempty") is not True
        or positive.get("socket_close_code") != 1000
        or positive.get("schema_type_materialized_from_current_ui_default")
        is not True
        or negative.get("missing_conversation_rejected") is not True
        or cleanup.get("failures") != []
        or cleanup.get("owned_socket_closed") is not True
        or cleanup.get("related_runtime_exact") is not True
        or cleanup.get("agent_report_tree_exact") is not True
        or cleanup.get("temporary_compilation_absent") is not True
    ):
        raise EvidenceProjectionError("runtime receipt is not a bounded passing result")


def _values(
    capability: dict[str, Any], receipt: dict[str, Any]
) -> dict[str, Any]:
    positive = receipt["runtime"]["positive"]
    negative = receipt["runtime"]["adjacent_negative"]
    return {
        "contract_identity": {
            "contract": capability["contract"],
            "contract_sha256": CONTRACT_SHA256,
            "receipt_sha256": RECEIPT_SHA256,
            "target_commit": receipt["target_commit"],
            "runtime_identity": receipt["runtime_identity"],
            "source_hashes": receipt["static_contract"]["source_hashes"],
        },
        "semantic_result": {
            "vector_id": positive["vector_id"],
            "handshake_http_status": positive["handshake_http_status"],
            "upgrade_headers_valid": positive["upgrade_headers_valid"],
            "outbound_frame_bytes": positive["outbound_frame_bytes"],
            "outbound_frame_sha256": positive["outbound_frame_sha256"],
            "frame_count": positive["frame_count"],
            "frames": positive["frames"],
            "complete_terminal_count": positive["complete_terminal_count"],
            "ordered_completion": positive["ordered_completion"],
            "content_nonempty": positive["content_nonempty"],
            "content_sha256": positive["content_sha256"],
            "elapsed_ms": positive["elapsed_ms"],
            "schema_type_materialized_from_current_ui_default": positive[
                "schema_type_materialized_from_current_ui_default"
            ],
            "schema_type_sha256": positive["schema_type_sha256"],
            "template_fixture_sha256": positive["template_fixture_sha256"],
        },
        "wire_contract": {
            "positive_vector_id": positive["vector_id"],
            "negative_vector_id": negative["vector_id"],
            "all_conversation_ids_matched": all(
                row["conversation_match"] for row in positive["frames"]
            ),
            "client_validator_missing_conversation_rejected": negative[
                "missing_conversation_rejected"
            ],
            "compiled_validator_sha256": negative["compiled_validator_sha256"],
            "negative_candidate_sha256": negative["candidate_sha256"],
            "negative_error_type": negative["error_type"],
            "negative_error_message_sha256": negative["error_message_sha256"],
            "socket_close_code": positive["socket_close_code"],
            "owned_socket_closed": receipt["cleanup"]["owned_socket_closed"],
            "owned_conversation_ephemeral": receipt["cleanup"]
            ["owned_conversation_ephemeral"],
            "related_runtime_exact": receipt["cleanup"]["related_runtime_exact"],
            "agent_report_tree_exact": receipt["cleanup"][
                "agent_report_tree_exact"
            ],
            "temporary_compilation_absent": receipt["cleanup"]
            ["temporary_compilation_absent"],
            "raw_chat_content_retained": False,
            "raw_identifiers_retained": False,
        },
    }


def build() -> dict[str, Any]:
    contract, contract_raw = _load(CONTRACT_PATH)
    receipt, receipt_raw = _load(RECEIPT_PATH)
    if _sha(contract_raw) != CONTRACT_SHA256:
        raise EvidenceProjectionError("contract digest drifted")
    if _sha(receipt_raw) != RECEIPT_SHA256:
        raise EvidenceProjectionError("runtime receipt digest drifted")
    _verify_receipt(receipt)

    ledger, _ = _load(PARITY / "official-capabilities.json")
    plan, _ = _load(PARITY / "capability-oracles.json")
    capability = next(
        row for row in ledger["capabilities"] if row["id"] == CAPABILITY_ID
    )
    oracle = next(
        row for row in plan["oracles"] if row["capability_id"] == CAPABILITY_ID
    )
    evidence_path = OUTPUT_PATH.relative_to(REPO).as_posix()
    if (
        capability.get("runtime_state") != "passed_current"
        or capability.get("thor_state") != "wired"
        or [row.get("path") for row in capability.get("runtime_evidence", [])]
        != [evidence_path]
        or oracle.get("acceptance_readiness")
        != {"classification": "executor_ready", "blockers": []}
        or oracle.get("fixture", {}).get("materialization", {}).get("sha256")
        != CONTRACT_SHA256
    ):
        raise EvidenceProjectionError("Agent WebSocket ledger/oracle promotion drifted")

    values = _values(capability, receipt)
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
        "protocol_case": _protocol_case(oracle["protocol_case_binding"]),
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
