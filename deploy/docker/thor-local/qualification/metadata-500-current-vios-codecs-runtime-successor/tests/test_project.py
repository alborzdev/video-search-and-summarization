from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("metadata_500_codec_project", HERE / "project.py")
assert SPEC is not None and SPEC.loader is not None
project = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = project
SPEC.loader.exec_module(project)


def test_projection_is_exact_current_prefix_plus_candidate_suffix() -> None:
    outputs = project.build_outputs()
    ledger = json.loads(outputs[project.OUTPUT_LEDGER_500])
    oracles = json.loads(outputs[project.OUTPUT_ORACLES_500])
    selector = json.loads(outputs[project.SELECTOR])
    current_ledger = json.loads((project.REPO / project.CURRENT_LEDGER).read_bytes())
    current_oracles = json.loads((project.REPO / project.CURRENT_ORACLES).read_bytes())

    assert ledger["capabilities"][:289] == current_ledger["capabilities"]
    assert oracles["oracles"][:289] == current_oracles["oracles"]
    assert len(ledger["capabilities"]) == 500
    assert len(oracles["oracles"]) == 500
    assert selector["selected_set"] == project.SET_ID_500


def test_checked_in_projection_has_no_drift() -> None:
    outputs = project.build_outputs()
    assert all((project.REPO / path).read_bytes() == raw for path, raw in outputs.items())
