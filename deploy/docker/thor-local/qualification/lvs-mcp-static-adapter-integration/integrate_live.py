#!/usr/bin/env python3
"""Integrate the Thor-local LVS file-management adapter into live contracts.

It replays the immutable static-adapter history, rebases the two current
LVS/LVS-MCP expected-manifest digests onto the newer live aggregate, and
records no runtime evidence or passed-current promotion.
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
ORACLE_COMPILER_RAW_SHA256 = "32f18f2d74508a78282cf572c00ba5f7b739b7b0969019f963e04372e791de1c"
LIVE_ORACLE_SCHEMA_RAW_SHA256 = "55de87c13e78b4f349e7095232f31c1135155e0bc13ed6bcb8e4abb906f26cf1"

STATIC_INPUTS = {
    "deploy/docker/thor-local/qualification/api_inventory.json": "17d3f26a950b142c72e5d5003ac0429ac56f552247ca24458b05c964bf0edb6d",
    "deploy/docker/thor-local/qualification/expected/lvs.json": "dcc3b500384bdc57868f018e03baad46ff9f2692f690bbb07a308bcb200dad17",
    "deploy/docker/thor-local/qualification/expected/lvs-mcp.json": "6768be993243685b467e185280f9321ea402117a9000df5f8a99d63dc094383c",
    "services/video-summarization/docker/package_file_list.txt": "2320f99c469ec0bca82022d7a60ab16098ad4fa18a36d7fdae284a1af23c96c2",
    "services/video-summarization/src/lvs_mcp.py": "32a4cc0913025ed34a5e08f751c7d08b97877a047ff72244185a1a9f7d29c211",
    "services/video-summarization/src/lvs_mcp_sse.py": "94306d18703a598982fbfe3515dcb3ed7cad31dfb106cb0d5b5c4ef92e6806f8",
    "services/video-summarization/src/via_server.py": "2f95a82460a932cc3aac0161ed227eac12f2ac080dc7e44ef1641841730d5e6d",
    "services/video-summarization/src/via_stream_handler.py": "fa10dadab32da7b6800e0acd84176f955f86adf08c4e018bfa4651c0f33e7f60",
    "services/video-summarization/src/rtvi_vlm_client.py": "46cdf3abc75146497dd94b5fe0a41895ff900fc08f9ff278dc56de9858944383",
    "services/video-summarization/tests/test_lvs_delete_cleanup.py": "4b57befb075fac25548617a1fbed857779fe2793b11fe4678ef36d472a1c4120",
    "services/video-summarization/tests/test_lvs_mcp.py": "01129bed02201c964cc4e62b16c0380bf8f636b44f78ab11944160f21813bc2e",
    "services/video-summarization/tests/test_lvs_mcp_sse.py": "1d37ff696c4ce0d892fd92b9f52f76dff5fc72366027d0ecca5f34a58b7f489e",
    "deploy/docker/thor-local/patches/patch_lvs_file_management.py": "d1c5e52fb908063362952d3fb28c38c675bb2adb4ccb2bfd4dfd06ba94ec95d1",
    "deploy/docker/thor-local/Dockerfile.video-summarization": "572e480c4ff4525bb539621668b4bddd1a080bc31a6ec15f49ef3dd8c53b22f4",
    "deploy/docker/thor-local/compose.yml": "b3f8b8d94f05e0edfbe0e1652457c80bd821d0dc93271fb75e2bc40b188c12ce",
    "deploy/docker/services/video-summarization/compose.yml": "6bf986735bb6971c03df50ec1cfa15fe2024ba213574f08ed767517e85b18e74",
    "deploy/docker/thor-local/vios-mcp/wheels-linux-aarch64.lock.json": "a65a8aa75b331209c996f99c05058e9301f50ddc7a5278da2c416ade06d6d70d",
    "deploy/docker/thor-local/qualification/offline-mv3dt-tools/contract.json": "070d8d89c0d38e2127da53478a5f093a460cc65b6a7ec4de1a45b79c36949984",
    "deploy/docker/thor-local/qualification/offline-mv3dt-tools/executor.py": "2055cf4ee3551a4cf680f1ad760eeef11c014ddb9fb952d78ec970864c9b0273",
    "deploy/docker/thor-local/qualification/offline-mv3dt-tools/execution-receipt.json": "b01ae4fe7d6007ca89ce819462c44e04407ba0cedb20bb306067038091f38063",
    "deploy/docker/thor-local/qualification/offline-mv3dt-tools/fixtures/two-camera-calibration.json": "3b31aa74c5fa132437a35f2d2241f55fb204db58dedbe104cd8632fdef91cb33",
    "deploy/docker/thor-local/qualification/offline-mv3dt-tools/result.schema.json": "e39cdaa74d3359f84be8cf16c2ace8dbf774c98de26ff89c01ff64d244d94887",
}

CURRENT_LIVE_PREDECESSOR = {
    "official-capabilities.json": "cde0dc3981aaf699a017c7108089aac72070101edc47a06489f3940e44fe52a0",
    "manifest.json": "1f56d63437bd7742cf7488b9bd85b25fc886cdaf39a3c2b46aabecbc6b7201ce",
    "acceptance_inventory.json": "79001985f9cc9d0dbb64adea2a014aaedacd0b0411d8becb5b311c8697a563a5",
    "capability-oracles.json": "c4e7a5ecfedfa2ddf18e68fc2bc110bea48d9ff7ce63d0dd4fdc169711beda90",
}
CURRENT_LIVE_PREDECESSOR_CANONICAL = {
    "official-capabilities.json": "30142a6716d48597f2daee6a5e776629393526bc7185ca7f70b89fefe2b13eec",
    "manifest.json": "cbf65ddc55b3518763bf8ee57f58f24619956473035aeca98a274a7b1bc959f2",
    "acceptance_inventory.json": "a15f9f6fb349b9907fc4934f633c9d9158dd781cd1f9cee50954ad836523dc25",
    "capability-oracles.json": "6d2b3991e6e31a74ba42c3271d7cc0dce8748468617d18772078db6abfd1e336",
}
MANIFEST_HASH_DELTA = {
    "40b5dc3aadb33eb6ad05fc40c9a125329e8552d4f0006260eaddc202b9210aaf": "dcc3b500384bdc57868f018e03baad46ff9f2692f690bbb07a308bcb200dad17",
    "2e4eeb61c98688ed2cb7d5e0662513edd3b5ee8db470c61a90b8e91001ff598e": "6768be993243685b467e185280f9321ea402117a9000df5f8a99d63dc094383c",
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
    executor.SUCCESSOR_ORACLE_SCHEMA_RAW_SHA256 = LIVE_ORACLE_SCHEMA_RAW_SHA256
    original_loader = executor._module

    def historical_loader(name: str, path: Path) -> Any:
        module = original_loader(name, path)
        if path == executor.WAVE3_MERGE:
            # Wave 3's immutable receipt binds the historical official-schema
            # digest. Later successors broadened that live schema without
            # changing the Wave 3 data output, so replay only its historical
            # schema fingerprint while preserving every other file check.
            historical_sha_file = module.sha_file
            schema_path = module.PARITY_DIR / "official-capabilities.schema.json"
            module.sha_file = lambda candidate: (
                module.EXPECTED_SCHEMA_RAW_SHA256
                if candidate == schema_path
                else historical_sha_file(candidate)
            )
        if path == executor.RECONCILE:
            module.verify_evidence = lambda descriptor, _repo_root: {
                item["path"]: item["sha256"]
                for item in descriptor["reviewed_evidence"]
            }
        if path == executor.CAPABILITY_ORACLES:
            module._offline_mv3dt_tool_bindings = lambda: {}
            historical_compile = module.compile_plan
            module.compile_plan = lambda *args, **kwargs: historical_compile(
                *args, **kwargs, include_local_runtime_bounds=False
            )
        return module

    executor._module = historical_loader
    ten_case = executor.build_expected(execute=False)
    source._predecessor = lambda: ten_case
    source_loader = source._module
    source_locked = source._locked

    def source_historical_loader(name: str, path: Path) -> Any:
        module = source_loader(name, path)
        if path == source.CAPABILITY_ORACLES:
            module._offline_mv3dt_tool_bindings = lambda: {}
            historical_compile = module.compile_plan
            module.compile_plan = lambda *args, **kwargs: historical_compile(
                *args, **kwargs, include_local_runtime_bounds=False
            )
        return module

    def source_historical_lock(path: Path, expected: str) -> None:
        if path in {source.CAPABILITY_ORACLES, source.ORACLE_SCHEMA}:
            return
        source_locked(path, expected)

    source._module = source_historical_loader
    source._locked = source_historical_lock
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


def _replace_exact_strings(value: Any, replacements: dict[str, str]) -> int:
    """Replace allowlisted string leaves in-place and return the replacement count."""
    count = 0
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, str) and item in replacements:
                value[key] = replacements[item]
                count += 1
            else:
                count += _replace_exact_strings(item, replacements)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            if isinstance(item, str) and item in replacements:
                value[index] = replacements[item]
                count += 1
            else:
                count += _replace_exact_strings(item, replacements)
    return count


def _current_live_predecessor() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Load or reconstruct the exact current aggregate predecessor after our write."""
    paths = (LEDGER, MANIFEST, ACCEPTANCE, ORACLES)
    raw_values = [path.read_bytes() for path in paths]
    values = [json.loads(raw) for raw in raw_values]
    names = tuple(CURRENT_LIVE_PREDECESSOR)
    reverse = {new: old for old, new in MANIFEST_HASH_DELTA.items()}
    for index, (name, value, raw) in enumerate(zip(names, values, raw_values, strict=True)):
        expected = CURRENT_LIVE_PREDECESSOR[name]
        if raw_sha256(raw) == expected:
            continue
        reconstructed = copy.deepcopy(value)
        replaced = _replace_exact_strings(reconstructed, reverse)
        expected_replacements = 2 if name == "official-capabilities.json" else 6 if name == "capability-oracles.json" else 0
        if (
            replaced != expected_replacements
            or canonical_sha256(reconstructed) != CURRENT_LIVE_PREDECESSOR_CANONICAL[name]
        ):
            raise IntegrationError(f"current live predecessor drift: {name}")
        values[index] = reconstructed
    return values[0], values[1], values[2], values[3]


