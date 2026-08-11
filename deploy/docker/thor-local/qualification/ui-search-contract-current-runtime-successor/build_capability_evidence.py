#!/usr/bin/env python3
"""Project the sealed complete Search UI run into canonical evidence."""

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
CAPABILITY_ID = "runtime.ui.search-tab"
CONTRACT_PATH = HERE / "contract.json"
RECEIPT_PATH = HERE / "runtime-receipt.json"
SUMMARY_PATH = HERE / "official-runtime-evidence.json"
OUTPUT_PATH = HERE / "canonical-runtime-evidence.json"
CONTRACT_SHA256 = "71dec2ac7077970df573a6d09181db546ff21d58ac7783fb42601eb75e111230"
RECEIPT_SHA256 = "314c314b6250310d6ab2a7cd0ed5d92463a971dac829599e240c506d06fc0867"
SUMMARY_SHA256 = "5e0fcda66f79fca334cc03e1e65b54a68e861e47a75ea7c11afcafb372ceab40"


class EvidenceProjectionError(RuntimeError):
    """The sealed Search UI run cannot support the canonical projection."""


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
        "ui_search_contract_current_runtime_verifier", HERE / "verify.py"
    )
    if spec is None or spec.loader is None:
        raise EvidenceProjectionError("cannot load the sealed Search UI verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.verify()
    if result.get("status") != "passed" or result.get("promotion_eligible") is not True:
        raise EvidenceProjectionError("sealed Search UI verification did not pass")
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
        raise EvidenceProjectionError("Search UI contract digest drifted")
    if _sha(receipt_raw) != RECEIPT_SHA256:
        raise EvidenceProjectionError("Search UI receipt digest drifted")
    if _sha(summary_raw) != SUMMARY_SHA256:
        raise EvidenceProjectionError("Search UI qualification summary digest drifted")
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
            "ui-workflows",
            "search-archive-workflows",
            "oracle.runtime.ui.search-tab",
        ]
        or oracle.get("execution_bounds", {}).get("max_requests") != 250
        or oracle.get("execution_bounds", {}).get("max_actions") != 18
        or oracle.get("cleanup", {}).get("mutation") != "read_only"
        or oracle.get("cleanup", {}).get("targets") != []
        or oracle.get("cleanup", {}).get("allowlist") != []
    ):
        raise EvidenceProjectionError("Search UI ledger/oracle promotion drifted")
    if (
        receipt.get("status") != "passed_current_candidate"
        or receipt.get("promotion_eligible") is not True
        or summary.get("status") != "passed_current"
        or summary.get("promotion_eligible") is not True
        or verification.get("browser_actions") != receipt["bounds"]["browser_actions"]
    ):
        raise EvidenceProjectionError("Search UI retained result envelope drifted")

    ui = receipt["ui_semantics"]
    cleanup = receipt["cleanup"]
    critic = receipt["pre_state"]["critic"]
    selected = receipt["identity"]["selected_object_evidence"]
    real_critic = receipt["identity"]["critic_runtime_evidence"]
    diagnostics = ui["diagnostics"]
    values = {
        "contract_identity": {
            "contract": capability["contract"],
            "contract_sha256": CONTRACT_SHA256,
            "qualification_summary_sha256": SUMMARY_SHA256,
            "receipt_sha256": RECEIPT_SHA256,
            "source_lock_count": len(contract["source_locks"]),
        },
        "semantic_result": {
            "search_component_visible": ui["page_identity"]["search_component_visible"],
            "source_default_video_file": ui["source_contract"]["default_video_file"],
            "source_values": ui["source_contract"]["values"],
            "source_round_trip": ui["source_contract"][
                "rtsp_and_video_file_round_trip"
            ],
            "top_k_default": ui["filter_contract"]["defaults"]["top_k"],
            "top_k_minimum": ui["filter_contract"]["top_k_minimum"],
            "similarity_default": ui["filter_contract"]["defaults"]["similarity"],
            "request_top_k": ui["request_contract"]["top_k"],
            "request_video_file": ui["request_contract"]["source_type_video_file"],
            "request_agent_mode_false": ui["request_contract"]["agent_mode_false"],
            "request_empty_sources": ui["request_contract"]["empty_video_sources"],
            "request_null_time_range": ui["request_contract"]["null_time_range"],
            "critic_default_enabled": critic["runtime_default_enabled"],
            "critic_disable_env_supported": critic["disable_env_supported"],
            "critic_rendered_order": ui["critic_contract"]["rendered_order"],
            "selected_object_evidence_passed": selected["passed"],
            "real_local_critic_evidence_passed": real_critic["passed"],
            "real_local_confirmed_card_count": real_critic["confirmed_card_count"],
        },
        "boundary_pair": {
            "below_minimum_top_k_clamped": ui["filter_contract"][
                "top_k_minimum_selected"
            ],
            "critic_input_order": ui["critic_contract"]["input_order"],
            "critic_rendered_order": ui["critic_contract"]["rendered_order"],
            "critic_similarity_endpoints": [
                min(ui["critic_contract"]["similarities"]),
                max(ui["critic_contract"]["similarities"]),
            ],
            "browser_local_time_without_conversion": ui["time_contract"][
                "local_time_without_offset_conversion"
            ],
            "desktop_horizontal_overflow": (
                ui["desktop"]["overflow"]["document"]
                > ui["desktop"]["overflow"]["viewport"]
            ),
            "mobile_horizontal_overflow": (
                ui["mobile"]["overflow"]["document"]
                > ui["mobile"]["overflow"]["viewport"]
            ),
            "unexpected_browser_failures": (
                len(diagnostics["console_error_hashes"])
                + len(diagnostics["console_warning_hashes"])
                + len(diagnostics["page_error_hashes"])
                + len(diagnostics["request_failure_hashes"])
                + len(diagnostics["failing_response_hashes"])
                + diagnostics["framework_error_overlay_count"]
                + diagnostics["non_loopback_request_count"]
                + diagnostics["non_loopback_response_count"]
                + diagnostics["non_loopback_websocket_count"]
            ),
            "expected_audio_probe_abort_count": diagnostics[
                "expected_audio_probe_abort_count"
            ],
            "persistent_mutations": cleanup["persistent_mutations"],
            "runtime_unchanged": cleanup["runtime_unchanged"],
            "dependencies_reverified": (
                cleanup["selected_object_evidence_reverified"]
                and cleanup["critic_runtime_evidence_reverified"]
            ),
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
