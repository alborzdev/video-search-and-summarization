from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "metadata_500_current_rt_embed_runtime_project",
    HERE / "project.py",
)
assert SPEC is not None and SPEC.loader is not None
project = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = project
SPEC.loader.exec_module(project)


CAPABILITY_IDS = (
    "model.rt-embed.cosmos-embed1-448p-anomaly",
    "behavior.rt-embed.base64-data-url",
    "behavior.rt-embed.duplicate-id-409",
    "api.core.rt-embed-24",
)


def test_projection_is_current_prefix_plus_unchanged_candidate_suffix() -> None:
    outputs = project.build_outputs()
    ledger = json.loads(outputs[project.OUTPUT_LEDGER_500])
    oracles = json.loads(outputs[project.OUTPUT_ORACLES_500])
    manifest = json.loads(outputs[project.OUTPUT_MANIFEST_500])
    current_ledger = json.loads((project.REPO / project.CURRENT_LEDGER).read_bytes())
    current_oracles = json.loads((project.REPO / project.CURRENT_ORACLES).read_bytes())
    prior_ledger = json.loads((project.REPO / project.PRIOR_LEDGER_500).read_bytes())
    prior_oracles = json.loads((project.REPO / project.PRIOR_ORACLES_500).read_bytes())

    assert ledger["capabilities"][:289] == current_ledger["capabilities"]
    assert oracles["oracles"][:289] == current_oracles["oracles"]
    assert ledger["capabilities"][289:] == prior_ledger["capabilities"][289:]
    assert oracles["oracles"][289:] == prior_oracles["oracles"][289:]
    assert len(ledger["capabilities"]) == len(oracles["oracles"]) == 500

    capabilities = {row["id"]: row for row in ledger["capabilities"]}
    oracle_rows = {row["capability_id"]: row for row in oracles["oracles"]}
    for capability_id in CAPABILITY_IDS:
        capability = capabilities[capability_id]
        oracle = oracle_rows[capability_id]
        assert capability["runtime_state"] == "passed_current"
        assert capability["thor_state"] == "wired"
        assert capability["gap"].startswith("No known gap:")
        assert oracle["acceptance_readiness"] == {
            "classification": "executor_ready",
            "blockers": [],
        }
        assert oracle["execution_bounds"]["max_requests"] == 43
        assert oracle["execution_bounds"]["max_actions"] == 4
        assert oracle["cleanup"]["mutation"] == "namespaced_and_reversible"

    families = {row["id"]: row for row in manifest["features"]}
    assert (
        "deploy/docker/thor-local/qualification/rt-embed-current-runtime/"
        "official-runtime-evidence-model.json" in families["rt-embed"]["thor_evidence"]
    )
    assert (
        "deploy/docker/thor-local/qualification/rt-embed-current-runtime/"
        "official-runtime-evidence-data-url.json"
        in families["release-behavior-contracts"]["thor_evidence"]
    )
    assert (
        "deploy/docker/thor-local/qualification/rt-embed-current-runtime/"
        "official-runtime-evidence-api.json"
        in families["core-api-operation-contracts"]["thor_evidence"]
    )
    assert families["rt-embed"]["runtime_state"] == "not_qualified"
    assert families["release-behavior-contracts"]["runtime_state"] == "not_qualified"
    assert families["core-api-operation-contracts"]["runtime_state"] == "not_qualified"


def test_checked_in_projection_has_no_drift() -> None:
    outputs = project.build_outputs()
    assert all(
        (project.REPO / path).read_bytes() == raw for path, raw in outputs.items()
    )
