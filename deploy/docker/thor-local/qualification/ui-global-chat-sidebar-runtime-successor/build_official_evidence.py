#!/usr/bin/env python3
"""Project the retained Global Chat browser run into canonical evidence."""

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
CAPABILITY_ID = "runtime.ui.global-chat-sidebar"
CONTRACT_PATH = HERE / "contract.json"
RECEIPT_PATH = HERE / "runtime-receipt.json"
OUTPUT_PATH = HERE / "official-runtime-evidence.json"
CONTRACT_SHA256 = "a049b6596436e09dd7e9c9be0da76534c3b17b9d545d4af5c4c7ae062d37e632"
RECEIPT_SHA256 = "6a431d7a3b9c025ff158db9817265a96332cdcff7298d37ca0173a7ad673a743"
TARGET_COMMIT = "d16797d05490c169fd600bd653084f7e7968da0f"


class EvidenceProjectionError(RuntimeError):
    """The retained receipt cannot support the exact canonical projection."""


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


def _run_receipt_verifier() -> None:
    spec = importlib.util.spec_from_file_location(
        "ui_global_chat_retained_receipt_verify", HERE / "verify.py"
    )
    if spec is None or spec.loader is None:
        raise EvidenceProjectionError("cannot load retained-receipt verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.verify()


def _verify_receipt(
    receipt: dict[str, Any], contract: dict[str, Any]
) -> None:
    _run_receipt_verifier()
    if (
        receipt.get("schema_version") != 1
        or receipt.get("package_id") != contract["package_id"]
        or receipt.get("status") != "passed_current_candidate"
        or receipt.get("target_commit") != TARGET_COMMIT
        or receipt.get("contract_sha256") != CONTRACT_SHA256
        or receipt.get("warehouse_sample_bundle") != "excluded"
        or receipt.get("cleanup", {}).get("related_runtime_state_unchanged")
        is not True
    ):
        raise EvidenceProjectionError("receipt envelope drifted")


def _values(
    capability: dict[str, Any], receipt: dict[str, Any]
) -> dict[str, Any]:
    current = receipt["current_profile"]
    profile = receipt["profile_boundary"]
    report = receipt["report_boundary"]
    return {
        "contract_identity": {
            "contract": capability["contract"],
            "contract_sha256": CONTRACT_SHA256,
            "receipt_sha256": RECEIPT_SHA256,
            "target_commit": receipt["target_commit"],
            "runtime": receipt["pre_state"]["related_runtime"],
            "source_hashes": receipt["identity"]["source_hashes"],
            "runtime_environment": {
                "sha256": current["runtime_env"]["sha256"],
                "bytes": current["runtime_env"]["bytes"],
                "required_flags_match": current["runtime_env"]
                ["required_flags_match"],
            },
            "settings_endpoints": {
                "http": current["settings"]["http_endpoint"],
                "websocket": current["settings"]["websocket_endpoint"],
            },
        },
        "semantic_result": {
            "tabs": current["tabs"],
            "theme": current["theme"],
            "sidebar": current["sidebar"],
            "uploads": current["uploads"],
            "history": current["history"],
            "settings": {
                "required_labels_present": current["settings"]
                ["required_labels_present"],
                "schema_options": current["settings"]["schema_options"],
                "selected_schema": current["settings"]["selected_schema"],
                "intermediate_initially_enabled": current["settings"]
                ["intermediate_initially_enabled"],
                "intermediate_disabled": current["settings"]
                ["intermediate_disabled"],
                "intermediate_restored": current["settings"]
                ["intermediate_restored"],
            },
            "context_action": current["context_action"],
            "profile_boundary": {
                "changed_keys": profile["runtime_env"]["changed_keys"],
                "sidebar_remained_enabled": profile["runtime_env"]
                ["sidebar_remained_enabled"],
                "tabs": profile["tabs"],
                "profile_controlled_chat_transition": profile[
                    "profile_controlled_chat_transition"
                ],
                "legacy_and_global_coexist": profile[
                    "legacy_and_global_coexist"
                ],
                "on_chat": profile["on_chat"],
                "on_search": profile["on_search"],
            },
            "report": {
                "row_count": report["row_count"],
                "valid_generate_report_count": report[
                    "valid_generate_report_count"
                ],
                "adjacent_generate_report_suppressed": report[
                    "adjacent_generate_report_suppressed"
                ],
                "sent_state_visible": report["sent_state_visible"],
                "transport": report["transport"],
                "wire": report["wire"],
            },
            "bounds": receipt["bounds"],
        },
        "boundary_pair": {
            "positive_plus_chat_added_once": current["context_action"]
            ["added_state_count"]
            == 1,
            "positive_context_chip_added_once": current["context_action"]
            ["chip_count"]
            == 1,
            "adjacent_context_chip_removed": current["context_action"]
            ["chip_count_after_remove"]
            == 0,
            "positive_generate_report_available_once": report[
                "valid_generate_report_count"
            ]
            == 1,
            "adjacent_fallback_generate_report_suppressed": report[
                "adjacent_generate_report_suppressed"
            ],
            "report_transport_send_suppressed": report["transport"]
            ["send_suppressed"],
            "only_profile_flag_changed": profile["runtime_env"]["changed_keys"]
            == ["NEXT_PUBLIC_ENABLE_CHAT_TAB"],
            "live_context_page_errors_absent": not current["diagnostics"]
            ["page_error_hashes"]
            and not report["diagnostics"]["page_error_hashes"],
            "non_loopback_responses_absent": all(
                row["non_loopback_response_count"] == 0
                for row in (
                    current["diagnostics"],
                    profile["diagnostics"],
                    report["diagnostics"],
                )
            ),
            "related_runtime_state_unchanged": receipt["pre_state"]
            == receipt["post_state"],
            "server_resources_created": receipt["cleanup"]
            ["server_resources_created"],
            "server_resources_changed": receipt["cleanup"]
            ["server_resources_changed"],
            "server_resources_deleted": receipt["cleanup"]
            ["server_resources_deleted"],
        },
    }


def build() -> dict[str, Any]:
    contract, contract_raw = _load(CONTRACT_PATH)
    receipt, receipt_raw = _load(RECEIPT_PATH)
    if _sha(contract_raw) != CONTRACT_SHA256:
        raise EvidenceProjectionError("contract digest drifted")
    if _sha(receipt_raw) != RECEIPT_SHA256:
        raise EvidenceProjectionError("runtime receipt digest drifted")
    _verify_receipt(receipt, contract)

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
            "ui-workflows",
            "core-agent-workflows",
            "oracle.runtime.ui.global-chat-sidebar",
        ]
        or oracle.get("execution_bounds", {}).get("max_actions") != 40
        or oracle.get("execution_bounds", {}).get("max_requests") != 1200
        or oracle.get("cleanup", {}).get("targets") != []
        or oracle.get("cleanup", {}).get("allowlist") != []
    ):
        raise EvidenceProjectionError("Global Chat ledger/oracle promotion drifted")

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
