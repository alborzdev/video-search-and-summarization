from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import sys
import unittest

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))
SPEC = importlib.util.spec_from_file_location(
    "mv3dt_projection_for_promotion", PACKAGE / "compiler.py"
)
assert SPEC is not None and SPEC.loader is not None
compiler = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compiler)
import promotion  # noqa: E402


class MV3DTPromotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _, cls.oracle, _ = compiler.derive()
        cls.documents, cls.payloads, cls.counts = promotion.derive(cls.oracle)

    def test_all_checked_outputs_are_exact_derivations(self) -> None:
        destinations = {
            **promotion.OUTPUT_PATHS,
            **{
                f"receipt:{key}": value
                for key, value in promotion.RECEIPT_PATHS.items()
            },
        }
        self.assertEqual(set(destinations), set(self.payloads))
        self.assertEqual(set(destinations), set(promotion.EXPECTED_OUTPUT_SHA256))
        for name, path in destinations.items():
            with self.subTest(name=name):
                self.assertEqual(path.read_bytes(), self.payloads[name])
                self.assertEqual(
                    hashlib.sha256(self.payloads[name]).hexdigest(),
                    promotion.EXPECTED_OUTPUT_SHA256[name],
                )

    def test_exact_two_capabilities_and_one_family_are_promoted(self) -> None:
        rows = {row["id"]: row for row in self.documents["ledger_500"]["capabilities"]}
        refs = [
            rows[capability_id]["runtime_evidence"][0]
            for capability_id in promotion.TARGET_IDS
        ]
        self.assertEqual(self.counts["preserved_ledger_rows"], 498)
        self.assertEqual(self.counts["preserved_manifest_features"], 54)
        self.assertEqual({ref["path"] for ref in refs}, {promotion.AGGREGATE[0]})
        self.assertEqual({ref["sha256"] for ref in refs}, {promotion.AGGREGATE[1]})
        self.assertEqual(
            [ref["capability_id"] for ref in refs], list(promotion.TARGET_IDS)
        )
        self.assertEqual(
            [ref["json_pointer"] for ref in refs],
            ["/capability_results/0", "/capability_results/1"],
        )
        for capability_id in promotion.TARGET_IDS:
            row = rows[capability_id]
            self.assertEqual(
                (row["thor_state"], row["runtime_state"]), ("wired", "passed_current")
            )
            self.assertIs(row["contract"]["wave3_acceptance"]["executor_ready"], False)
            self.assertIs(row["contract"]["wave3_acceptance"]["materialized"], False)

    def test_prefix_suffix_and_schema_handoff_are_exact(self) -> None:
        self.assertEqual(
            self.documents["ledger_500"]["capabilities"][:289],
            self.documents["ledger_289"]["capabilities"],
        )
        selected = promotion.load_locked(promotion.SELECTED_LEDGER)
        self.assertEqual(
            self.documents["ledger_500"]["capabilities"][289:],
            selected["capabilities"][289:],
        )
        self.assertEqual(
            self.payloads["official_schema"],
            (promotion.REPO_ROOT / promotion.OFFICIAL_SCHEMA_PATH).read_bytes(),
        )

    def test_aggregate_tampering_fails_closed(self) -> None:
        aggregate = promotion.load_locked(promotion.AGGREGATE)
        aggregate["capability_results"][0]["runtime_evidence_binding"]["requests"] += 1
        with self.assertRaisesRegex(promotion.PromotionError, "deep aggregate"):
            promotion.validate_aggregate(aggregate, self.oracle)

    def test_dependency_pin_parity_cannot_be_invented(self) -> None:
        aggregate = promotion.load_locked(promotion.AGGREGATE)
        aggregate["promotion"]["dependency_pin_parity_claimed"] = True
        with self.assertRaisesRegex(
            promotion.PromotionError, "deep aggregate|promotion"
        ):
            promotion.validate_aggregate(aggregate, self.oracle)


if __name__ == "__main__":
    unittest.main()
