from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest


PACKAGE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "synthetic_data_oracle_successor", PACKAGE / "compiler.py"
)
assert SPEC is not None and SPEC.loader is not None
compiler = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compiler)


class SyntheticDataOracleSuccessorTests(unittest.TestCase):
    def test_checked_output_is_exact_derivation(self) -> None:
        _, derived, _ = compiler.derive()
        payload = compiler.encoded(derived)
        checked = (PACKAGE / "post-state-capability-oracles.json").read_bytes()
        self.assertEqual(checked, payload)
        self.assertEqual(
            hashlib.sha256(checked).hexdigest(), compiler.EXPECTED_OUTPUT_SHA256
        )

    def test_only_four_declared_rows_change(self) -> None:
        source, derived, _ = compiler.derive()
        targets = {row[0] for row in compiler.TARGETS}
        source_rows = {row["capability_id"]: row for row in source["oracles"]}
        derived_rows = {row["capability_id"]: row for row in derived["oracles"]}
        changed = {
            capability_id
            for capability_id in source_rows
            if compiler.canonical_bytes(source_rows[capability_id])
            != compiler.canonical_bytes(derived_rows[capability_id])
        }
        self.assertEqual(changed, targets)
        for capability_id in targets:
            row = derived_rows[capability_id]
            self.assertEqual(row["current_state"], "open_unexecuted")
            self.assertEqual(row["evidence"], [])
            self.assertEqual(row["ledger_binding"]["runtime_state"], "passed_current")
            self.assertEqual(
                row["acceptance_readiness"],
                {"blockers": [], "classification": "executor_ready"},
            )

    def test_baseline_rebases_current_prefix_and_preserves_selected_suffix(
        self,
    ) -> None:
        baseline, _, _ = compiler.derive()
        current = compiler.load_locked(compiler.CURRENT_ORACLES)
        selected = compiler.load_locked(compiler.SOURCE_ORACLES)
        self.assertEqual(baseline["policy"], current["policy"])
        self.assertEqual(baseline["oracles"][:289], current["oracles"])
        self.assertEqual(baseline["oracles"][289:], selected["oracles"][289:])
        self.assertEqual(len(baseline["oracles"][289:]), 211)

    def test_fixture_file_and_generated_input_digests_are_distinct(self) -> None:
        contract = compiler.load_locked(compiler.RUNTIME_CONTRACT)
        runtime = {row["capability_id"]: row for row in contract["capabilities"]}
        _, derived, _ = compiler.derive()
        rows = {row["capability_id"]: row for row in derived["oracles"]}
        for capability_id, _, fixture_relative, raw_sha in compiler.TARGETS:
            fixture = json.loads(
                (PACKAGE / fixture_relative).read_text(encoding="utf-8")
            )
            self.assertEqual(
                fixture["generated_input_sha256"],
                runtime[capability_id]["generated_input_sha256"],
            )
            self.assertEqual(
                rows[capability_id]["fixture"]["materialization"]["sha256"], raw_sha
            )
            self.assertNotEqual(raw_sha, fixture["generated_input_sha256"])

    def test_undeclared_target_mutation_fails_closed(self) -> None:
        source, derived, fixtures = compiler.derive()
        mutated = copy.deepcopy(derived)
        target = next(
            row
            for row in mutated["oracles"]
            if row["capability_id"] == compiler.TARGETS[0][0]
        )
        target["mode"] = "runtime"
        schema = compiler.load_locked(compiler.ORACLE_SCHEMA)
        with self.assertRaisesRegex(compiler.SuccessorError, "undeclared change"):
            compiler.validate(source, mutated, schema, fixtures)


if __name__ == "__main__":
    unittest.main()
