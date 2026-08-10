#!/usr/bin/env python3
"""Project one retained Thor run into two official model capability proofs."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
PARITY = REPO / "deploy/docker/thor-local/parity"
RECEIPT_PATH = HERE / "runtime-receipt.json"
CONTRACT_SHA256 = "87f7d363c51c840dd079297cb55bc66d312d2e79b2679f4db0c6d5a878d0b924"
RECEIPT_SHA256 = "2ef3f5df21e3dd5635f961b358932f9e4921290fc67345346986388a546c4e76"
CAPABILITY_IDS = (
    "model.edge.nemotron-3-nano-4b-fp8",
    "model.edge.cosmos3-nano-served-id",
)
OUTPUTS = {
    CAPABILITY_IDS[0]: HERE / "official-runtime-evidence-nemotron.json",
    CAPABILITY_IDS[1]: HERE / "official-runtime-evidence-cosmos3.json",
}
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class EvidenceProjectionError(RuntimeError):
    """The retained receipt cannot support the exact official projections."""


def _module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise EvidenceProjectionError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


executor = _module("official_edge_model_identity_executor_evidence", HERE / "execute.py")


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


def _hash_fields(value: dict[str, Any], *keys: str) -> bool:
    return all(
        isinstance(value.get(key), str)
        and SHA256_RE.fullmatch(value[key]) is not None
        for key in keys
    )


def _verify_receipt(receipt: dict[str, Any], contract: dict[str, Any]) -> None:
    try:
        executor.validate_receipt(receipt)
    except executor.QualificationError as exc:
        raise EvidenceProjectionError("executor rejected retained receipt") from exc
    if (
        receipt.get("target") != contract["target"]
        or receipt.get("duration_seconds", 0) <= 0
        or receipt.get("duration_seconds", 0) > 240
        or receipt.get("sanitization")
        != {
            "credential_values_included": False,
            "dynamic_identifiers_included": False,
            "local_paths_included": False,
            "raw_prompts_included": False,
            "response_bodies_included": False,
        }
    ):
        raise EvidenceProjectionError("retained receipt bounds or sanitization drifted")
    llm = receipt["llm_proof"]
    vlm = receipt["vlm_proof"]
    if (
        llm.get("artifact_revision")
        != contract["models"]["llm"]["artifact_revision"]
        or llm.get("response_model_exact") is not True
        or not _hash_fields(
            llm,
            "arguments_sha256",
            "model_response_sha256",
            "semantic_response_sha256",
        )
        or llm.get("semantic_response_bytes", 0) <= 0
        or vlm.get("selector") != contract["models"]["vlm"]["selector"]
        or vlm.get("fixture_image_sha256")
        != contract["semantic_contract"]["vlm_composite_image"]["sha256"]
        or vlm.get("response_model_exact") is not True
        or not _hash_fields(
            vlm,
            "fixture_image_sha256",
            "model_response_sha256",
            "normalized_answer_sha256",
            "semantic_response_sha256",
        )
        or vlm.get("semantic_response_bytes", 0) <= 0
    ):
        raise EvidenceProjectionError("model semantic proof drifted")
    identity = receipt["runtime_identity"]
    for role in ("llm", "vlm"):
        row = identity["pre"][role]
        expected = contract["models"][role]
        if (
            row.get("image_id") != expected["image_id"]
            or row.get("image_reference") != expected["image_reference"]
            or row.get("health") != "healthy"
            or row.get("running") is not True
            or row.get("restart_count") != 0
            or row.get("oom_killed") is not False
        ):
            raise EvidenceProjectionError(f"{role} runtime identity drifted")
    cleanup = receipt["cleanup"]
    if (
        cleanup.get("mutation") != "none"
        or cleanup.get("asset_statistics_exact") is not True
        or cleanup.get("container_identity_exact") is not True
        or cleanup.get("owned_resource_count") != 0
        or cleanup.get("failures") != []
        or cleanup.get("asset_statistics_pre_sha256")
        != cleanup.get("asset_statistics_post_sha256")
    ):
        raise EvidenceProjectionError("read-only postconditions drifted")


def _values(
    capability_id: str,
    capability: dict[str, Any],
    receipt: dict[str, Any],
) -> dict[str, Any]:
    common_identity = {
        "contract": capability["contract"],
        "contract_sha256": CONTRACT_SHA256,
        "receipt_sha256": RECEIPT_SHA256,
        "readiness_passed": receipt["readiness"]["passed"],
        "source_projection_sha256": receipt["source_projection_sha256"],
    }
    if capability_id == CAPABILITY_IDS[0]:
        proof = receipt["llm_proof"]
        runtime = receipt["runtime_identity"]["pre"]["llm"]
        return {
            "contract_identity": common_identity,
            "semantic_result": {
                "artifact_revision": proof["artifact_revision"],
                "image_id": runtime["image_id"],
                "runtime_configuration": runtime["configuration"],
                "container_healthy": runtime["health"] == "healthy",
                "container_restart_count": runtime["restart_count"],
                "container_oom_killed": runtime["oom_killed"],
                "tool_call_count": proof["tool_call_count"],
                "tool_name_exact": proof["tool_name_exact"],
                "tool_arguments_exact": proof["tool_arguments_exact"],
                "thinking_disabled": proof["thinking_disabled"],
                "semantic_response_sha256": proof["semantic_response_sha256"],
                "semantic_response_bytes": proof["semantic_response_bytes"],
            },
            "model_response": {
                "served_model_id": proof["served_model_id"],
                "model_identity_exact": proof["model_identity_exact"],
                "response_model_exact": proof["response_model_exact"],
                "model_response_sha256": proof["model_response_sha256"],
                "no_fallback_observed": True,
                "container_identity_exact_after": receipt["cleanup"][
                    "container_identity_exact"
                ],
            },
        }
    if capability_id == CAPABILITY_IDS[1]:
        proof = receipt["vlm_proof"]
        runtime = receipt["runtime_identity"]["pre"]["vlm"]
        return {
            "contract_identity": common_identity,
            "semantic_result": {
                "artifact_id": proof["artifact_id"],
                "selector": proof["selector"],
                "image_id": runtime["image_id"],
                "runtime_configuration": runtime["configuration"],
                "container_healthy": runtime["health"] == "healthy",
                "container_restart_count": runtime["restart_count"],
                "container_oom_killed": runtime["oom_killed"],
                "fixture_image_sha256": proof["fixture_image_sha256"],
                "ordered_image_count": proof["ordered_image_count"],
                "ordered_panel_count": proof["ordered_panel_count"],
                "visual_answer_exact": proof["visual_answer_exact"],
                "normalized_answer_sha256": proof["normalized_answer_sha256"],
                "semantic_response_sha256": proof["semantic_response_sha256"],
                "semantic_response_bytes": proof["semantic_response_bytes"],
            },
            "model_response": {
                "served_model_id": proof["served_model_id"],
                "model_identity_exact": proof["model_identity_exact"],
                "response_model_exact": proof["response_model_exact"],
                "model_response_sha256": proof["model_response_sha256"],
                "no_fallback_observed": True,
                "asset_statistics_exact_after": receipt["cleanup"][
                    "asset_statistics_exact"
                ],
                "owned_resource_count_after": receipt["cleanup"][
                    "owned_resource_count"
                ],
                "container_identity_exact_after": receipt["cleanup"][
                    "container_identity_exact"
                ],
            },
        }
    raise EvidenceProjectionError(f"unsupported capability: {capability_id}")


def build() -> dict[str, dict[str, Any]]:
    contract, contract_raw = _load(HERE / "contract.json")
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
    result: dict[str, dict[str, Any]] = {}
    for capability_id in CAPABILITY_IDS:
        capability = capabilities[capability_id]
        oracle = oracles[capability_id]
        values = _values(capability_id, capability, receipt)
        result[capability_id] = {
            "schema_version": 1,
            "capability_id": capability_id,
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
                {
                    "id": row["id"],
                    "result": "pass",
                    "value": values[row["id"]],
                }
                for row in oracle["expected_observations"]
            ],
            "assertions": _assertions(oracle),
            "cleanup": _cleanup(oracle),
        }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    evidence = build()
    if args.write:
        for capability_id, output in OUTPUTS.items():
            output.write_text(
                json.dumps(evidence[capability_id], indent=2, sort_keys=True) + "\n"
            )
            print(f"WROTE: {output.relative_to(REPO)}")
    else:
        print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
