from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


LANE = Path(__file__).resolve().parents[1]
MODULE_PATH = LANE / "integrate_live.py"
SPEC = importlib.util.spec_from_file_location(
    "source_contract_successor_tests", MODULE_PATH
)
assert SPEC and SPEC.loader
INTEGRATION = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = INTEGRATION
SPEC.loader.exec_module(INTEGRATION)


class SecondSuccessorTests(unittest.TestCase):
    def test_exact_current_successor_validates(self) -> None:
        report = INTEGRATION.validate_live()
        self.assertEqual(report["planning_requirements"], 110)
        self.assertEqual(report["materialized_planning_requirements"], 26)
        self.assertEqual(report["executor_ready_planning_requirements"], 26)
        self.assertEqual(report["open_planning_requirements"], 84)
        self.assertEqual(report["planning_index_only_oracles"], 276)
        self.assertEqual(report["static_subset_oracle_bindings"], 26)
        self.assertEqual(report["full_executor_ready_oracles"], 0)
        self.assertEqual(report["runtime_evidence_records"], 0)
        self.assertEqual(report["passed_current_promotions"], 0)
        self.assertEqual(report["new_observed_match"], 15)
        self.assertEqual(report["new_observed_mismatch"], 1)
        self.assertEqual(report["cumulative_observed_match"], 23)
        self.assertEqual(report["cumulative_observed_mismatch"], 3)

    def test_predecessor_receipt_is_byte_exact_and_replayed(self) -> None:
        observed = INTEGRATION.PREDECESSOR_RECEIPT.read_bytes()
        self.assertEqual(
            hashlib.sha256(observed).hexdigest(),
            INTEGRATION.PREDECESSOR_RECEIPT_RAW_SHA256,
        )
        receipt = json.loads(observed)
        self.assertEqual(
            INTEGRATION.canonical_sha256(receipt),
            INTEGRATION.PREDECESSOR_RECEIPT_CANONICAL_SHA256,
        )
        report = INTEGRATION.validate_predecessor()
        self.assertEqual(report["materialized_planning_requirements"], 10)
        self.assertEqual(report["executor_ready_planning_requirements"], 10)
        self.assertEqual(report["runtime_evidence_records"], 0)

    def test_all_sixteen_cases_execute_against_reconstructed_predecessor(self) -> None:
        ledger, _manifest, acceptance, _oracles, _receipt = (
            INTEGRATION._predecessor()
        )
        contract = INTEGRATION._module(
            "test_source_contract_predecessor_execution", INTEGRATION.LIVE_CONTRACT
        )
        bindings = contract.build_bindings(acceptance, ledger, execute=True)
        self.assertEqual(len(bindings), 16)
        outcomes = [item["result"]["expected_outcome"] for item in bindings.values()]
        self.assertEqual(outcomes.count("observed_match"), 15)
        self.assertEqual(outcomes.count("observed_mismatch"), 1)
        self.assertTrue(
            all(item["result"]["runtime_evidence"] == [] for item in bindings.values())
        )

    def test_live_state_has_only_bounded_static_subset_bindings(self) -> None:
        ledger, _manifest, acceptance, oracles, _receipt = (
            INTEGRATION.build_expected(execute=False)
        )
        requirements = acceptance["wave3_contracts"]["planning_requirements"]
        ready = [item for item in requirements if item["materialized"]]
        self.assertEqual(len(ready), 26)
        self.assertEqual(sum(not item["materialized"] for item in requirements), 84)
        self.assertTrue(all(item["runtime_evidence"] == [] for item in requirements))
        self.assertFalse(any(row["runtime_state"] == "passed_current" for row in ledger["capabilities"] if row["id"] in {item["owner_id"] for item in ready}))
        rows = oracles["oracles"]
        self.assertEqual(len(rows), 276)
        self.assertTrue(
            all(
                row["acceptance_readiness"]["classification"]
                == "planning_index_only"
                for row in rows
            )
        )
        self.assertTrue(all(row.get("executor") is None for row in rows))
        bindings = [
            binding
            for row in rows
            for binding in row.get("planning_executor_bindings", [])
        ]
        self.assertEqual(len(bindings), 26)
        self.assertTrue(all(binding["runtime_evidence"] == [] for binding in bindings))

    def test_acceptance_and_receipt_co_tamper_is_rejected(self) -> None:
        ledger, manifest, acceptance, oracles, receipt = INTEGRATION.build_expected(
            execute=False
        )
        acceptance = copy.deepcopy(acceptance)
        target = next(
            item
            for item in acceptance["wave3_contracts"]["planning_requirements"]
            if item["materialized"]
        )
        target["runtime_evidence"] = ["fabricated-runtime-pass"]
        receipt = copy.deepcopy(receipt)
        receipt["outputs"]["acceptance_inventory.json"] = INTEGRATION.raw_sha256(
            INTEGRATION.encoded(acceptance)
        )
        with self._temporary_live_paths(
            ledger, manifest, acceptance, oracles, receipt
        ):
            with self.assertRaisesRegex(
                INTEGRATION.IntegrationError, "receipt differs|partial or drifted"
            ):
                INTEGRATION.validate_live(execute=False)

    class _temporary_live_paths:
        def __init__(
            self,
            ledger: dict,
            manifest: dict,
            acceptance: dict,
            oracles: dict,
            receipt: dict,
        ) -> None:
            self.values = ledger, manifest, acceptance, oracles, receipt

        def __enter__(self) -> None:
            self.temporary = tempfile.TemporaryDirectory()
            root = Path(self.temporary.name)
            self.paths = [root / name for name in ("ledger", "manifest", "acceptance", "oracles", "receipt")]
            for path, value in zip(self.paths, self.values, strict=True):
                path.write_bytes(INTEGRATION.encoded(value))
            self.original = (
                INTEGRATION.LEDGER,
                INTEGRATION.MANIFEST,
                INTEGRATION.ACCEPTANCE,
                INTEGRATION.ORACLES,
                INTEGRATION.RECEIPT,
            )
            (
                INTEGRATION.LEDGER,
                INTEGRATION.MANIFEST,
                INTEGRATION.ACCEPTANCE,
                INTEGRATION.ORACLES,
                INTEGRATION.RECEIPT,
            ) = self.paths

        def __exit__(self, *_args: object) -> None:
            (
                INTEGRATION.LEDGER,
                INTEGRATION.MANIFEST,
                INTEGRATION.ACCEPTANCE,
                INTEGRATION.ORACLES,
                INTEGRATION.RECEIPT,
            ) = self.original
            self.temporary.cleanup()


if __name__ == "__main__":
    unittest.main()
