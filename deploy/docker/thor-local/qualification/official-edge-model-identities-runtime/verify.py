#!/usr/bin/env python3
"""Verify retained official-edge model evidence and canonical bindings."""

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
    "contract": "87f7d363c51c840dd079297cb55bc66d312d2e79b2679f4db0c6d5a878d0b924",
    "receipt": "2ef3f5df21e3dd5635f961b358932f9e4921290fc67345346986388a546c4e76",
    "evidence": {
        CAPABILITY_IDS[0]: "2ff121a4cc600641ccd62d4e6fc163e115e759b8654523ebf1ffc383577e69a4",
        CAPABILITY_IDS[1]: "b142e6a770b126611fb2033575210cb51f61ee5c9326bdb930bbfc89ac4fa373",
    },
    "oracle": {
        CAPABILITY_IDS[0]: "6a241afe35fbb1f12029114e2d7c893269de50e5dc9050ef2bcf44ca07b5a143",
        CAPABILITY_IDS[1]: "d11f2a182b6358121b7a97f9792aa98f318351fb39732084ad22eb8ac9a78d45",
    },
}
HEX_IDENTIFIER_RE = re.compile(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])")


class OfficialEdgeModelEvidenceError(RuntimeError):
    """Retained model evidence or canonical binding drifted."""


def _load(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise OfficialEdgeModelEvidenceError(
                    f"duplicate JSON key in {path}"
                )
            value[key] = item
        return value

    try:
        value = json.loads(raw, object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OfficialEdgeModelEvidenceError(f"invalid JSON in {path}") from exc
    if not isinstance(value, dict):
        raise OfficialEdgeModelEvidenceError(f"{path} is not a JSON object")
    return value, raw


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _privacy_walk(value: Any, path: str = "$") -> None:
    forbidden_keys = {
        "api_key",
        "authorization",
        "content",
        "credential",
        "credentials",
        "ice",
        "messages",
        "prompt",
        "request_id",
        "sdp",
        "session_id",
        "summary",
    }
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in forbidden_keys:
                raise OfficialEdgeModelEvidenceError(
                    f"forbidden retained field at {path}/{key}"
                )
            _privacy_walk(item, f"{path}/{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _privacy_walk(item, f"{path}/{index}")
    elif isinstance(value, str):
        lowered = value.lower()
        if (
            "nvapi-" in lowered
            or "bearer " in lowered
            or "data:image/" in lowered
            or "/home/nvidia/" in lowered
            or "http://127.0.0.1" in lowered
            or "call the thor_contract_ping" in lowered
        ):
            raise OfficialEdgeModelEvidenceError(
                f"sensitive retained value at {path}"
            )


def verify() -> dict[str, Any]:
    contract, contract_raw = _load(HERE / "contract.json")
    receipt, receipt_raw = _load(HERE / "runtime-receipt.json")
    if _sha(contract_raw) != EXPECTED["contract"]:
        raise OfficialEdgeModelEvidenceError("fixture contract digest drifted")
    if _sha(receipt_raw) != EXPECTED["receipt"]:
        raise OfficialEdgeModelEvidenceError("runtime receipt digest drifted")
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
            raise OfficialEdgeModelEvidenceError(
                f"official projection is not reproducible: {capability_id}"
            )
        if evidence_sha != EXPECTED["evidence"][capability_id]:
            raise OfficialEdgeModelEvidenceError(
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
                "path": capability_oracles.OFFICIAL_EDGE_MODEL_RUNTIME_FIXTURE[
                    "path"
                ],
                "generator": capability_oracles.OFFICIAL_EDGE_MODEL_RUNTIME_EXECUTOR,
                "sha256": EXPECTED["contract"],
            }
            or oracle["execution_bounds"]["max_requests"] != 6
            or oracle["execution_bounds"]["max_actions"] != 2
            or oracle["acceptance_readiness"]
            != {"classification": "executor_ready", "blockers": []}
            or oracle["cleanup"]["mutation"] != "read_only"
            or oracle["cleanup"]["targets"]
            != capability_oracles.OFFICIAL_EDGE_MODEL_RUNTIME_NAMESPACES
            or oracle["cleanup"]["allowlist"]
            != capability_oracles.OFFICIAL_EDGE_MODEL_RUNTIME_NAMESPACES
        ):
            raise OfficialEdgeModelEvidenceError(
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
        OfficialEdgeModelEvidenceError,
        build_official_evidence.EvidenceProjectionError,
        verify_official_capabilities.CapabilityContractError,
    ) as exc:
        print(json.dumps({"status": "failed", "error": type(exc).__name__}))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
