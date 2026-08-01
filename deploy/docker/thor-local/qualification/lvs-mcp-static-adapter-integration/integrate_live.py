#!/usr/bin/env python3
"""Integrate the Thor-local LVS file-management adapter into live contracts.

This is the third deterministic static successor.  It replays the immutable
source-contract predecessor without re-validating source files that were
intentionally changed by this adapter, applies a narrowly allowlisted planning
delta, and records no runtime evidence or passed-current promotion.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any


sys.dont_write_bytecode = True

LANE = Path(__file__).resolve().parent
REPO_ROOT = LANE.parents[4]
PARITY = REPO_ROOT / "deploy/docker/thor-local/parity"
QUALIFICATION = REPO_ROOT / "deploy/docker/thor-local/qualification"
LEDGER = PARITY / "official-capabilities.json"
MANIFEST = PARITY / "manifest.json"
ORACLES = PARITY / "capability-oracles.json"
ACCEPTANCE = QUALIFICATION / "acceptance_inventory.json"
RECEIPT = LANE / "live-integration-receipt.json"

PREDECESSOR = QUALIFICATION / "source-contract-integration/integrate_live.py"
PREDECESSOR_RECEIPT = (
    QUALIFICATION / "source-contract-integration/live-integration-receipt.json"
)
ORACLE_COMPILER = PARITY / "capability_oracles.py"

PREDECESSOR_RAW_SHA256 = "dcb2f8119da1c2b719c4398549861c0929af9bfdf53b933301b6d4677e4318f7"
PREDECESSOR_RECEIPT_RAW_SHA256 = "ae8716961b6a2ad30680cdf19587bd0578209594b6a39987b704ad2a29a1aad5"
PREDECESSOR_RECEIPT_CANONICAL_SHA256 = "b1bd743da7511d2034ab0755d458f6b019df493f34c76fe81c9b2af2291a31fa"
PREDECESSOR_CONTRACT_SHA256 = "1ba9dac99127932ddf8f517e1d87631bd13240fa61b8f360b123c42242f98cb9"
PREDECESSOR_OUTPUTS = {
    "official-capabilities.json": "32befd108b8e4f3eb10c066c3a28a936b277ff68d2b4940cf9e1ef40107e1873",
    "manifest.json": "bd181bea21b053407da4df7767e73496c4defab100d109e4ee0a3e113e42f35a",
    "acceptance_inventory.json": "9b6a1f8e4aa3e6a6545f37baffdb346143608056aa21f88ad18dee3df9dbed47",
    "capability-oracles.json": "000c2dfddd80ecaed14c416cb94827c34d68cb5b05e7111e17678b0aa94db1bb",
    "capability-oracles.schema.json": "d3f86870fcca6bdb80eacb92bd402a88f34bacd68c42e52ac3408d05e0437498",
}
ORACLE_COMPILER_RAW_SHA256 = "bf029e8f1b3e50401368b77021d0b2b3373cb98ac9dafe7ffcd4f87e2bafd034"

STATIC_INPUTS = {
    "deploy/docker/thor-local/qualification/api_inventory.json": "5d7f5e9303eedebdaabaec25dd77677540475d968850b8481ab4422c2d6b525b",
    "deploy/docker/thor-local/qualification/expected/lvs.json": "40b5dc3aadb33eb6ad05fc40c9a125329e8552d4f0006260eaddc202b9210aaf",
    "deploy/docker/thor-local/qualification/expected/lvs-mcp.json": "2e4eeb61c98688ed2cb7d5e0662513edd3b5ee8db470c61a90b8e91001ff598e",
    "services/video-summarization/src/lvs_mcp.py": "2d7f5fcf1b88119a60a75c71ee5560d7ecbd2872bd341fa906521ed859ec1de0",
    "services/video-summarization/src/via_server.py": "80192bc98f7c501839ec2d561e8e9bedfce6673d1459276aa7b653d75dc3dd96",
    "services/video-summarization/src/rtvi_vlm_client.py": "46cdf3abc75146497dd94b5fe0a41895ff900fc08f9ff278dc56de9858944383",
    "deploy/docker/thor-local/patches/patch_lvs_file_management.py": "d1c5e52fb908063362952d3fb28c38c675bb2adb4ccb2bfd4dfd06ba94ec95d1",
    "deploy/docker/thor-local/Dockerfile.video-summarization": "50b77993332df61de4fc0a42dcdb1856ba3307b392b922d10de70eb08d591663",
    "deploy/docker/thor-local/compose.yml": "1106c34a4831c6545ed8024c92f8bcba413f1d90a22434844c9cd446d0069778",
    "deploy/docker/services/video-summarization/compose.yml": "4bf61024fc548a56f0b8e8b01611609daed47b7201eba93878268ec06193a97f",
}

ADAPTER_TOOLS = ["add_file", "list_files", "get_file_info", "delete_file"]
UPSTREAM_TOOLS = [
    "health_ready",
    "health_live",
    "get_metrics",
    "list_models",
    "summarize_video",
    "generate_captions",
    "stream_summarize",
    "generate_vlm_captions",
    "get_recommended_config",
]
LOCAL_TOOLS = [
    "add_file",
    "delete_file",
    "generate_captions",
    "generate_vlm_captions",
    "get_file_info",
    "get_metrics",
    "get_recommended_config",
    "health_live",
    "health_ready",
    "list_files",
    "list_models",
    "stream_summarize",
    "summarize_video",
]


class IntegrationError(ValueError):
    """The immutable predecessor, reviewed adapter, or live output drifted."""


def encoded(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()


def raw_sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def _locked(path: Path, expected: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise IntegrationError(f"reviewed input is unavailable: {path}")
    if raw_sha256(path.read_bytes()) != expected:
        raise IntegrationError(f"reviewed input digest drift: {path}")


def _module(name: str, path: Path) -> Any:
    if path.is_symlink() or not path.is_file():
        raise IntegrationError(f"reviewed module is unavailable: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise IntegrationError(f"cannot load reviewed module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _historical_predecessor() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Replay the immutable second successor while permitting reviewed source evolution.

    The old reconciliation verifies live source bytes, which necessarily drift
    when this adapter is added.  Its transformation, receipt, and all four
    reconstructed outputs remain digest-checked here; only that obsolete live
    evidence recheck is bypassed.
    """

    _locked(PREDECESSOR, PREDECESSOR_RAW_SHA256)
    _locked(PREDECESSOR_RECEIPT, PREDECESSOR_RECEIPT_RAW_SHA256)
    predecessor_receipt = json.loads(PREDECESSOR_RECEIPT.read_text(encoding="utf-8"))
    if (
        canonical_sha256(predecessor_receipt) != PREDECESSOR_RECEIPT_CANONICAL_SHA256
        or predecessor_receipt.get("contract_sha256") != PREDECESSOR_CONTRACT_SHA256
        or predecessor_receipt.get("outputs") != PREDECESSOR_OUTPUTS
    ):
        raise IntegrationError("immutable source-contract receipt binding drift")

    source = _module("lvs_adapter_source_predecessor", PREDECESSOR)
    executor = _module(
        "lvs_adapter_executor_predecessor", source.PREDECESSOR_INTEGRATOR
    )
    original_loader = executor._module

    def historical_loader(name: str, path: Path) -> Any:
        module = original_loader(name, path)
        if path == executor.RECONCILE:
            module.verify_evidence = lambda descriptor, _repo_root: {
                item["path"]: item["sha256"]
                for item in descriptor["reviewed_evidence"]
            }
        return module

    executor._module = historical_loader
    ten_case = executor.build_expected(execute=False)
    source._predecessor = lambda: ten_case
    values = source.build_expected(execute=False)
    names = (
        "official-capabilities.json",
        "manifest.json",
        "acceptance_inventory.json",
        "capability-oracles.json",
    )
    for name, value in zip(names, values[:4], strict=True):
        if raw_sha256(encoded(value)) != PREDECESSOR_OUTPUTS[name]:
            raise IntegrationError(f"immutable predecessor output drift: {name}")
    if values[4] != predecessor_receipt:
        raise IntegrationError("immutable predecessor receipt differs from replay")
    return values


