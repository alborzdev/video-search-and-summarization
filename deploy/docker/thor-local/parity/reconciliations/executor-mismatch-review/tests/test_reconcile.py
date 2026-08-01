from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


LANE = Path(__file__).resolve().parents[1]
MODULE_PATH = LANE / "reconcile.py"
SPEC = importlib.util.spec_from_file_location("executor_mismatch_reconcile", MODULE_PATH)
assert SPEC and SPEC.loader
RECONCILE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = RECONCILE
SPEC.loader.exec_module(RECONCILE)


class ReconciliationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.descriptor = RECONCILE.load_descriptor()
        cls.live_path = (
            RECONCILE.REPO_ROOT / cls.descriptor["ledger"]["path"]
        )
        cls.output_payload = cls.live_path.read_bytes()
        cls.baseline_payload = RECONCILE.derive_baseline_bytes(
            cls.output_payload, cls.descriptor
        )

    def test_live_output_is_exact_deterministic_rebuild(self) -> None:
        report = RECONCILE.validate_live()
        self.assertEqual(report["added_discrepancies"], 2)
        self.assertEqual(report["output_discrepancy_count"], 47)
        self.assertEqual(report["reviewed_evidence_count"], 9)
        self.assertEqual(
            RECONCILE.build_bytes(self.baseline_payload, self.descriptor),
            self.output_payload,
        )

    def test_only_two_discrepancy_records_change(self) -> None:
        baseline = RECONCILE.strict_loads(self.baseline_payload, "baseline")
        output = RECONCILE.strict_loads(self.output_payload, "output")
        added = output["source_discrepancies"][-2:]
        self.assertEqual(added, self.descriptor["records"])
        del output["source_discrepancies"][-2:]
        self.assertEqual(output, baseline)
        self.assertEqual(
            {item["classification"] for item in self.descriptor["decisions"]},
            {
                "official_documentation_to_repository_name_discrepancy",
                "explicit_unqualified_thor_override",
            },
        )

    def test_partial_record_application_fails_closed(self) -> None:
        partial = RECONCILE.strict_loads(self.baseline_payload, "baseline")
        partial["source_discrepancies"].append(
            copy.deepcopy(self.descriptor["records"][0])
        )
        with self.assertRaises(RECONCILE.ReconciliationError):
            RECONCILE.validate_payload(
                RECONCILE.encoded(partial), self.descriptor
            )

    def test_record_or_order_tamper_fails_closed(self) -> None:
        tampered = RECONCILE.strict_loads(self.output_payload, "output")
        tampered["source_discrepancies"][-1]["resolution"] = "weakened"
        with self.assertRaises(RECONCILE.ReconciliationError):
            RECONCILE.validate_payload(
                RECONCILE.encoded(tampered), self.descriptor
            )
        reordered = RECONCILE.strict_loads(self.output_payload, "output")
        reordered["source_discrepancies"][-2:] = reversed(
            reordered["source_discrepancies"][-2:]
        )
        with self.assertRaises(RECONCILE.ReconciliationError):
            RECONCILE.validate_payload(
                RECONCILE.encoded(reordered), self.descriptor
            )

    def test_descriptor_co_tamper_fails_canonical_pin(self) -> None:
        altered = copy.deepcopy(self.descriptor)
        altered["records"][0]["must_not_claim"] = "weakened"
        with self.assertRaisesRegex(
            RECONCILE.ReconciliationError, "descriptor canonical digest drift"
        ):
            RECONCILE.load_descriptor(RECONCILE.encoded(altered))

    def test_reviewed_evidence_drift_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            root = Path(temporary_name)
            for item in self.descriptor["reviewed_evidence"]:
                target = root / item["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                source = RECONCILE.REPO_ROOT / item["path"]
                target.write_bytes(source.read_bytes())
            first = root / self.descriptor["reviewed_evidence"][0]["path"]
            first.write_bytes(first.read_bytes() + b"\n")
            with self.assertRaisesRegex(
                RECONCILE.ReconciliationError, "reviewed evidence drift"
            ):
                RECONCILE.verify_evidence(self.descriptor, root)

    def test_duplicate_json_keys_fail_closed(self) -> None:
        with self.assertRaisesRegex(
            RECONCILE.ReconciliationError, "duplicate JSON key"
        ):
            RECONCILE.strict_loads(b'{"a":1,"a":2}', "test")


if __name__ == "__main__":
    unittest.main()
