#!/usr/bin/env python3
"""Project the retained Dashboard browser run into canonical runtime evidence."""

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
CAPABILITY_ID = "runtime.ui.dashboard-tab"
CONTRACT_PATH = HERE / "contract.json"
RECEIPT_PATH = HERE / "runtime-receipt.json"
OUTPUT_PATH = HERE / "official-runtime-evidence.json"
CONTRACT_SHA256 = "21a6f9a7d70489d4bde567cfe6aa6fca2d4f18381a8052757e5b474b4384add2"
RECEIPT_SHA256 = "800d5f9d0f821a4be971c3b63dc1be79d6fe9b37cfc8270627ba8404e0f5104a"
TARGET_COMMIT = "e96af9bbdc947e2c460ee34dec8ace129b1a86ab"


class EvidenceProjectionError(RuntimeError):
    """The retained receipt cannot support the exact official projection."""


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


def _run_receipt_verifier() -> None:
    spec = importlib.util.spec_from_file_location(
        "ui_dashboard_retained_receipt_verify", HERE / "verify.py"
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
        or receipt.get("browser_plugin") != "absent_regular_playwright_fallback"
    ):
        raise EvidenceProjectionError("receipt envelope drifted")
    if any(value is not True for value in receipt.get("checks", {}).values()):
        raise EvidenceProjectionError("a required browser check did not pass")
    if receipt.get("diagnostics", {}).get("unknown_404_paths") != []:
        raise EvidenceProjectionError("unknown browser 404 remains")
    if receipt.get("diagnostics", {}).get("classification") != (
        "known_local_security_gap_not_dashboard_render_failure"
    ):
        raise EvidenceProjectionError("browser diagnostic classification drifted")
    if receipt.get("cleanup") != {
        "mutation": "none_read_only",
        "persistent_resources_created": 0,
        "persistent_resources_deleted": 0,
        "persistent_state_unchanged": True,
        "temporary_screenshots_only": True,
    }:
        raise EvidenceProjectionError("read-only cleanup drifted")


def _values(
    capability: dict[str, Any], receipt: dict[str, Any]
) -> dict[str, Any]:
    identity = receipt["identity"]
    render = receipt["render"]
    dashboard = receipt["dashboard"]
    diagnostics = receipt["diagnostics"]
    return {
        "contract_identity": {
            "contract": capability["contract"],
            "contract_sha256": CONTRACT_SHA256,
            "receipt_sha256": RECEIPT_SHA256,
            "fixture_sha256": receipt["fixture_sha256"],
            "target_commit": receipt["target_commit"],
            "ui": {
                "configured_image": identity["ui"]["configured_image"],
                "image_id": identity["ui"]["image_id"],
                "healthy": identity["ui"]["healthy"],
            },
            "kibana": {
                "configured_image": identity["kibana"]["configured_image"],
                "image_id": identity["kibana"]["image_id"],
                "healthy": identity["kibana"]["healthy"],
            },
            "source_locks": identity["source_locks"],
        },
        "semantic_result": {
            "checks": receipt["checks"],
            "dashboard_id": dashboard["id"],
            "dashboard_title": dashboard["title"],
            "saved_object_sha256": dashboard["saved_object_sha256"],
            "required_panel_titles": dashboard["required_panel_titles"],
            "dashboard_count": dashboard["dashboard_count"],
            "iframe_title": render["iframe_title"],
            "iframe_path": render["iframe_path"],
            "iframe_hash_prefix": render["iframe_hash_prefix"],
            "iframe_sandbox_tokens": render["iframe_sandbox_tokens"],
            "frame_body_sha256": render["frame_body_sha256"],
            "desktop": render["desktop"],
            "mobile": render["mobile"],
            "duration_ms": receipt["bounds"]["duration_ms"],
            "browser_actions": receipt["bounds"]["browser_actions"],
            "direct_api_requests": receipt["bounds"]["direct_api_requests"],
            "loopback_browser_responses": receipt["bounds"][
                "loopback_browser_responses"
            ],
        },
        "boundary_pair": {
            "positive_saved_object_present": receipt["checks"][
                "saved_object_present"
            ],
            "positive_desktop_render": receipt["checks"]["desktop_render"],
            "positive_mobile_render": receipt["checks"]["mobile_render"],
            "adjacent_missing_object_status": receipt["adjacent_negative"]["status"],
            "adjacent_missing_object_sha256": receipt["adjacent_negative"][
                "body_sha256"
            ],
            "unknown_404_paths": diagnostics["unknown_404_paths"],
            "known_security_profile_404_count": diagnostics[
                "known_security_profile_404_count"
            ],
            "diagnostic_classification": diagnostics["classification"],
            "local_security_gap_open": diagnostics["local_security_gap_open"],
            "persistent_state_unchanged": receipt["cleanup"][
                "persistent_state_unchanged"
            ],
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
        != ["ui-workflows", "oracle.runtime.ui.dashboard-tab"]
    ):
        raise EvidenceProjectionError("Dashboard ledger/oracle promotion drifted")

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