def _by_id(items: list[dict[str, Any]], identifier: str) -> dict[str, Any]:
    matches = [item for item in items if item.get("id") == identifier]
    if len(matches) != 1:
        raise IntegrationError(f"expected one exact record: {identifier}")
    return matches[0]


def _apply_delta(
    ledger: dict[str, Any], manifest: dict[str, Any], acceptance: dict[str, Any]
) -> None:
    source_hashes = {
        "lvs-api-doc-3.2.1": "eef97a91cba69f24c4d9f04457dbc7652df07247bc0cdcbd9d7159b2d9a97c8f",
        "lvs-doc-3.2.1": "17a2fe3fd627f9d06edc0585e02df7f8244694dab3b5d209c9bc701a3deec99a",
        "main-repository-7732edf8": "fc36e720d9ab4a684b328a2b234456959932163de93e5d8dd54d162b2fe97089",
    }
    for source_id, digest in source_hashes.items():
        _by_id(ledger["sources"], source_id)["claim_set_sha256"] = digest

    lvs = _by_id(ledger["capabilities"], "api.core.lvs-17")
    if lvs["contract"].get("operation_count") != 17:
        raise IntegrationError("LVS REST predecessor count drift")
    lvs["contract"]["operation_count"] = 18
    lvs["contract"]["expected_manifest_sha256"] = STATIC_INPUTS[
        "deploy/docker/thor-local/qualification/expected/lvs.json"
    ]

    mcp = _by_id(ledger["capabilities"], "api.core.lvs-mcp-doc-13-repo-9")
    if (
        mcp.get("thor_state") != "blocked_upstream"
        or mcp.get("runtime_state") != "blocked"
        or mcp.get("contract", {}).get("repository_tool_count") != 9
    ):
        raise IntegrationError("LVS MCP predecessor state drift")
    mcp["thor_state"] = "wired"
    mcp["runtime_state"] = "static_only"
    mcp["contract"] = {
        "docs_tool_count": 13,
        "upstream_repository_tool_count": 9,
        "repository_tool_count": 13,
        "upstream_missing_tools": copy.deepcopy(ADAPTER_TOOLS),
        "upstream_repository_tools": copy.deepcopy(UPSTREAM_TOOLS),
        "repository_tools": copy.deepcopy(LOCAL_TOOLS),
        "thor_local_adapter_tools": copy.deepcopy(ADAPTER_TOOLS),
        "expected_manifest": "deploy/docker/thor-local/qualification/expected/lvs-mcp.json",
        "expected_manifest_sha256": STATIC_INPUTS[
            "deploy/docker/thor-local/qualification/expected/lvs-mcp.json"
        ],
    }
    mcp["gap"] = (
        "A Thor-local static adapter now supplies the four file-management MCP tools "
        "missing from the pinned upstream repositories. The exact 13-tool source "
        "contract is wired, but discovery and a disposable add/list/info/delete "
        "lifecycle still require runtime qualification."
    )

    discrepancy = _by_id(
        ledger["source_discrepancies"], "lvs-mcp-doc-13-vs-repository-9"
    )
    discrepancy["resolution"] = (
        "The versioned 3.2.1 Video Summarization documentation lists 13 MCP tools, "
        "including add_file, list_files, get_file_info, and delete_file, while both "
        "pinned upstream repository implementations register nine tools. Thor closes "
        "the local static surface with a bounded four-tool adapter, without changing "
        "the upstream discrepancy or manufacturing runtime evidence."
    )
    discrepancy["must_not_claim"] = (
        "Do not claim either pinned upstream repository exposes all 13 documented "
        "MCP tools, or that the Thor-local adapter has passed a live file lifecycle."
    )

    video = _by_id(manifest["features"], "video-summarization-live")
    video["gap"] = (
        "All 18 LVS HTTP routes and 13 SSE MCP tools, including the four Thor-local "
        "file-management adapters, are statically qualified. MCP health tools probe "
        "real LVS readiness/liveness, but every tool and the separate dense-caption "
        "cache/embedding lanes still require runtime exercise."
    )
    api = _by_id(manifest["features"], "agent-and-mcp-apis")
    api["gap"] = (
        "The scoped core ledger passes 327 declared REST operations (326 normalized "
        "routes) plus all 42 tools and five prompts across 17 surfaces. It is not the "
        "complete product API: configuration and calibration surfaces are tracked "
        "separately by extended-api-surfaces. The GET-only loopback tier defines 32 "
        "probes across 22 services; the stopped unified stack still needs every "
        "inventoried route, tool, prompt, and VIOS-backed path exercised."
    )
    core = _by_id(manifest["features"], "core-api-operation-contracts")
    core["runtime_state"] = "static_only"
    core["gap"] = (
        "Operation manifests are exact and digest-bound, including the four Thor-local "
        "LVS file-management adapters. Execution remains plan-only, and the pinned "
        "upstream LVS repositories still expose only nine of the 13 documented MCP tools."
    )

    scenarios = acceptance["coverage"]["api_surfaces"]
    lvs_row = next(item for item in scenarios if item.get("surface_id") == "lvs")
    lvs_row["expected_item_count"] = 18
    lvs_row["items_sha256"] = "393a04089472b75b33fccd61650356ed52319b46450ad812657cedd8559bb214"
    mcp_row = next(item for item in scenarios if item.get("surface_id") == "lvs-mcp")
    mcp_row["expected_item_count"] = 13
    mcp_row["items_sha256"] = "b8166875144e5aab3cfa31730b1f40ed67dbba6dc8067fc74b667c3f6802a621"


