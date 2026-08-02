import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest

from jsonschema import Draft202012Validator


LANE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "source_claim_hash_repair_successor", LANE / "integrate_live.py"
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class SourceClaimHashRepairSuccessorTests(unittest.TestCase):
    def test_exact_six_leaf_allowlist(self):
        predecessor, successor, before, after = MODULE._transition()
        self.assertEqual(MODULE._sha256(predecessor), MODULE.PREDECESSOR_OFFICIAL_SHA256)
        self.assertEqual(MODULE._sha256(successor), MODULE.FINAL_OFFICIAL_SHA256)
        self.assertEqual(
            sorted(MODULE._leaf_diffs(before, after)),
            sorted(
                f"/sources/{row['index']}/claim_set_sha256"
                for row in MODULE.SOURCE_HASH_TRANSITIONS
            ),
        )

    def test_capabilities_are_byte_semantically_identical(self):
        _predecessor, _successor, before, after = MODULE._transition()
        self.assertEqual(before["capabilities"], after["capabilities"])

    def test_only_hash_leaf_changes_inside_each_allowlisted_source(self):
        _predecessor, _successor, before, after = MODULE._transition()
        for row in MODULE.SOURCE_HASH_TRANSITIONS:
            old_source = copy.deepcopy(before["sources"][row["index"]])
            new_source = copy.deepcopy(after["sources"][row["index"]])
            self.assertEqual(old_source["id"], row["source_id"])
            self.assertEqual(new_source["id"], row["source_id"])
            self.assertEqual(old_source.pop("claim_set_sha256"), row["old"])
            self.assertEqual(new_source.pop("claim_set_sha256"), row["new"])
            self.assertEqual(old_source, new_source)

    def test_all_successor_source_hashes_are_verifier_derived(self):
        _predecessor, _successor, _before, after = MODULE._transition()
        derived = MODULE._derived_claim_hashes(after)
        self.assertTrue(
            all(
                source["claim_set_sha256"] == derived[source["id"]]
                for source in after["sources"]
            )
        )

    def test_receipt_schema_and_contract_digest(self):
        _successor, receipt = MODULE.build_expected()
        schema = json.loads(MODULE.RECEIPT_SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        errors = list(Draft202012Validator(schema).iter_errors(receipt))
        self.assertEqual(errors, [])
        core = {
            key: value
            for key, value in receipt.items()
            if key not in {"contract_sha256", "lifecycle"}
        }
        self.assertEqual(receipt["contract_sha256"], MODULE._canonical_sha256(core))

    def test_preserved_aggregates_and_zero_advancement(self):
        _successor, receipt = MODULE.build_expected()
        self.assertEqual(
            {row["path"]: row["raw_sha256"] for row in receipt["preserved_aggregates"]},
            MODULE.PRESERVED_RAW_SHA256,
        )
        self.assertFalse(receipt["boundaries"]["oracles_written"])
        self.assertFalse(receipt["boundaries"]["runtime_evidence_added"])
        self.assertFalse(receipt["boundaries"]["passed_current_allowed"])
        self.assertEqual(receipt["boundaries"]["warehouse_sample_bundle"], "excluded")

    def test_review_and_rollback_are_read_only_and_exact(self):
        review = MODULE.review()
        rollback = MODULE.rollback_plan()
        self.assertFalse(review["writes_performed"])
        self.assertFalse(rollback["writes_performed"])
        self.assertEqual(review["semantic_leaf_change_count"], 6)
        self.assertTrue(rollback["matches_locked_predecessor"])
        self.assertEqual(rollback["rollback_raw_sha256"], MODULE.PREDECESSOR_OFFICIAL_SHA256)

    def test_live_validation(self):
        result = MODULE.validate()
        self.assertEqual(result["semantic_leaf_change_count"], 6)
        self.assertFalse(result["capabilities_changed"])
        self.assertFalse(result["oracles_written"])
        self.assertEqual(result["runtime_evidence_records"], 0)
        self.assertEqual(result["passed_current_promotions"], 0)


if __name__ == "__main__":
    unittest.main()
