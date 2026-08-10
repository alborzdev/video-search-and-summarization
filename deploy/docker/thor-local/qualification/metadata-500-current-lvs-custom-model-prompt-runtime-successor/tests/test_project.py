from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "metadata_500_current_lvs_custom_model_prompt_project", HERE / "project.py"
)
assert SPEC is not None and SPEC.loader is not None
project = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = project
SPEC.loader.exec_module(project)


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

    capability = next(
        row
        for row in ledger["capabilities"]
        if row["id"] == "configuration.lvs.custom-model-prompt"
    )
    oracle = next(
        row
        for row in oracles["oracles"]
        if row["capability_id"] == "configuration.lvs.custom-model-prompt"
    )
    family = next(
        row for row in manifest["features"] if row["id"] == "model-customization"
    )
    assert capability["runtime_state"] == "passed_current"
    assert capability["thor_state"] == "wired"
    assert capability["contract"]["custom_model_environment"] is True
    assert capability["contract"]["prompt_override"] is True
    assert capability["contract"]["output_shape_must_match"] is True
    assert oracle["acceptance_readiness"] == {
        "classification": "executor_ready",
        "blockers": [],
    }
    assert oracle["execution_bounds"]["max_requests"] == 19
    assert oracle["execution_bounds"]["max_actions"] == 2
    assert (
        "deploy/docker/thor-local/qualification/lvs-custom-model-prompt-runtime/"
        "official-runtime-evidence.json"
    ) in family["thor_evidence"]
    assert family["runtime_state"] == "not_qualified"
    assert family["thor_state"] == "partial"


def test_checked_in_projection_has_no_drift() -> None:
    outputs = project.build_outputs()
    assert all(
        (project.REPO / path).read_bytes() == raw for path, raw in outputs.items()
    )
