from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "metadata_500_current_search_runtime_project", HERE / "project.py"
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

    rows = {row["id"]: row for row in ledger["capabilities"][:289]}
    oracle_rows = {row["capability_id"]: row for row in oracles["oracles"][:289]}
    backend = rows["runtime.agent.search-profile"]
    ui = rows["runtime.ui.search-tab"]
    backend_oracle = oracle_rows["runtime.agent.search-profile"]
    ui_oracle = oracle_rows["runtime.ui.search-tab"]

    for capability in (backend, ui):
        assert capability["runtime_state"] == "passed_current"
        assert capability["thor_state"] == "wired"
        assert capability["runtime_evidence"]
    for oracle in (backend_oracle, ui_oracle):
        assert oracle["acceptance_readiness"] == {
            "classification": "executor_ready",
            "blockers": [],
        }
        assert oracle["evidence"] == []

    assert backend_oracle["execution_bounds"]["max_requests"] == 48
    assert backend_oracle["execution_bounds"]["max_actions"] == 14
    assert backend_oracle["cleanup"]["targets"] == [
        "mdx-behavior-2025-01-01",
        "mdx-raw-2025-01-01",
    ]
    assert ui_oracle["execution_bounds"]["max_requests"] == 250
    assert ui_oracle["execution_bounds"]["max_actions"] == 18
    assert ui_oracle["cleanup"]["mutation"] == "read_only"
    assert ui_oracle["cleanup"]["targets"] == []
    assert ui_oracle["cleanup"]["allowlist"] == []

    features = {row["id"]: row for row in manifest["features"]}
    assert features["semantic-search"]["thor_state"] == "partial"
    assert features["semantic-search"]["runtime_state"] == "not_qualified"
    assert features["main-ui"]["thor_state"] == "partial"
    assert features["main-ui"]["runtime_state"] == "not_qualified"


def test_checked_in_projection_has_no_drift() -> None:
    outputs = project.build_outputs()
    assert all(
        (project.REPO / path).read_bytes() == raw for path, raw in outputs.items()
    )
