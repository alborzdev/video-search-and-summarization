from __future__ import annotations

import copy
import json
from pathlib import Path
import sys

import pytest


PACKAGE = Path(__file__).resolve().parents[1]
REPO = PACKAGE.parents[4]
PARITY = REPO / "deploy/docker/thor-local/parity"
sys.path.insert(0, str(PARITY))
import capability_oracles  # noqa: E402
import verify_official_capabilities as verifier  # noqa: E402


def load(name: str) -> dict:
    return json.loads((PACKAGE / name).read_text())


def promoted_documents():
    ledger = load("post-state-root-official-capabilities.json")
    oracles = load("post-state-root-capability-oracles.json")
    capabilities = {row["id"]: row for row in ledger["capabilities"]}
    oracle_rows = {row["capability_id"]: row for row in oracles["oracles"]}
    return ledger, oracles, capabilities, oracle_rows


def test_pre_and_post_promotion_oracle_plans_validate() -> None:
    capability_oracles.validate()
    ledger, oracles, _, _ = promoted_documents()
    assert (
        capability_oracles.compile_plan(
            ledger,
            acceptance_document=capability_oracles._load(capability_oracles.ACCEPTANCE),
        )
        == oracles
    )
    capability_oracles.validate(oracles, ledger)


def test_spatial_ai_aggregate_verifier_positive_and_tamper_rejection() -> None:
    ledger, _, capabilities, oracles = promoted_documents()
    aggregate = load("producer-runtime-receipt.json")
    capability_id = aggregate["capability_results"][0]["capability_id"]
    reference = capabilities[capability_id]["runtime_evidence"][0]
    selected = verifier._validate_spatial_ai_aggregate_runtime_evidence(
        aggregate,
        reference,
        capabilities[capability_id],
        capabilities,
        oracles,
        ledger["target"],
        REPO,
    )
    assert selected["capability_id"] == capability_id
    tampered = copy.deepcopy(aggregate)
    tampered["confinement"]["warehouse_sample_accesses"] = 1
    with pytest.raises(verifier.CapabilityContractError):
        verifier._validate_spatial_ai_aggregate_runtime_evidence(
            tampered,
            reference,
            capabilities[capability_id],
            capabilities,
            oracles,
            ledger["target"],
            REPO,
        )


def test_unknown_aggregate_package_is_not_dispatched_as_mv3dt() -> None:
    ledger, _, capabilities, oracles = promoted_documents()
    aggregate = load("producer-runtime-receipt.json")
    aggregate["package_id"] = "unknown-runtime-package"
    capability_id = next(iter(capabilities))
    with pytest.raises(verifier.CapabilityContractError, match="unknown aggregate"):
        verifier._validate_aggregate_runtime_evidence(
            aggregate,
            {
                "path": "x",
                "sha256": "0" * 64,
                "capability_id": capability_id,
                "json_pointer": "/capability_results/0",
            },
            capabilities[capability_id],
            capabilities,
            oracles,
            ledger["target"],
            REPO,
        )
