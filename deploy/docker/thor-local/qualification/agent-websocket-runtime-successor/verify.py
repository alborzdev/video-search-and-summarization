#!/usr/bin/env python3
"""Fail-closed validation for retained Agent WebSocket runtime evidence."""

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
PARITY = REPO / "deploy/docker/thor-local/parity"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(PARITY))

import build_official_evidence  # noqa: E402
import capability_oracles  # noqa: E402
import verify_official_capabilities  # noqa: E402


CAPABILITY_ID = "protocol.agent.websocket"
EXPECTED = {
    "contract": "f6c6508734f7e4ce2bc724c78617f28821fea0f2810276f912498ec9800b5180",
    "receipt": "cfd80f33ecc7fbac69f9117304e3c97ce62658be519591c2ea23ed5fe5b5d68a",
    "schema": "0730ba9bc136e953f63fa6ecb67b5fb5b2b9f0e5c860a5e63180f0802e62f391",
    "evidence": "d2b82ab841a5ee9dc65ede6ada0903b973432129b71188251f2d70dc25d6da30",
    "oracle": "2115f6ea576419e4bf092286b800ccc2ef4a4f863549355d61d1ed356c0b8d2b",
}
RAW_NETWORK_PATTERN = re.compile(r"(?:https?|wss?)://", re.IGNORECASE)
SECRET_PATTERN = re.compile(
    r"(?:nvapi-|api[_-]?key|authorization|bearer\s+|session[_-]?id)",
    re.IGNORECASE,
)


class AgentWebSocketEvidenceError(RuntimeError):
    """Retained Agent WebSocket evidence is inconsistent."""