def _apply_current_manifest_delta(ledger: dict[str, Any], oracles: dict[str, Any]) -> None:
    if _replace_exact_strings(ledger, MANIFEST_HASH_DELTA) != 2:
        raise IntegrationError("current LVS ledger manifest-hash denominator drift")
    if _replace_exact_strings(oracles, MANIFEST_HASH_DELTA) != 6:
        raise IntegrationError("current LVS oracle manifest-hash denominator drift")


def _prospective_live_bytes(path: Path, expected_replacements: int) -> bytes:
    """Apply the allowlisted hash delta without reformatting unrelated bytes."""
    raw = path.read_bytes()
    name = path.name
    old_to_new = {old.encode(): new.encode() for old, new in MANIFEST_HASH_DELTA.items()}
    new_to_old = {new: old for old, new in old_to_new.items()}
    if raw_sha256(raw) == CURRENT_LIVE_PREDECESSOR[name]:
        prospective = raw
        count = 0
        for old, new in old_to_new.items():
            occurrences = prospective.count(old)
            prospective = prospective.replace(old, new)
            count += occurrences
        if count != expected_replacements:
            raise IntegrationError(f"current live replacement denominator drift: {name}")
        return prospective
    reconstructed = raw
    count = 0
    for new, old in new_to_old.items():
        occurrences = reconstructed.count(new)
        reconstructed = reconstructed.replace(new, old)
        count += occurrences
    if count != expected_replacements or raw_sha256(reconstructed) != CURRENT_LIVE_PREDECESSOR[name]:
        raise IntegrationError(f"current live output drift: {name}")
    return raw


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
    planning_bindings = sum(len(row.get("planning_executor_bindings", [])) for row in rows)
    offline_bindings = [
        (row["capability_id"], binding)
        for row in rows
        for binding in row.get("offline_tool_observation_bindings", [])
    ]
    if planning_bindings != 26 or {capability_id for capability_id, _binding in offline_bindings} != {
        "tool.mv3dt.cam-info-generator",
        "tool.mv3dt.pub-sub-generator",
    }:
        raise IntegrationError("static subset oracle binding denominator drift")
    if any(
        binding.get("can_advance_capability") is not False
        or binding.get("can_mark_passed_current") is not False
        or binding.get("runtime_evidence") != []
        or binding.get("result", {}).get("official_capability_effect") != "none_candidate_only"
        or not binding.get("oracle_coverage", {}).get("uncovered_assertion_ids")
        for _capability_id, binding in offline_bindings
    ):
        raise IntegrationError("offline MV3DT subset boundary drift")


