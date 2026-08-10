#!/usr/bin/env python3
"""Verify retained RT-Embed evidence and canonical capability bindings."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
PARITY = REPO / "deploy/docker/thor-local/parity"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(PARITY))

import build_official_evidence  # noqa: E402
import capability_oracles  # noqa: E402
import verify_official_capabilities  # noqa: E402


CAPABILITY_IDS = list(build_official_evidence.CAPABILITY_IDS)
EXPECTED = {
    "contract": "ff00f1cb91045a9f758c3dc23223fc6bc562b9a1819735e8c97d790c96ca2494",
    "receipt": "56da7bf867628791152cdb9c3cdf788801ab77aa3e4dedb374ba130bf9849934",
    "evidence": {
        CAPABILITY_IDS[
            0
        ]: "38e367d7d35e18d7e80cf9b0a20ec324e68750e2767a4ce3f0abf289e35dbe99",
        CAPABILITY_IDS[
            1
        ]: "f9cd87923a4d66c2f89641bd52a70f3cbfb1b950f6c0725960415d0d0d6beeb6",
        CAPABILITY_IDS[
            2
        ]: "4fd5ce16811e73041b935398b49729d0499dcdd20c8adb49ea3f03878b855b89",
        CAPABILITY_IDS[
            3
        ]: "033cdb49311c8b5c443aaa5f921d682c5c03a3abd0147d6e278e2c6043497586",
    },
    "oracle": {
        CAPABILITY_IDS[
            0
        ]: "3454e6b38fe07cedc0c7ad161eb08454577aae0c72768b5ede6f21731674a5b8",
        CAPABILITY_IDS[
            1
        ]: "e0daf993d9f121b25e4d7b7154da2fb24599cf029dcdded4c45c48c156461530",
        CAPABILITY_IDS[
            2
        ]: "264f74135902bd5d5d8a7841d92c01aa96d8a0224fc482dd5da197525066a12b",
        CAPABILITY_IDS[
            3
        ]: "5eec9567bca3543a1452215ad88becfc53ea00aaf03ec45fc647affebbadf66a",
    },
}


class RTEmbedEvidenceError(RuntimeError):
    """Retained RT-Embed evidence or a canonical binding drifted."""


def _load(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise RTEmbedEvidenceError(f"duplicate JSON key in {path}")
            value[key] = item
        return value

    try:
        value = json.loads(raw, object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RTEmbedEvidenceError(f"invalid JSON in {path}") from exc
    if not isinstance(value, dict):
        raise RTEmbedEvidenceError(f"{path} is not a JSON object")
    return value, raw


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _privacy_walk(value: Any, path: str = "$") -> None:
    forbidden_keys = {
        "api_key",
        "authorization",
        "content",
        "credentials",
        "ice",
        "messages",
        "prompt",
        "request_id",
        "response_body",
        "sdp",
        "session_id",
        "text_input",
        "token",
    }
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in forbidden_keys:
                raise RTEmbedEvidenceError(f"forbidden retained field at {path}/{key}")
            _privacy_walk(item, f"{path}/{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _privacy_walk(item, f"{path}/{index}")
    elif isinstance(value, str):
        lowered = value.lower()
        if (
            "nvapi-" in lowered
            or "bearer " in lowered
            or "data:video/" in lowered
            or "rtsp://" in lowered
            or "/home/nvidia/" in lowered
            or re.fullmatch(r"[a-zA-Z0-9+/]{512,}={0,2}", value) is not None
        ):
            raise RTEmbedEvidenceError(f"sensitive retained value at {path}")


def verify() -> dict[str, Any]:
    contract, contract_raw = _load(HERE / "contract.json")
    receipt, receipt_raw = _load(HERE / "runtime-receipt.json")
    if _sha(contract_raw) != EXPECTED["contract"]:
        raise RTEmbedEvidenceError("fixture contract digest drifted")
    if _sha(receipt_raw) != EXPECTED["receipt"]:
        raise RTEmbedEvidenceError("runtime receipt digest drifted")
    build_official_evidence._verify_receipt(receipt, contract)
    _privacy_walk(receipt)

    ledger, _ = _load(PARITY / "official-capabilities.json")
    plan, _ = _load(PARITY / "capability-oracles.json")
    capabilities = {row["id"]: row for row in ledger["capabilities"]}
    oracles = {row["capability_id"]: row for row in plan["oracles"]}
    rebuilt = build_official_evidence.build()
    for capability_id, evidence_path in build_official_evidence.OUTPUTS.items():
        evidence, evidence_raw = _load(evidence_path)
        evidence_sha = _sha(evidence_raw)
        oracle = oracles[capability_id]
        capability = capabilities[capability_id]
        oracle_sha = capability_oracles.canonical_oracle_sha256(oracle)
        expected_reference = [
            {
                "path": str(evidence_path.relative_to(REPO)),
                "sha256": EXPECTED["evidence"][capability_id],
            }
        ]
        if evidence != rebuilt[capability_id]:
            raise RTEmbedEvidenceError(
                f"official projection is not reproducible: {capability_id}"
            )
        if evidence_sha != EXPECTED["evidence"][capability_id]:
            raise RTEmbedEvidenceError(
                f"official evidence digest drifted: {capability_id}"
            )
        if (
            capability.get("runtime_state") != "passed_current"
            or capability.get("thor_state") != "wired"
            or not capability.get("gap", "").startswith("No known gap:")
            or capability.get("runtime_evidence") != expected_reference
            or oracle_sha != EXPECTED["oracle"][capability_id]
            or evidence.get("oracle_sha256") != oracle_sha
            or oracle["fixture"]["materialization"]
            != {
                "path": capability_oracles.RT_EMBED_CURRENT_RUNTIME_FIXTURE["path"],
                "generator": capability_oracles.RT_EMBED_CURRENT_RUNTIME_EXECUTOR,
                "sha256": EXPECTED["contract"],
            }
            or oracle["execution_bounds"]["max_requests"] != 43
            or oracle["execution_bounds"]["max_actions"] != 4
            or oracle["acceptance_readiness"]
            != {"classification": "executor_ready", "blockers": []}
            or oracle["cleanup"]["mutation"] != "namespaced_and_reversible"
            or oracle["cleanup"]["targets"]
            != capability_oracles.RT_EMBED_CURRENT_RUNTIME_NAMESPACES
            or oracle["cleanup"]["allowlist"]
            != capability_oracles.RT_EMBED_CURRENT_RUNTIME_NAMESPACES
        ):
            raise RTEmbedEvidenceError(
                f"ledger or oracle binding drifted: {capability_id}"
            )
        _privacy_walk(evidence)

    counts = verify_official_capabilities.validate(repo_root=REPO)
    return {
        "status": "passed",
        "capability_ids": CAPABILITY_IDS,
        "capability_count": len(CAPABILITY_IDS),
        "official_capability_count": counts["capabilities"],
        "http_request_count": receipt["http_request_count"],
        "retained_observation_count": receipt["retained_observation_count"],
        "semantic_action_count": receipt["semantic_action_count"],
        "contract_sha256": EXPECTED["contract"],
        "receipt_sha256": EXPECTED["receipt"],
        "evidence_sha256": EXPECTED["evidence"],
        "oracle_sha256": EXPECTED["oracle"],
        "warehouse_sample_bundle": False,
    }


def main() -> int:
    try:
        result = verify()
    except (
        OSError,
        KeyError,
        StopIteration,
        RTEmbedEvidenceError,
        build_official_evidence.EvidenceProjectionError,
        verify_official_capabilities.CapabilityContractError,
    ) as exc:
        print(json.dumps({"status": "failed", "error": type(exc).__name__}))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
