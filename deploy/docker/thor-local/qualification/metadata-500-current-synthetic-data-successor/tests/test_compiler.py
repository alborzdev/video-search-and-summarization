from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest


PACKAGE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "synthetic_data_oracle_successor", PACKAGE / "compiler.py"
)
assert SPEC is not None and SPEC.loader is not None
compiler = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compiler)

PARITY = compiler.REPO_ROOT / "deploy/docker/thor-local/parity"
sys.path.insert(0, str(PARITY))
VERIFIER_SPEC = importlib.util.spec_from_file_location(
    "synthetic_data_official_verifier", PARITY / "verify_official_capabilities.py"
)
assert VERIFIER_SPEC is not None and VERIFIER_SPEC.loader is not None
verifier = importlib.util.module_from_spec(VERIFIER_SPEC)
VERIFIER_SPEC.loader.exec_module(verifier)


class SyntheticDataOracleSuccessorTests(unittest.TestCase):
    def test_checked_output_is_exact_derivation(self) -> None:
        _, derived, _ = compiler.derive()
        payload = compiler.encoded(derived)
        checked = (PACKAGE / "post-state-capability-oracles.json").read_bytes()
        self.assertEqual(checked, payload)
        self.assertEqual(
            hashlib.sha256(checked).hexdigest(), compiler.EXPECTED_OUTPUT_SHA256
        )

    def test_promoted_root_oracle_prefix_requires_no_additional_change(self) -> None:
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
        self.assertEqual(changed, set())
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

    def test_checked_promotion_outputs_are_exact_derivation(self) -> None:
        ledger, manifest, receipts, oracles = compiler.derive_promotion()
        checked = {
            compiler.LEDGER_OUTPUT: (
                compiler.encoded(ledger),
                compiler.EXPECTED_LEDGER_SHA256,
            ),
            compiler.MANIFEST_OUTPUT: (
                compiler.encoded(manifest),
                compiler.EXPECTED_MANIFEST_SHA256,
            ),
        }
        for path, (payload, expected_sha) in checked.items():
            self.assertEqual(path.read_bytes(), payload)
            self.assertEqual(hashlib.sha256(payload).hexdigest(), expected_sha)
        ledger_rows = {row["id"]: row for row in ledger["capabilities"]}
        oracle_rows = {row["capability_id"]: row for row in oracles["oracles"]}
        for capability_id, receipt in receipts.items():
            path = compiler.REPO_ROOT / compiler.receipt_relative(capability_id)
            payload = compiler.encoded(receipt)
            self.assertEqual(path.read_bytes(), payload)
            self.assertEqual(
                hashlib.sha256(payload).hexdigest(),
                compiler.EXPECTED_RECEIPT_SHA256[capability_id],
            )
            verifier._validate_bound_runtime_evidence(
                ledger_rows[capability_id],
                oracle_rows[capability_id],
                receipt,
                ledger["target"],
            )

    def test_aggregate_cleanup_and_confinement_fail_closed(self) -> None:
        _, oracles, fixtures = compiler.derive()
        oracle_rows = {row["capability_id"]: row for row in oracles["oracles"]}
        contract = compiler.load_locked(compiler.RUNTIME_CONTRACT)
        schema = compiler.load_locked(compiler.RUNTIME_RESULT_SCHEMA)
        aggregate = compiler.load_locked(compiler.AGGREGATE_RECEIPT)
        aggregate["cleanup"]["root_removed"] = False
        with self.assertRaisesRegex(compiler.SuccessorError, "cleanup envelope"):
            compiler.validate_aggregate(
                aggregate, schema, contract, oracle_rows, fixtures
            )
        aggregate = compiler.load_locked(compiler.AGGREGATE_RECEIPT)
        aggregate["confinement"]["network_calls"] = 1
        with self.assertRaisesRegex(compiler.SuccessorError, "zero-confinement"):
            compiler.validate_aggregate(
                aggregate, schema, contract, oracle_rows, fixtures
            )

    def test_receipt_observations_bind_aggregate_and_result(self) -> None:
        _, _, receipts, _ = compiler.derive_promotion()
        aggregate = compiler.load_locked(compiler.AGGREGATE_RECEIPT)
        results = {row["capability_id"]: row for row in aggregate["capability_results"]}
        for capability_id, receipt in receipts.items():
            expected_result_sha = compiler.sha256(
                compiler.canonical_bytes(results[capability_id])
            )
            for observation in receipt["observations"]:
                self.assertEqual(
                    observation["value"]["aggregate_receipt_sha256"],
                    compiler.AGGREGATE_SHA256,
                )
                self.assertEqual(
                    observation["value"]["capability_result_sha256"],
                    expected_result_sha,
                )

    def test_only_synthetic_ledger_rows_and_manifest_family_change(self) -> None:
        ledger, manifest, receipts, oracles = compiler.derive_promotion()
        counts = compiler.validate_promotion(
            compiler._ledger_baseline(),
            ledger,
            compiler.load_locked(compiler.SELECTED_MANIFEST),
            manifest,
            receipts,
            oracles,
            compiler.load_locked(compiler.OFFICIAL_SCHEMA),
        )
        self.assertEqual(counts["preserved_ledger_rows"], 496)
        self.assertEqual(counts["preserved_manifest_features"], 54)
        self.assertEqual(counts["selected_suffix"], 211)
        self.assertEqual(counts["official_receipts"], 4)


if __name__ == "__main__":
    unittest.main()