def _validate_semantics(
    predecessor: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    ledger: dict[str, Any],
    acceptance: dict[str, Any],
    oracles: dict[str, Any],
) -> None:
    old_ledger, _old_manifest, old_acceptance, _old_oracles, _receipt = predecessor
    if (
        len(ledger["capabilities"]) != 276
        or len(old_ledger["capabilities"]) != 276
    ):
        raise IntegrationError("capability denominator drift")
    if len(ledger["source_discrepancies"]) != len(old_ledger["source_discrepancies"]):
        raise IntegrationError("upstream discrepancy denominator drift")
    if acceptance["wave3_contracts"] != old_acceptance["wave3_contracts"]:
        raise IntegrationError("historical planning contracts changed")
    rows = oracles.get("oracles", [])
    if len(rows) != 276 or any(
        row.get("acceptance_readiness", {}).get("classification") != "planning_index_only"
        for row in rows
    ):
        raise IntegrationError("capability oracle planning boundary drift")
    if any(row.get("runtime_evidence") for row in rows):
        raise IntegrationError("runtime evidence was added")
    if any(row.get("current_state") == "passed_current" for row in rows):
        raise IntegrationError("passed_current promotion is forbidden")


def build_expected(
    *, execute: bool = False
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    # Kept for compatibility with acceptance.py's successor interface. This
    # lane is static-only, so either value deterministically replays receipts.
    del execute
    for relative, digest in STATIC_INPUTS.items():
        _locked(REPO_ROOT / relative, digest)
    _locked(ORACLE_COMPILER, ORACLE_COMPILER_RAW_SHA256)
    predecessor = _historical_predecessor()
    ledger, manifest, acceptance = copy.deepcopy(predecessor[:3])
    _apply_delta(ledger, manifest, acceptance)
    compiler = _module("lvs_adapter_oracle_compiler", ORACLE_COMPILER)
    oracles = compiler.compile_plan(ledger, acceptance_document=acceptance)
    _validate_semantics(predecessor, ledger, acceptance, oracles)
    receipt_core = {
        "schema_version": 1,
        "integration_id": "lvs-mcp-static-adapter-2026-08-01",
        "predecessor": {
            "integrator_path": "deploy/docker/thor-local/qualification/source-contract-integration/integrate_live.py",
            "integrator_raw_sha256": PREDECESSOR_RAW_SHA256,
            "receipt_path": "deploy/docker/thor-local/qualification/source-contract-integration/live-integration-receipt.json",
            "receipt_raw_sha256": PREDECESSOR_RECEIPT_RAW_SHA256,
            "receipt_canonical_sha256": PREDECESSOR_RECEIPT_CANONICAL_SHA256,
            "contract_sha256": PREDECESSOR_CONTRACT_SHA256,
            "outputs": copy.deepcopy(PREDECESSOR_OUTPUTS),
        },
        "static_inputs": [
            {"path": path, "raw_sha256": digest}
            for path, digest in sorted(STATIC_INPUTS.items())
        ],
        "delta": {
            "capability_ids": ["api.core.lvs-17", "api.core.lvs-mcp-doc-13-repo-9"],
            "discrepancy_ids": ["lvs-mcp-doc-13-vs-repository-9"],
            "feature_ids": [
                "video-summarization-live",
                "agent-and-mcp-apis",
                "core-api-operation-contracts",
            ],
            "api_surface_ids": ["lvs", "lvs-mcp"],
            "local_adapter_tools": copy.deepcopy(ADAPTER_TOOLS),
        },
        "expected_counts": {
            "capabilities": 276,
            "oracles": 276,
            "planning_index_only_oracles": 276,
            "static_subset_oracle_bindings": 26,
            "runtime_evidence_records": 0,
            "passed_current_promotions": 0,
            "lvs_rest_operations": 18,
            "lvs_mcp_tools": 13,
            "upstream_lvs_mcp_tools": 9,
        },
        "boundaries": {
            "evidence_class": "deterministic_static_adapter_contract_not_runtime",
            "upstream_discrepancy_preserved": True,
            "runtime_evidence_added": False,
            "passed_current_allowed": False,
            "warehouse_sample_bundle": "excluded",
            "network": "forbidden",
            "docker": "forbidden",
            "subprocess": "forbidden",
        },
    }
    receipt = copy.deepcopy(receipt_core)
    receipt["contract_sha256"] = canonical_sha256(receipt_core)
    receipt["outputs"] = {
        "official-capabilities.json": raw_sha256(encoded(ledger)),
        "manifest.json": raw_sha256(encoded(manifest)),
        "acceptance_inventory.json": raw_sha256(encoded(acceptance)),
        "capability-oracles.json": raw_sha256(encoded(oracles)),
    }
    receipt["lifecycle"] = "third_static_adapter_successor_integrated"
    return ledger, manifest, acceptance, oracles, receipt


def validate_live() -> dict[str, Any]:
    ledger, manifest, acceptance, oracles, receipt = build_expected()
    if RECEIPT.read_bytes() != encoded(receipt):
        raise IntegrationError("third successor receipt differs from replay")
    for path, value in {
        LEDGER: ledger,
        MANIFEST: manifest,
        ACCEPTANCE: acceptance,
        ORACLES: oracles,
    }.items():
        if path.read_bytes() != encoded(value):
            raise IntegrationError(f"partial or drifted third successor: {path.name}")
    return {"lifecycle": receipt["lifecycle"], **receipt["expected_counts"]}


def validate_predecessor() -> dict[str, Any]:
    """Replay and digest-check the immutable second successor only."""
    values = _historical_predecessor()
    receipt = values[4]
    return {"lifecycle": receipt["lifecycle"], **receipt["expected_counts"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("plan", "validate", "validate-predecessor", "write")
    )
    args = parser.parse_args()
    try:
        if args.command == "validate":
            print(json.dumps(validate_live(), sort_keys=True))
            return 0
        if args.command == "validate-predecessor":
            print(json.dumps(validate_predecessor(), sort_keys=True))
            return 0
        ledger, manifest, acceptance, oracles, receipt = build_expected()
        if args.command == "plan":
            print(json.dumps({"lifecycle": "prospective_third_static_adapter_successor", **receipt["expected_counts"]}, sort_keys=True))
            return 0
        for path, value in {
            LEDGER: ledger,
            MANIFEST: manifest,
            ACCEPTANCE: acceptance,
            ORACLES: oracles,
            RECEIPT: receipt,
        }.items():
            path.write_bytes(encoded(value))
        print(json.dumps({"lifecycle": receipt["lifecycle"], **receipt["expected_counts"]}, sort_keys=True))
        return 0
    except (IntegrationError, OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
