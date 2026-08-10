#!/usr/bin/env python3
"""Verify retained LVS one-video boundary evidence and canonical bindings."""

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
import execute  # noqa: E402


CAPABILITY_ID = "runtime.lvs.single-request-queue"
EXPECTED = {
    "contract": "2065ca45457490b299bbde56dfa0fd64529cc857f7b5e4a34c34468cc29ab49c",
    "receipt": "3359142428b97702c5a1524e66ece01db1adb7dfea13895c99c3dc928c1cc84f",
    "evidence": "7467cc46d9ebe25f6dec89dcacb60da602abce314c28b7c35bb11e13e708e9bf",
    "oracle": "4d6fe29f9ca73b5402cbbc0fd9db4e033eaed2c4feeb6756628e17eabaa1925b",
}
UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


class LvsSingleRequestEvidenceError(RuntimeError):
    """Retained evidence or its canonical bindings drifted."""


def _load(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise LvsSingleRequestEvidenceError(
                    f"duplicate JSON key in {path}"
                )
            value[key] = item
        return value

    try:
        value = json.loads(raw, object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LvsSingleRequestEvidenceError(f"invalid JSON in {path}") from exc
    if not isinstance(value, dict):
        raise LvsSingleRequestEvidenceError(f"{path} is not a JSON object")
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
                raise LvsSingleRequestEvidenceError(
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
            raise LvsSingleRequestEvidenceError(
                f"credential-like retained value at {path}"
            )
        match = UUID_RE.search(value)
        if (
            (match and match.group(0) not in allowed_fixed_ids)
            or "http://" in lowered
            or "https://" in lowered
        ):
            raise LvsSingleRequestEvidenceError(
                f"dynamic identity or URL retained at {path}"
            )


def _verify_receipt(receipt: dict[str, Any], contract: dict[str, Any]) -> None:
    build_official_evidence._verify_receipt(receipt)
    if (
        receipt.get("target") != contract["target"]
        or receipt.get("source_fixture")
        != {
            "path": contract["source_fixture"]["path"],
            "bytes": contract["source_fixture"]["bytes"],
            "sha256": contract["source_fixture"]["sha256"],
        }
        or len(receipt.get("observations", [])) != 150
        or [row.get("order") for row in receipt["observations"]]
        != list(range(1, 151))
        or receipt["pre_state"] != receipt["cleanup"]["post_state"]
        or receipt["pre_state"]["lvs_file_count"] != 0
        or receipt["pre_state"]["rt_vlm_asset_count"] != 0
        or receipt["pre_state"]["rt_vlm_asset_count_with_storage"] != 0
        or receipt["derived_fixture"]["bytes"] != contract["media"]["expected_bytes"]
        or receipt["derived_fixture"]["sha256"]
        != contract["media"]["expected_sha256"]
    ):
        raise LvsSingleRequestEvidenceError(
            "receipt state, fixture, or request accounting drifted"
        )

    identities = receipt.get("runtime_identity", {})
    for logical_name in ("lvs", "rt_vlm"):
        expected = contract["containers"][logical_name]
        identity = identities.get(logical_name, {})
        if identity != {
            "container": expected["name"],
            "image": expected["image"],
            "image_id": expected["image_id"],
            "status": "running",
            "health": "healthy",
            "restart_count": 0,
            "oom_killed": False,
        }:
            raise LvsSingleRequestEvidenceError(
                f"runtime identity drifted: {logical_name}"
            )

    observations = receipt["observations"]
    metric_rows = [
        row
        for row in observations
        if row["action_id"].startswith("queue-metric-sample-")
    ]
    summary_rows = {
        row["action_id"].removeprefix("summarize-"): row
        for row in observations
        if row["action_id"].startswith("summarize-")
    }
    if len(metric_rows) != 130 or set(summary_rows) != {"a", "b"}:
        raise LvsSingleRequestEvidenceError("observation partition drifted")
    for response in receipt["queue_proof"]["responses"]:
        observation = summary_rows[response["label"]]
        summary = response["summarization"]
        if (
            observation["http_status"] != 200
            or observation["path_template"] != "/v1/summarize"
            or observation["response_bytes"] != summary["response_bytes"]
            or observation["response_sha256"] != summary["response_sha256"]
        ):
            raise LvsSingleRequestEvidenceError(
                "summary observation/receipt mismatch"
            )
    _privacy_walk(receipt)


def verify() -> dict[str, Any]:
    contract, contract_raw = _load(HERE / "contract.json")
    receipt, receipt_raw = _load(HERE / "runtime-receipt.json")
    evidence, evidence_raw = _load(HERE / "official-runtime-evidence.json")
    if _sha(contract_raw) != EXPECTED["contract"]:
        raise LvsSingleRequestEvidenceError("fixture contract digest drifted")
    execute._verify_static(contract)
    if _sha(receipt_raw) != EXPECTED["receipt"]:
        raise LvsSingleRequestEvidenceError("runtime receipt digest drifted")
    if _sha(evidence_raw) != EXPECTED["evidence"]:
        raise LvsSingleRequestEvidenceError("official evidence digest drifted")
    _verify_receipt(receipt, contract)

    rebuilt = build_official_evidence.build()
    if evidence != rebuilt:
        raise LvsSingleRequestEvidenceError(
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
    if (
        capability.get("runtime_state") != "passed_current"
        or capability.get("thor_state") != "wired"
        or capability.get("contract", {}).get("batch_queue") != "external_required"
        or capability.get("contract", {}).get("simultaneous_video_processing")
        is not False
        or capability.get("runtime_evidence")
        != [
            {
                "path": (
                    "deploy/docker/thor-local/qualification/"
                    "lvs-single-request-queue-runtime/"
                    "official-runtime-evidence.json"
                ),
                "sha256": EXPECTED["evidence"],
            }
        ]
        or oracle_sha != EXPECTED["oracle"]
        or evidence.get("oracle_sha256") != EXPECTED["oracle"]
        or oracle["fixture"]["materialization"]
        != {
            "path": (
                "deploy/docker/thor-local/qualification/"
                "lvs-single-request-queue-runtime/contract.json"
            ),
            "generator": (
                "deploy/docker/thor-local/qualification/"
                "lvs-single-request-queue-runtime/execute.py"
            ),
            "sha256": EXPECTED["contract"],
        }
        or oracle["execution_bounds"]["max_requests"] != 150
        or oracle["execution_bounds"]["max_actions"] != 2
        or oracle["acceptance_readiness"]
        != {"classification": "executor_ready", "blockers": []}
        or oracle["cleanup"]["targets"]
        != capability_oracles.LVS_SINGLE_REQUEST_RUNTIME_NAMESPACES
    ):
        raise LvsSingleRequestEvidenceError("ledger or oracle binding drifted")
    _privacy_walk(
        evidence,
        allowed_fixed_ids=set(
            capability_oracles.LVS_SINGLE_REQUEST_RUNTIME_NAMESPACES[1:]
        ),
    )
    return {
        "status": "passed",
        "capability_id": CAPABILITY_ID,
        "submitted_requests": 2,
        "metric_sample_count": 130,
        "http_request_count": 150,
        "semantic_action_count": 2,
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
        execute.QualificationError,
        LvsSingleRequestEvidenceError,
    ) as exc:
        print(json.dumps({"status": "failed", "error": type(exc).__name__}))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
