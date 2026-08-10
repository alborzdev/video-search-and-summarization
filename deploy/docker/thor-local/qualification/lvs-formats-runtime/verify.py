#!/usr/bin/env python3
"""Verify retained LVS format evidence and its official ledger projection."""

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


CAPABILITY_ID = "runtime.lvs.supported-formats"
EXPECTED = {
    "contract": "28030f32ef10d0fe240b11671511a75b5b308041732206a258f9e1f333bf20d7",
    "receipt": "85b526607ff67698d43dbc424a78cc1feb4ac7304138999c0e82e65288e45f21",
    "evidence": "bedea1ec8ad2f7f10796a8aa6d8fe06bae0fd58912064c081abdcabc4b774574",
    "oracle": "a079349e0bcaca755601b9067326ed09a86b0d488e8ae4a4b6bd200067224460",
}
UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


class LvsFormatsEvidenceError(RuntimeError):
    """Retained evidence or its canonical bindings drifted."""


def _load(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise LvsFormatsEvidenceError(f"duplicate JSON key in {path}")
            value[key] = item
        return value

    try:
        value = json.loads(raw, object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LvsFormatsEvidenceError(f"invalid JSON in {path}") from exc
    if not isinstance(value, dict):
        raise LvsFormatsEvidenceError(f"{path} is not a JSON object")
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
                raise LvsFormatsEvidenceError(f"forbidden retained field at {path}")
            _privacy_walk(item, f"{path}/{key}", allowed_fixed_ids=allowed_fixed_ids)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _privacy_walk(
                item, f"{path}/{index}", allowed_fixed_ids=allowed_fixed_ids
            )
    elif isinstance(value, str):
        lowered = value.lower()
        if "nvapi-" in lowered or "bearer " in lowered:
            raise LvsFormatsEvidenceError(f"credential-like retained value at {path}")
        uuid_match = UUID_RE.search(value)
        if (
            (uuid_match and value not in allowed_fixed_ids)
            or "http://" in lowered
            or "https://" in lowered
        ):
            raise LvsFormatsEvidenceError(f"dynamic identity or URL retained at {path}")


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
        or len(receipt.get("observations", [])) != 37
        or [row.get("order") for row in receipt["observations"]]
        != list(range(1, 38))
        or receipt["pre_state"] != receipt["cleanup"]["post_state"]
        or receipt["pre_state"]["lvs_file_list_sha256"]
        != "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
        or receipt["pre_state"]["rt_vlm_asset_count"] != 0
        or receipt["pre_state"]["rt_vlm_asset_count_with_storage"] != 0
    ):
        raise LvsFormatsEvidenceError("receipt state or request accounting drifted")

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
            raise LvsFormatsEvidenceError(f"runtime identity drifted: {logical_name}")

    expected_rows = {row["name"]: row for row in contract["formats"]}
    for row in receipt["formats"]:
        expected = expected_rows[row["name"]]
        media = row["media"]
        summary = row["summarization"]
        if (
            row["extension"] != expected["extension"]
            or media["codec"] != expected["codec"]
            or media["format_name"] != expected["format_name"]
            or media["bytes"] != expected["expected_bytes"]
            or media["raw_hash_policy"] != expected["raw_hash_policy"]
            or (
                expected["expected_sha256"] is not None
                and media["sha256"] != expected["expected_sha256"]
            )
            or not re.fullmatch(r"[0-9a-f]{64}", media["sha256"])
            or not re.fullmatch(r"[0-9a-f]{64}", summary["response_sha256"])
            or not re.fullmatch(r"[0-9a-f]{64}", summary["content_sha256"])
            or summary["duration_seconds"] <= 0
            or summary["response_bytes"] <= 0
            or summary["content_bytes"] <= 0
        ):
            raise LvsFormatsEvidenceError(f"retained format result drifted: {row['name']}")

    observations = receipt["observations"]
    summary_observations = {
        row["action_id"]: row
        for row in observations
        if row["action_id"].startswith("summarize-")
    }
    if len(summary_observations) != 5:
        raise LvsFormatsEvidenceError("summarization observation count drifted")
    for row in receipt["formats"]:
        observation = summary_observations[f"summarize-{row['extension']}"]
        if (
            observation["http_status"] != 200
            or observation["path_template"] != "/v1/summarize"
            or observation["response_bytes"]
            != row["summarization"]["response_bytes"]
            or observation["response_sha256"]
            != row["summarization"]["response_sha256"]
        ):
            raise LvsFormatsEvidenceError("summary observation/receipt mismatch")
    _privacy_walk(receipt)


def verify() -> dict[str, Any]:
    contract, contract_raw = _load(HERE / "contract.json")
    receipt, receipt_raw = _load(HERE / "runtime-receipt.json")
    evidence, evidence_raw = _load(HERE / "official-runtime-evidence.json")
    if _sha(contract_raw) != EXPECTED["contract"]:
        raise LvsFormatsEvidenceError("fixture contract digest drifted")
    if _sha(receipt_raw) != EXPECTED["receipt"]:
        raise LvsFormatsEvidenceError("runtime receipt digest drifted")
    if _sha(evidence_raw) != EXPECTED["evidence"]:
        raise LvsFormatsEvidenceError("official evidence digest drifted")
    _verify_receipt(receipt, contract)

    rebuilt = build_official_evidence.build()
    if evidence != rebuilt:
        raise LvsFormatsEvidenceError("official projection is not reproducible")

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
        or capability.get("runtime_evidence")
        != [
            {
                "path": (
                    "deploy/docker/thor-local/qualification/lvs-formats-runtime/"
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
                "deploy/docker/thor-local/qualification/lvs-formats-runtime/"
                "contract.json"
            ),
            "generator": (
                "deploy/docker/thor-local/qualification/lvs-formats-runtime/"
                "execute.py"
            ),
            "sha256": EXPECTED["contract"],
        }
        or oracle["execution_bounds"]["max_requests"] != 37
        or oracle["execution_bounds"]["max_actions"] != 9
        or oracle["acceptance_readiness"]
        != {"classification": "executor_ready", "blockers": []}
        or oracle["cleanup"]["targets"]
        != capability_oracles.LVS_FORMATS_RUNTIME_NAMESPACES
    ):
        raise LvsFormatsEvidenceError("ledger or oracle binding drifted")
    _privacy_walk(
        evidence,
        allowed_fixed_ids=set(capability_oracles.LVS_FORMATS_RUNTIME_NAMESPACES[1:]),
    )
    return {
        "status": "passed",
        "capability_id": CAPABILITY_ID,
        "format_count": 5,
        "http_request_count": 37,
        "semantic_action_count": 9,
        "contract_sha256": EXPECTED["contract"],
        "receipt_sha256": EXPECTED["receipt"],
        "evidence_sha256": EXPECTED["evidence"],
        "oracle_sha256": EXPECTED["oracle"],
        "warehouse_sample_bundle": False,
    }


def main() -> int:
    try:
        result = verify()
    except (OSError, KeyError, StopIteration, LvsFormatsEvidenceError) as exc:
        print(json.dumps({"status": "failed", "error": type(exc).__name__}))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
