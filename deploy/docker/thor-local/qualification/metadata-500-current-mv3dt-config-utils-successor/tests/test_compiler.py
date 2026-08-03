from __future__ import annotations

import copy
import hashlib
import importlib.util
from pathlib import Path
import unittest


PACKAGE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "mv3dt_config_utils_projection", PACKAGE / "compiler.py"
)
assert SPEC is not None and SPEC.loader is not None
compiler = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compiler)


class MV3DTConfigUtilsProjectionTests(unittest.TestCase):
    def test_checked_output_is_exact_derivation(self) -> None:
        _, output, _ = compiler.derive()
        payload = compiler.encoded(output)
        checked = compiler.OUTPUT.read_bytes()
        self.assertEqual(checked, payload)
        self.assertEqual(
            hashlib.sha256(checked).hexdigest(), compiler.EXPECTED_OUTPUT_SHA256
        )

    def test_rebased_prefix_and_candidate_suffix_are_exact(self) -> None:
        baseline, _, _ = compiler.derive()
        current = compiler.load_locked(compiler.CURRENT_ORACLES)
        selected = compiler.load_locked(compiler.SELECTED_ORACLES)
        self.assertEqual(baseline["policy"], current["policy"])
        current_by_id = {row["capability_id"]: row for row in current["oracles"]}
        selected_by_id = {
            row["capability_id"]: row for row in selected["oracles"][:289]
        }
        for row in baseline["oracles"][:289]:
            capability_id = row["capability_id"]
            expected = (
                selected_by_id[capability_id]
                if capability_id in compiler.TARGET_IDS
                else current_by_id[capability_id]
            )
            self.assertEqual(row, expected)
        self.assertEqual(baseline["oracles"][289:], selected["oracles"][289:])
        self.assertEqual(len(baseline["oracles"][289:]), 211)

    def test_only_two_target_rows_change(self) -> None:
        baseline, output, bindings = compiler.derive()
        counts = compiler.validate(baseline, output, bindings)
        self.assertEqual(counts["preserved_oracles"], 498)
        self.assertEqual(counts["projected_executor_ready"], 2)
        self.assertEqual(counts["projected_actions"], 17)
        self.assertEqual(counts["projected_requests"], 14)
        self.assertEqual(counts["runtime_evidence"], 0)

    def test_future_rows_bind_exact_runtime_interface(self) -> None:
        _, output, bindings = compiler.derive()
        rows = {row["capability_id"]: row for row in output["oracles"]}
        interface, _ = compiler.load_interface()
        executor = interface["executor"]["path"]
        for capability_id in compiler.TARGET_IDS:
            row = rows[capability_id]
            binding = bindings[capability_id]
            self.assertEqual(row["current_state"], "open_unexecuted")
            self.assertEqual(row["evidence"], [])
            self.assertEqual(row["fixture"]["availability"], "not_staged")
            self.assertEqual(
                row["fixture"]["materialization"],
                {
                    "generator": executor,
                    "path": binding["fixture_manifest"]["path"],
                    "sha256": binding["fixture_manifest"]["sha256"],
                },
            )
            self.assertEqual(row["execution_bounds"]["executor"], executor)
            self.assertEqual(row["execution_bounds"]["collectors"], [executor])
            expected_actions = 7 if capability_id == compiler.TARGET_IDS[0] else 10
            self.assertEqual(row["execution_bounds"]["max_actions"], expected_actions)
            self.assertEqual(row["execution_bounds"]["max_requests"], 7)
            self.assertEqual(
                row["execution_bounds"]["workload"],
                binding["execution_bounds"]["workload"],
            )
            self.assertEqual(row["cleanup"]["executor"], executor)
            self.assertEqual(row["cleanup"]["postcondition_collectors"], [executor])
            self.assertEqual(
                row["acceptance_readiness"],
                {"blockers": [], "classification": "executor_ready"},
            )
            self.assertEqual(row["ledger_binding"]["thor_state"], "wired")
            self.assertEqual(row["ledger_binding"]["runtime_state"], "passed_current")

    def test_historical_wave3_and_candidate_observation_are_preserved(self) -> None:
        baseline, output, _ = compiler.derive()
        before = {row["capability_id"]: row for row in baseline["oracles"]}
        after = {row["capability_id"]: row for row in output["oracles"]}
        for capability_id in compiler.TARGET_IDS:
            self.assertEqual(
                after[capability_id]["ledger_binding"]["contract"],
                before[capability_id]["ledger_binding"]["contract"],
            )
            wave3 = after[capability_id]["ledger_binding"]["contract"][
                "wave3_acceptance"
            ]
            self.assertIs(wave3["materialized"], False)
            self.assertIs(wave3["executor_ready"], False)
            self.assertEqual(
                after[capability_id]["offline_tool_observation_bindings"],
                before[capability_id]["offline_tool_observation_bindings"],
            )

    def test_undeclared_mutation_fails_closed(self) -> None:
        baseline, output, bindings = compiler.derive()
        mutated = copy.deepcopy(output)
        target = next(
            row
            for row in mutated["oracles"]
            if row["capability_id"] == compiler.TARGET_IDS[0]
        )
        target["fixture"]["availability"] = "operator_required"
        with self.assertRaisesRegex(compiler.ProjectionError, "undeclared change"):
            compiler.validate(baseline, mutated, bindings)


if __name__ == "__main__":
    unittest.main()
