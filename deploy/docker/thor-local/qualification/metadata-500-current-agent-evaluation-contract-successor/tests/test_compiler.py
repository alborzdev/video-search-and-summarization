from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


PACKAGE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "agent_eval_contract_compiler", PACKAGE / "compiler.py"
)
assert SPEC and SPEC.loader
compiler = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = compiler
SPEC.loader.exec_module(compiler)


def test_exact_correction_and_suffix_preservation() -> None:
    docs, payloads, counts = compiler.derive()
    assert counts == {
        "root_capabilities": 289,
        "selected_capabilities": 500,
        "corrected_capabilities": 1,
        "preserved_suffix": 211,
    }
    assert {
        name: compiler.sha(payload) for name, payload in payloads.items()
    } == compiler.EXPECTED_OUTPUT_SHA256
    old_root = compiler.baseline(compiler.ROOT_LEDGER)
    old_oracle = compiler.baseline(compiler.ROOT_ORACLE)
    old_500 = compiler.baseline(compiler.SELECTED_LEDGER)
    old_o500 = compiler.baseline(compiler.SELECTED_ORACLE)
    assert compiler.changed(
        old_root["capabilities"], docs["ledger_289"]["capabilities"], "id"
    ) == {compiler.TARGET_ID}
    assert compiler.changed(
        old_oracle["oracles"], docs["oracle_289"]["oracles"], "capability_id"
    ) == {compiler.TARGET_ID}
    assert docs["ledger_500"]["capabilities"][289:] == old_500["capabilities"][289:]
    assert docs["oracle_500"]["oracles"][289:] == old_o500["oracles"][289:]


def test_repository_bound_profile_replaces_stale_default() -> None:
    docs, _, _ = compiler.derive()
    config = compiler.yaml.safe_load(
        compiler.git_blob(compiler.UPSTREAM, compiler.CONFIG_PATH)
    )
    assert (
        config["eval"]["evaluators"]["report_evaluator"]["metric_configs"]["llm_judge"][
            "llm_name"
        ]
        == "eval_llm_judge"
    )
    assert compiler.PROFILE["llm_profile"] == "eval_llm_judge"
    capability = next(
        row
        for row in docs["ledger_289"]["capabilities"]
        if row["id"] == compiler.TARGET_ID
    )
    oracle = next(
        row
        for row in docs["oracle_289"]["oracles"]
        if row["capability_id"] == compiler.TARGET_ID
    )
    assert "judge_defaults" not in capability["contract"]
    assert capability["contract"]["judge_profile_config"] == compiler.PROFILE
    assert compiler.SOURCE_CLAIM in capability["source_claims"]
    assert oracle["ledger_binding"]["contract"] == capability["contract"]
    assert oracle["fixture"]["input"]["contract"] == capability["contract"]
    observations = [row["observation"] for row in oracle["assertions"]]
    assert not any("judge_defaults" in value for value in observations)
    assert "contract_identity/contract/judge_profile_config/max_tokens" in observations
    assert "contract_identity/contract/judge_profile_config/temperature" in observations
    assert oracle["current_state"] == "open_unexecuted"
    assert oracle["evidence"] == []


def test_wave2_and_selector_are_exactly_rebound() -> None:
    docs, _, _ = compiler.derive()
    row = next(
        row
        for row in docs["wave2"]["enrichments"]
        if row["target_id"] == compiler.TARGET_ID
    )
    assert "judge_defaults" not in row["contract_merge"]
    assert row["contract_merge"]["judge_profile_config"] == compiler.PROFILE
    assert (
        docs["selector"]["selected_set"]
        == "thor-vss-3.2.1-current-agent-evaluation-contract-500"
    )
    assert [row["set_id"] for row in docs["selector"]["available_sets"]] == [
        "thor-vss-3.2.1-current-agent-evaluation-contract-289",
        "thor-vss-3.2.1-current-agent-evaluation-contract-500",
    ]
