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
SPEC = importlib.util.spec_from_file_location("executor_live_integration_tests", MODULE_PATH)
assert SPEC and SPEC.loader
INTEGRATION = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = INTEGRATION
SPEC.loader.exec_module(INTEGRATION)


class LiveIntegrationTests(unittest.TestCase):
    def test_exact_combined_successor_state_validates(self) -> None:
        report = INTEGRATION.validate_live()
        self.assertEqual(report["materialized_planning_requirements"], 10)
        self.assertEqual(report["executor_ready_planning_requirements"], 10)
        self.assertEqual(report["planning_index_only_oracles"], 276)
        self.assertEqual(report["full_executor_ready_oracles"], 0)
        self.assertEqual(report["runtime_evidence_records"], 0)
        self.assertEqual(report["observed_match"], 8)
        self.assertEqual(report["observed_mismatch"], 2)

    def test_historical_wave3_receipt_is_byte_exact_and_immutable(self) -> None:
        wave3 = INTEGRATION._module("test_wave3_receipt_replay", INTEGRATION.WAVE3_MERGE)
        expected = wave3.build_unmerged(from_baseline=True)[-1]
        observed = INTEGRATION.WAVE3_RECEIPT.read_bytes()
        self.assertEqual(observed, INTEGRATION.encoded(expected))
        self.assertEqual(
            hashlib.sha256(observed).hexdigest(),
            "7bbefa6fdc0cd8223b0aafdace181526ef5ef5f5fcff17dc192d2d2dbb6eeb5c",
        )

    def test_acceptance_output_and_receipt_co_tamper_is_rejected(self) -> None:
        ledger, manifest, acceptance, oracles, receipt = INTEGRATION.build_expected()
        acceptance = copy.deepcopy(acceptance)
        target = next(
            item
            for item in acceptance["wave3_contracts"]["planning_requirements"]
            if item.get("static_executor_binding")
        )
        target["runtime_evidence"] = ["fabricated-runtime-pass"]
        receipt = copy.deepcopy(receipt)
        receipt["outputs"]["acceptance_inventory.json"] = INTEGRATION.raw_sha256(
            INTEGRATION.encoded(acceptance)
        )
        with self._TemporaryLivePaths(
            ledger, manifest, acceptance, oracles, receipt
        ):
            with self.assertRaisesRegex(
                INTEGRATION.IntegrationError,
                "receipt differs|partial or drifted",
            ):
                INTEGRATION.validate_live(execute=False)

    def test_oracle_output_and_receipt_co_tamper_is_rejected(self) -> None:
        ledger, manifest, acceptance, oracles, receipt = INTEGRATION.build_expected()
        oracles = copy.deepcopy(oracles)
        target = next(
            item for item in oracles["oracles"] if item.get("planning_executor_bindings")
        )
        target["planning_executor_bindings"][0]["runtime_evidence"] = [
            "fabricated-runtime-pass"
        ]
        receipt = copy.deepcopy(receipt)
        receipt["outputs"]["capability-oracles.json"] = INTEGRATION.raw_sha256(
            INTEGRATION.encoded(oracles)
        )
        with self._TemporaryLivePaths(
            ledger, manifest, acceptance, oracles, receipt
        ):
            with self.assertRaisesRegex(
                INTEGRATION.IntegrationError,
                "receipt differs|partial or drifted",
            ):
                INTEGRATION.validate_live(execute=False)

    def test_schema_and_receipt_co_tamper_is_rejected_by_code_lock(self) -> None:
        _, _, _, _, receipt = INTEGRATION.build_expected()
        with tempfile.TemporaryDirectory() as temporary_name:
            schema = Path(temporary_name) / "capability-oracles.schema.json"
            payload = json.loads(INTEGRATION.ORACLE_SCHEMA.read_text(encoding="utf-8"))
            payload["title"] += " tampered"
            schema.write_bytes(INTEGRATION.encoded(payload))
            receipt = copy.deepcopy(receipt)
            receipt["outputs"]["capability-oracles.schema.json"] = hashlib.sha256(
                schema.read_bytes()
            ).hexdigest()
            original_schema = INTEGRATION.ORACLE_SCHEMA
            INTEGRATION.ORACLE_SCHEMA = schema
            try:
                with self.assertRaisesRegex(
                    INTEGRATION.IntegrationError,
                    "reviewed capability oracle schema digest drift",
                ):
                    INTEGRATION.build_expected(execute=False)
            finally:
                INTEGRATION.ORACLE_SCHEMA = original_schema

    class _TemporaryLivePaths:
        def __init__(
            self,
            ledger: dict,
            manifest: dict,
            acceptance: dict,
            oracles: dict,
            receipt: dict,
        ) -> None:
            self.values = (ledger, manifest, acceptance, oracles, receipt)

        def __enter__(self) -> None:
            self.temporary = tempfile.TemporaryDirectory()
            root = Path(self.temporary.name)
            names = ("ledger.json", "manifest.json", "acceptance.json", "oracles.json", "receipt.json")
            self.paths = [root / name for name in names]
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
