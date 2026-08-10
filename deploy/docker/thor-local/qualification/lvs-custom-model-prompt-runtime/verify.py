#!/usr/bin/env python3
"""Verify retained LVS custom-model/prompt evidence and canonical bindings."""

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


CAPABILITY_ID = "configuration.lvs.custom-model-prompt"
EXPECTED = {
    "contract": "16a1c5ff167774c07e1a9dca057bf15650ff5ae0367db42d7576bfc55322de9b",
    "receipt": "48fc2c5515f2ace79992277bd528ee133d6ac4c0712c5653639e1d9efb7ed1a7",
    "evidence": "79269793902ca6a4cb603d4caf99476707233c2dab05435bf0ca9d1eaae191ad",
    "oracle": "b153cde4a023f8a18f80966af8feab7ba938b8fdaa5f4237e18b22e7273a9d62",
}
UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


class LvsCustomModelPromptEvidenceError(RuntimeError):
    """Retained evidence or its canonical bindings drifted."""


def _load(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise LvsCustomModelPromptEvidenceError(
                    f"duplicate JSON key in {path}"
                )
            value[key] = item
        return value

    try:
        value = json.loads(raw, object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LvsCustomModelPromptEvidenceError(f"invalid JSON in {path}") from exc
    if not isinstance(value, dict):
        raise LvsCustomModelPromptEvidenceError(f"{path} is not a JSON object")
    return value, raw


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _privacy_walk(
    value: Any, path: str = "$", *, allowed_fixed_ids: set[str] | None = None
) -> None:
    allowed_fixed_ids = set() if allowed_fixed_ids is None else allowed_fixed_ids
    forbidden_keys = {
        "request_id",
        "video_id",
        "asset_id",
        "prompt",
        "system_prompt",
        "summary",
        "content",
        "authorization",
        "access_token",
        "refresh_token",
        "sdp",
        "ice",
    }
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in forbidden_keys:
                raise LvsCustomModelPromptEvidenceError(
                    f"forbidden retained field at {path}"
                )
            _privacy_walk(item, f"{path}/{key}", allowed_fixed_ids=allowed_fixed_ids)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _privacy_walk(
                item, f"{path}/{index}", allowed_fixed_ids=allowed_fixed_ids
            )
    elif isinstance(value, str):
        lowered = value.lower()
        if "nvapi-" in lowered or "bearer " in lowered:
            raise LvsCustomModelPromptEvidenceError(
                f"credential-like retained value at {path}"
            )
        match = UUID_RE.search(value)
        if (
            (match and value not in allowed_fixed_ids)
            or "http://" in lowered
            or "https://" in lowered
        ):
            raise LvsCustomModelPromptEvidenceError(
                f"dynamic identity or URL retained at {path}"
            )


def _verify_receipt(receipt: dict[str, Any], contract: dict[str, Any]) -> None:
    build_official_evidence._verify_receipt(receipt, contract)
    if (
        receipt["pre_state"] != receipt["cleanup"]["post_state"]
        or receipt["pre_state"]["lvs_file_list_sha256"]
        != "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
        or receipt["pre_state"]["rt_vlm_asset_count"] != 0
        or receipt["pre_state"]["rt_vlm_asset_count_with_storage"] != 0
    ):
        raise LvsCustomModelPromptEvidenceError("retained pre/post state drifted")
    prompt = receipt["custom_prompt_proof"]
    summary_observation = next(
        row
        for row in receipt["observations"]
        if row["action_id"] == "summarize-with-custom-prompt"
    )
    negative_observation = next(
        row
        for row in receipt["observations"]
        if row["action_id"] == "reject-unknown-model"
    )
    if (
        summary_observation["path_template"] != "/v1/summarize"
        or summary_observation["http_status"] != 200
        or summary_observation["response_bytes"] != prompt["response_bytes"]
        or summary_observation["response_sha256"] != prompt["response_sha256"]
        or negative_observation["path_template"] != "/v1/summarize"
        or negative_observation["http_status"] != 400
        or negative_observation["response_sha256"]
        != receipt["adjacent_negative"]["response_sha256"]
    ):
        raise LvsCustomModelPromptEvidenceError(
            "semantic observation/receipt binding drifted"
        )
    _privacy_walk(receipt)


def verify() -> dict[str, Any]:
    contract, contract_raw = _load(HERE / "contract.json")
    receipt, receipt_raw = _load(HERE / "runtime-receipt.json")
    evidence, evidence_raw = _load(HERE / "official-runtime-evidence.json")
    if _sha(contract_raw) != EXPECTED["contract"]:
        raise LvsCustomModelPromptEvidenceError("fixture contract digest drifted")
    if _sha(receipt_raw) != EXPECTED["receipt"]:
        raise LvsCustomModelPromptEvidenceError("runtime receipt digest drifted")
    if _sha(evidence_raw) != EXPECTED["evidence"]:
        raise LvsCustomModelPromptEvidenceError("official evidence digest drifted")
    _verify_receipt(receipt, contract)

    if evidence != build_official_evidence.build():
        raise LvsCustomModelPromptEvidenceError(
            "official projection is not reproducible"
        )

    ledger, _ = _load(PARITY / "official-capabilities.json")
    plan, _ = _load(PARITY / "capability-oracles.json")
    capability = next(
        row for row in ledger["capabilities"] if row["id"] == CAPABILITY_ID
    )
    oracle = next(
        row for row in plan["oracles"] if row["capability_id"] == CAPABILITY_ID
    )
    oracle_sha = capability_oracles.canonical_oracle_sha256(oracle)
    expected_evidence = [
        {
            "path": (
                "deploy/docker/thor-local/qualification/"
                "lvs-custom-model-prompt-runtime/official-runtime-evidence.json"
            ),
            "sha256": EXPECTED["evidence"],
        }
    ]
    if (
        capability.get("runtime_state") != "passed_current"
        or capability.get("thor_state") != "wired"
        or capability.get("runtime_evidence") != expected_evidence
        or oracle_sha != EXPECTED["oracle"]
        or evidence.get("oracle_sha256") != EXPECTED["oracle"]
        or oracle["fixture"]["materialization"]
        != {
            "path": (
                "deploy/docker/thor-local/qualification/"
                "lvs-custom-model-prompt-runtime/contract.json"
            ),
            "generator": (
                "deploy/docker/thor-local/qualification/"
                "lvs-custom-model-prompt-runtime/execute.py"
            ),
            "sha256": EXPECTED["contract"],
        }
        or oracle["execution_bounds"]["max_requests"] != 19
        or oracle["execution_bounds"]["max_actions"] != 2
        or oracle["acceptance_readiness"]
        != {"classification": "executor_ready", "blockers": []}
        or oracle["cleanup"]["targets"]
        != capability_oracles.LVS_CUSTOM_MODEL_PROMPT_RUNTIME_NAMESPACES
        or oracle["cleanup"]["allowlist"]
        != capability_oracles.LVS_CUSTOM_MODEL_PROMPT_RUNTIME_NAMESPACES
    ):
        raise LvsCustomModelPromptEvidenceError("ledger or oracle binding drifted")

    _privacy_walk(
        evidence,
        allowed_fixed_ids=set(
            capability_oracles.LVS_CUSTOM_MODEL_PROMPT_RUNTIME_NAMESPACES
        ),
    )
    return {
        "status": "passed",
        "capability_id": CAPABILITY_ID,
        "http_request_count": 19,
        "semantic_action_count": 2,
        "custom_prompt_event_count": receipt["custom_prompt_proof"]["event_count"],
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
        LvsCustomModelPromptEvidenceError,
    ) as exc:
        print(json.dumps({"status": "failed", "error": type(exc).__name__}))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