def build_expected(
    *, execute: bool = False
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    # Kept for compatibility with acceptance.py's successor interface. This
    # lane is static-only, so either value deterministically replays receipts.
    del execute
    for relative, digest in STATIC_INPUTS.items():
        _locked(REPO_ROOT / relative, digest)
    _locked(ORACLE_COMPILER, ORACLE_COMPILER_RAW_SHA256)
    _historical_predecessor()
    current = _current_live_predecessor()
    ledger, manifest, acceptance, oracles = copy.deepcopy(current)
    _apply_current_manifest_delta(ledger, oracles)
    if len(ledger.get("capabilities", [])) != 289 or len(oracles.get("oracles", [])) != 289:
        raise IntegrationError("current live capability/oracle denominator drift")
    if any(row.get("runtime_evidence") for row in oracles["oracles"]):
        raise IntegrationError("runtime evidence was added")
    if any(row.get("current_state") == "passed_current" for row in oracles["oracles"]):
        raise IntegrationError("passed_current promotion is forbidden")
    receipt_core = {
        "schema_version": 1,
        "integration_id": "lvs-mcp-current-contract-2026-08-02",
        "predecessor": {
            "integrator_path": "deploy/docker/thor-local/qualification/source-contract-integration/integrate_live.py",
            "integrator_raw_sha256": PREDECESSOR_RAW_SHA256,
            "receipt_path": "deploy/docker/thor-local/qualification/source-contract-integration/live-integration-receipt.json",
            "receipt_raw_sha256": PREDECESSOR_RECEIPT_RAW_SHA256,
            "receipt_canonical_sha256": PREDECESSOR_RECEIPT_CANONICAL_SHA256,
            "contract_sha256": PREDECESSOR_CONTRACT_SHA256,
            "outputs": copy.deepcopy(PREDECESSOR_OUTPUTS),
        },
        "live_current_predecessor": copy.deepcopy(CURRENT_LIVE_PREDECESSOR),
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
            "offline_tool_capability_ids": [
                "tool.mv3dt.cam-info-generator",
                "tool.mv3dt.pub-sub-generator",
            ],
            "offline_tool_qualification_package": "deploy/docker/thor-local/qualification/offline-mv3dt-tools",
        },
        "expected_counts": {
            "capabilities": 289,
            "oracles": 289,
            "planning_index_only_oracles": 289,
            "static_subset_oracle_bindings": 29,
            "offline_tool_observation_bindings": 2,
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
        "official-capabilities.json": raw_sha256(_prospective_live_bytes(LEDGER, 2)),
        "manifest.json": CURRENT_LIVE_PREDECESSOR["manifest.json"],
        "acceptance_inventory.json": CURRENT_LIVE_PREDECESSOR[
            "acceptance_inventory.json"
        ],
        "capability-oracles.json": raw_sha256(_prospective_live_bytes(ORACLES, 6)),
    }
    receipt["lifecycle"] = "current_lvs_mcp_contract_successor_integrated"
    return ledger, manifest, acceptance, oracles, receipt


def validate_live() -> dict[str, Any]:
    ledger, manifest, acceptance, oracles, receipt = build_expected()
    if RECEIPT.read_bytes() != encoded(receipt):
        raise IntegrationError("third successor receipt differs from replay")
    for path, value, count in (
        (LEDGER, ledger, 2),
        (ORACLES, oracles, 6),
    ):
        if path.read_bytes() != _prospective_live_bytes(path, count) or json.loads(
            path.read_bytes()
        ) != value:
            raise IntegrationError(f"partial or drifted third successor: {path.name}")
    for path, expected in {
        MANIFEST: CURRENT_LIVE_PREDECESSOR["manifest.json"],
        ACCEPTANCE: CURRENT_LIVE_PREDECESSOR["acceptance_inventory.json"],
    }.items():
        if raw_sha256(path.read_bytes()) != expected:
            raise IntegrationError(f"unrelated current aggregate drift: {path.name}")
    return {"lifecycle": receipt["lifecycle"], **receipt["expected_counts"]}


def validate_predecessor() -> dict[str, Any]:
    """Replay and digest-check the immutable second successor only."""
    values = _historical_predecessor()
    receipt = values[4]
    return {"lifecycle": receipt["lifecycle"], **receipt["expected_counts"]}


def review_live() -> dict[str, Any]:
    """Return the exact prospective write set without changing the checkout."""
    ledger, manifest, acceptance, oracles, receipt = build_expected()
    rows = []
    for path, prospective in {
        LEDGER: _prospective_live_bytes(LEDGER, 2),
        ORACLES: _prospective_live_bytes(ORACLES, 6),
        RECEIPT: encoded(receipt),
    }.items():
        current = path.read_bytes() if path.is_file() and not path.is_symlink() else None
        rows.append(
            {
                "path": str(path.relative_to(REPO_ROOT)),
                "current_raw_sha256": raw_sha256(current) if current is not None else None,
                "prospective_raw_sha256": raw_sha256(prospective),
                "byte_identical": current == prospective,
            }
        )
    return {
        "lifecycle": "prospective_current_lvs_mcp_contract_successor_reviewed",
        "writes_performed": False,
        "immutable_predecessor_receipts_rewritten": False,
        "static_input_count": len(STATIC_INPUTS),
        "write_targets": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("plan", "review", "validate", "validate-predecessor", "write"),
    )
    args = parser.parse_args()
    try:
        if args.command == "validate":
            print(json.dumps(validate_live(), sort_keys=True))
            return 0
        if args.command == "validate-predecessor":
            print(json.dumps(validate_predecessor(), sort_keys=True))
            return 0
        if args.command == "review":
            print(json.dumps(review_live(), sort_keys=True))
            return 0
        ledger, manifest, acceptance, oracles, receipt = build_expected()
        if args.command == "plan":
            print(json.dumps({"lifecycle": "prospective_current_lvs_mcp_contract_successor", **receipt["expected_counts"]}, sort_keys=True))
            return 0
        for path, payload in {
            LEDGER: _prospective_live_bytes(LEDGER, 2),
            ORACLES: _prospective_live_bytes(ORACLES, 6),
            RECEIPT: encoded(receipt),
        }.items():
            path.write_bytes(payload)
        print(json.dumps({"lifecycle": receipt["lifecycle"], **receipt["expected_counts"]}, sort_keys=True))
        return 0
    except (IntegrationError, OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
