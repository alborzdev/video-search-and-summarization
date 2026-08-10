#!/usr/bin/env python3
"""Fail-closed offline validation for the retained Global Chat UI receipt."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
CAPABILITY_ID = "runtime.ui.global-chat-sidebar"
EXPECTED = {
    "contract": "a049b6596436e09dd7e9c9be0da76534c3b17b9d545d4af5c4c7ae062d37e632",
    "evidence": "cdda66a198192335c1bbc9e59cdb907a8084e3ff9590c62388c1926e23e3357f",
    "harness": "7b1ec751e80975a9e938d3311013fc41fb60d46dd114f445c1238f4646f7752c",
    "oracle": "c78210466c5089cbd4c818ea360ba91c14eee9037f2422547902ab74fee11687",
    "receipt": "6a431d7a3b9c025ff158db9817265a96332cdcff7298d37ca0173a7ad673a743",
    "schema": "2343acd66b9b3d21f229caf516af93a372ef78bbae2a247865c192380092b19b",
}
RAW_NETWORK_PATTERN = re.compile(r"(?:https?|wss?)://", re.IGNORECASE)
SECRET_PATTERN = re.compile(
    r"(?:nvapi-|api[_-]?key|authorization|bearer\s+|session[_-]?id)",
    re.IGNORECASE,
)


class GlobalChatEvidenceError(RuntimeError):
    """The retained Global Chat proof is inconsistent or has drifted."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _load(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise GlobalChatEvidenceError(
                    f"duplicate JSON key in {path.name}: {key}"
                )
            value[key] = item
        return value

    try:
        value = json.loads(raw, object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GlobalChatEvidenceError(f"invalid JSON in {path.name}") from exc
    if not isinstance(value, dict):
        raise GlobalChatEvidenceError(f"{path.name} is not a JSON object")
    return value, raw


def _digest(path: Path) -> str:
    return _sha(path.read_bytes())


def _canonical_sha(value: Any) -> str:
    return _sha(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def _close_enough(value: float, expected: float, tolerance: float = 0.002) -> bool:
    return abs(value - expected) <= tolerance


def _verify_source_locks(
    contract: dict[str, Any], receipt: dict[str, Any]
) -> None:
    expected = {row["path"]: row["sha256"] for row in contract["source_locks"]}
    if receipt["identity"]["source_hashes"] != expected:
        raise GlobalChatEvidenceError("receipt source-lock projection drifted")
    for relative_text, expected_sha in expected.items():
        relative = Path(relative_text)
        if relative.is_absolute() or ".." in relative.parts:
            raise GlobalChatEvidenceError("unsafe source-lock path")
        target = (REPO / relative).resolve(strict=True)
        target.relative_to(REPO)
        if _digest(target) != expected_sha:
            raise GlobalChatEvidenceError(f"source lock drifted: {relative_text}")


def _verify_runtime_identity(
    contract: dict[str, Any], receipt: dict[str, Any]
) -> None:
    before = receipt["pre_state"]["related_runtime"]
    after = receipt["post_state"]["related_runtime"]
    if before != after:
        raise GlobalChatEvidenceError("related runtime changed during browser run")
    for runtime in contract["runtime"].values():
        observed = before[runtime["container"]]
        if (
            observed["configured_image"] != runtime["configured_image"]
            or observed["image_id"] != runtime["image_id"]
            or observed["running"] is not True
            or observed["restart_count"] != 0
            or observed["oom_killed"] is not False
        ):
            raise GlobalChatEvidenceError(
                f"runtime identity drifted: {runtime['container']}"
            )


def _verify_semantics(
    contract: dict[str, Any], receipt: dict[str, Any]
) -> None:
    bounds = receipt["bounds"]
    current = receipt["current_profile"]
    profile = receipt["profile_boundary"]
    report = receipt["report_boundary"]
    diagnostics = [
        current["diagnostics"],
        profile["diagnostics"],
        report["diagnostics"],
    ]
    if bounds["browser_actions"] != sum(
        row["actions"] for row in (current, profile, report)
    ):
        raise GlobalChatEvidenceError("browser action accounting drifted")
    if bounds["loopback_browser_responses"] != sum(
        row["loopback_response_count"] for row in diagnostics
    ):
        raise GlobalChatEvidenceError("browser response accounting drifted")
    sidebar = current["sidebar"]
    if not (
        _close_enough(sidebar["initial"]["ratio"], 1 / 3)
        and _close_enough(sidebar["minimum"]["ratio"], 1 / 3)
        and _close_enough(sidebar["maximum"]["ratio"], 2 / 3)
        and _close_enough(
            sidebar["stored_width"] / sidebar["minimum"]["outer_width"],
            1 / 3,
        )
    ):
        raise GlobalChatEvidenceError("sidebar resize boundary drifted")
    if (
        current["runtime_env"]["sha256"]
        != profile["runtime_env"]["before_sha256"]
        or profile["runtime_env"]["before_sha256"]
        == profile["runtime_env"]["after_sha256"]
        or profile["runtime_env"]["changed_keys"]
        != ["NEXT_PUBLIC_ENABLE_CHAT_TAB"]
    ):
        raise GlobalChatEvidenceError("profile runtime-environment boundary drifted")
    allowed_codes = set(
        contract["runtime_boundary"][
            "synthetic_profile_override_expected_react_hydration_recovery_codes"
        ]
    )
    observed_codes = set(
        profile["diagnostics"][
            "synthetic_profile_hydration_recovery_counts"
        ]
    )
    if not observed_codes or not observed_codes <= allowed_codes:
        raise GlobalChatEvidenceError("synthetic profile diagnostic drifted")
    for index, row in enumerate(diagnostics):
        if (
            row["console_hashes"]
            or row["page_error_hashes"]
            or row["failing_response_hashes"]
            or row["non_loopback_response_count"] != 0
        ):
            raise GlobalChatEvidenceError(
                f"unexpected browser diagnostic in context {index}"
            )
    if (
        current["diagnostics"][
            "synthetic_profile_hydration_recovery_counts"
        ]
        or report["diagnostics"][
            "synthetic_profile_hydration_recovery_counts"
        ]
    ):
        raise GlobalChatEvidenceError("live context admitted synthetic diagnostics")
    fixture_contract = {
        "incident_count": 2,
        "valid_id_class": "non_fallback",
        "adjacent_id_class": "fallback_prefix",
        "category": "Qualification",
        "transport_send_suppressed": True,
    }
    fixture_sha = _sha(
        json.dumps(fixture_contract, separators=(",", ":")).encode()
    )
    if report["fixture_contract_sha256"] != fixture_sha:
        raise GlobalChatEvidenceError("report fixture contract drifted")
    if report["transport"] != {
        "captured_send_count": 1,
        "actual_send_count": 0,
        "send_suppressed": True,
    }:
        raise GlobalChatEvidenceError("report transport suppression drifted")
    if receipt["cleanup"] != {
        "mutation": "browser_session_only",
        "isolated_contexts_closed": 3,
        "browser_closed": True,
        "temporary_screenshots_deleted_after_hashing": True,
        "server_resources_created": 0,
        "server_resources_changed": 0,
        "server_resources_deleted": 0,
        "runtime_environment_override_discarded": True,
        "report_fixture_discarded": True,
        "report_transport_send_suppressed": True,
        "related_runtime_state_unchanged": True,
    }:
        raise GlobalChatEvidenceError("browser-session cleanup drifted")


def _verify_retention_boundary(*raw_documents: bytes) -> None:
    for raw in raw_documents:
        text = raw.decode("utf-8")
        if RAW_NETWORK_PATTERN.search(text):
            raise GlobalChatEvidenceError("a raw network URL was retained")
    for raw in raw_documents[1:]:
        text = raw.decode("utf-8")
        if SECRET_PATTERN.search(text):
            raise GlobalChatEvidenceError("a secret-shaped value was retained")
    receipt_text = raw_documents[1].decode("utf-8")
    forbidden_keys = (
        '"text":',
        '"prompt":',
        '"query":',
        '"request_id":',
        '"conversation_id":',
        '"session_id":',
        '"sensor_id":',
        '"incident_id":',
    )
    if any(key in receipt_text for key in forbidden_keys):
        raise GlobalChatEvidenceError(
            "raw chat content or runtime identifier was retained"
        )


def verify() -> dict[str, Any]:
    contract, contract_raw = _load(HERE / "contract.json")
    evidence, evidence_raw = _load(HERE / "official-runtime-evidence.json")
    receipt, receipt_raw = _load(HERE / "runtime-receipt.json")
    schema, schema_raw = _load(HERE / "receipt.schema.json")
    observed = {
        "contract": _sha(contract_raw),
        "evidence": _sha(evidence_raw),
        "harness": _digest(HERE / "harness.mjs"),
        "oracle": EXPECTED["oracle"],
        "receipt": _sha(receipt_raw),
        "schema": _sha(schema_raw),
    }
    if observed != EXPECTED:
        raise GlobalChatEvidenceError("retained artifact digest drifted")
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(
            schema, format_checker=FormatChecker()
        ).iter_errors(receipt),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    if errors:
        raise GlobalChatEvidenceError(
            f"runtime receipt schema violation: {errors[0].message}"
        )
    if (
        contract["capability_id"] != CAPABILITY_ID
        or receipt["contract_sha256"] != EXPECTED["contract"]
        or receipt["harness_sha256"] != EXPECTED["harness"]
        or receipt["target_commit"] != contract["target_commit"]
        or receipt["warehouse_sample_bundle"] != "excluded"
    ):
        raise GlobalChatEvidenceError("receipt envelope drifted")
    _verify_source_locks(contract, receipt)
    _verify_runtime_identity(contract, receipt)
    _verify_semantics(contract, receipt)
    _verify_retention_boundary(contract_raw, receipt_raw, evidence_raw)
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", receipt["target_commit"], "HEAD"],
        cwd=REPO,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
    )
    if ancestor.returncode != 0:
        raise GlobalChatEvidenceError(
            "runtime target is not an ancestor of the current checkout"
        )
    ledger, _ = _load(
        REPO / "deploy/docker/thor-local/parity/official-capabilities.json"
    )
    plan, _ = _load(REPO / "deploy/docker/thor-local/parity/capability-oracles.json")
    capability = next(
        row for row in ledger["capabilities"] if row["id"] == CAPABILITY_ID
    )
    oracle = next(
        row for row in plan["oracles"] if row["capability_id"] == CAPABILITY_ID
    )
    expected_reference = [
        {
            "path": (
                "deploy/docker/thor-local/qualification/"
                "ui-global-chat-sidebar-runtime-successor/"
                "official-runtime-evidence.json"
            ),
            "sha256": EXPECTED["evidence"],
        }
    ]
    if (
        capability.get("runtime_state") != "passed_current"
        or capability.get("thor_state") != "wired"
        or capability.get("runtime_evidence") != expected_reference
        or oracle.get("acceptance_readiness")
        != {"classification": "executor_ready", "blockers": []}
        or oracle.get("execution_bounds", {}).get("max_requests") != 1200
        or oracle.get("execution_bounds", {}).get("max_actions") != 40
        or oracle.get("cleanup", {}).get("targets") != []
        or oracle.get("cleanup", {}).get("allowlist") != []
        or _canonical_sha(oracle) != EXPECTED["oracle"]
        or evidence.get("oracle_sha256") != EXPECTED["oracle"]
        or evidence.get("result") != "passed_current"
        or evidence.get("capability_id") != CAPABILITY_ID
    ):
        raise GlobalChatEvidenceError("official ledger/oracle binding drifted")
    return {
        "status": "passed",
        "capability_id": CAPABILITY_ID,
        "receipt_sha256": EXPECTED["receipt"],
        "contract_sha256": EXPECTED["contract"],
        "evidence_sha256": EXPECTED["evidence"],
        "oracle_sha256": EXPECTED["oracle"],
    }


def main() -> int:
    try:
        result = verify()
    except (
        OSError,
        KeyError,
        ValueError,
        json.JSONDecodeError,
        GlobalChatEvidenceError,
    ) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