def _load(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise AgentWebSocketEvidenceError(
                    f"duplicate JSON key in {path.name}: {key}"
                )
            value[key] = item
        return value

    value = json.loads(raw, object_pairs_hook=reject_duplicates)
    if not isinstance(value, dict):
        raise AgentWebSocketEvidenceError(f"{path.name} is not a JSON object")
    return value, raw


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_sha(value: Any) -> str:
    return _sha(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def _verify_source_locks(
    contract: dict[str, Any], receipt: dict[str, Any]
) -> None:
    observed = receipt["static_contract"]["source_hashes"]
    expected = {row["path"]: row["sha256"] for row in contract["source_locks"]}
    if observed != expected:
        raise AgentWebSocketEvidenceError("receipt source-lock projection drifted")
    for path, expected_sha in expected.items():
        relative = Path(path)
        if relative.is_absolute() or ".." in relative.parts:
            raise AgentWebSocketEvidenceError("unsafe source-lock path")
        target = (REPO / relative).resolve(strict=True)
        target.relative_to(REPO)
        if _sha(target.read_bytes()) != expected_sha:
            raise AgentWebSocketEvidenceError(f"source lock drifted: {path}")


def _verify_protocol_case(
    contract: dict[str, Any], evidence: dict[str, Any]
) -> None:
    binding = contract["protocol_case"]
    protocol, raw = _load(REPO / binding["path"])
    case = next(
        row for row in protocol["cases"] if row["case_id"] == binding["case_id"]
    )
    if (
        _sha(raw) != binding["file_sha256"]
        or protocol["contract_set_sha256"] != binding["contract_set_sha256"]
        or _canonical_sha(case) != binding["case_sha256"]
        or evidence["protocol_case"]["case_sha256"] != binding["case_sha256"]
        or evidence["protocol_case"]["positive_vector_id"]
        != binding["positive_vector_id"]
        or evidence["protocol_case"]["negative_vector_ids"]
        != binding["negative_vector_ids"]
        or evidence["protocol_case"]["cleanup_result"] != "pass"
    ):
        raise AgentWebSocketEvidenceError("protocol-case binding drifted")


def _verify_retention_boundary(*raw_documents: bytes) -> None:
    for raw in raw_documents:
        text = raw.decode("utf-8")
        if RAW_NETWORK_PATTERN.search(text):
            raise AgentWebSocketEvidenceError("a raw network URL was retained")
        if SECRET_PATTERN.search(text):
            raise AgentWebSocketEvidenceError("a secret-shaped field was retained")
    receipt_text = raw_documents[1].decode("utf-8")
    forbidden_keys = (
        '"text":',
        '"prompt":',
        '"query":',
        '"request_id":',
        '"conversation_id":',
        '"session":',
    )
    if any(key in receipt_text for key in forbidden_keys):
        raise AgentWebSocketEvidenceError("raw chat content or identifier was retained")


def verify() -> dict[str, Any]:
    contract, contract_raw = _load(HERE / "contract.json")
    receipt, receipt_raw = _load(HERE / "runtime-receipt.json")
    schema, schema_raw = _load(HERE / "receipt.schema.json")
    evidence, evidence_raw = _load(HERE / "official-runtime-evidence.json")
    if (
        _sha(contract_raw) != EXPECTED["contract"]
        or _sha(receipt_raw) != EXPECTED["receipt"]
        or _sha(schema_raw) != EXPECTED["schema"]
        or _sha(evidence_raw) != EXPECTED["evidence"]
    ):
        raise AgentWebSocketEvidenceError("retained artifact digest drifted")

    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(
            schema, format_checker=FormatChecker()
        ).iter_errors(receipt),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    if errors:
        raise AgentWebSocketEvidenceError(
            f"runtime receipt schema violation: {errors[0].message}"
        )
    if receipt["contract_sha256"] != EXPECTED["contract"]:
        raise AgentWebSocketEvidenceError("receipt is not contract-bound")
    if receipt["runtime_identity"] != receipt["pre_state"]["related_runtime"]:
        raise AgentWebSocketEvidenceError("runtime pre-state projection drifted")

    positive = receipt["runtime"]["positive"]
    frames = positive["frames"]
    if (
        positive["frame_count"] != len(frames)
        or [row["ordinal"] for row in frames] != list(range(1, len(frames) + 1))
        or frames[-1]["status"] != "complete"
        or any(row["status"] == "complete" for row in frames[:-1])
        or any(row["conversation_match"] is not True for row in frames)
    ):
        raise AgentWebSocketEvidenceError("positive frame order/correlation drifted")

    _verify_source_locks(contract, receipt)
    _verify_protocol_case(contract, evidence)
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
        raise AgentWebSocketEvidenceError("runtime target is not an ancestor of HEAD")

    ledger, _ = _load(PARITY / "official-capabilities.json")
    plan, _ = _load(PARITY / "capability-oracles.json")
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
                "agent-websocket-runtime-successor/official-runtime-evidence.json"
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
        or oracle["execution_bounds"]["max_requests"] != 2
        or oracle["execution_bounds"]["max_actions"] != 2
        or oracle["cleanup"]["targets"]
        != capability_oracles.AGENT_WEBSOCKET_RUNTIME_NAMESPACES
        or _canonical_sha(oracle) != EXPECTED["oracle"]
        or evidence.get("oracle_sha256") != EXPECTED["oracle"]
    ):
        raise AgentWebSocketEvidenceError("official ledger/oracle binding drifted")

    projected = build_official_evidence.build()
    projected_raw = (json.dumps(projected, indent=2, sort_keys=True) + "\n").encode()
    if projected_raw != evidence_raw:
        raise AgentWebSocketEvidenceError("official evidence is not reproducible")

    oracle_counts = capability_oracles.validate(repo_root=REPO)
    capability_counts = verify_official_capabilities.validate(repo_root=REPO)
    return {
        "status": "passed",
        "capability_id": CAPABILITY_ID,
        "receipt_sha256": EXPECTED["receipt"],
        "evidence_sha256": EXPECTED["evidence"],
        "oracle_sha256": EXPECTED["oracle"],
        "oracle_count": oracle_counts["oracles"],
        "official_capability_count": capability_counts["capabilities"],
    }


def main() -> int:
    try:
        result = verify()
    except (
        OSError,
        KeyError,
        StopIteration,
        ValueError,
        json.JSONDecodeError,
        AgentWebSocketEvidenceError,
        build_official_evidence.EvidenceProjectionError,
        capability_oracles.OracleContractError,
        verify_official_capabilities.CapabilityContractError,
    ) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
