import copy
import importlib.util
from pathlib import Path
import sys
import unittest


LANE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "alerts_current_contract_successor", LANE / "integrate_live.py"
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class AlertsCurrentContractSuccessorTests(unittest.TestCase):
    def test_exact_twelve_leaf_semantic_delta(self):
        outputs, receipt = MODULE.build_expected()
        self.assertEqual(receipt["delta"]["semantic_leaf_change_count"], 12)
        observed = []
        for relative in outputs:
            predecessor, successor, before, after = MODULE._transition(relative)
            self.assertEqual(
                MODULE._sha256(predecessor), MODULE.PREDECESSOR_RAW_SHA256[relative]
            )
            self.assertEqual(successor, outputs[relative])
            observed.extend(MODULE._leaf_diffs(before, after))
        self.assertEqual(len(observed), 12)

    def test_unrelated_records_and_lvs_contracts_are_identical(self):
        for relative in MODULE.TARGETS:
            _predecessor, _successor, before, after = MODULE._transition(relative)
            if "official-capabilities" in relative:
                old_alert = before["capabilities"][118]
                new_alert = after["capabilities"][118]
                stripped_old = copy.deepcopy(old_alert)
                stripped_new = copy.deepcopy(new_alert)
                for key in ("expected_manifest_sha256", "operation_count"):
                    stripped_old["contract"].pop(key)
                    stripped_new["contract"].pop(key)
                self.assertEqual(stripped_old, stripped_new)
                old_lvs = [
                    row
                    for row in before["capabilities"]
                    if row.get("id") in {"api.core.lvs-17", "api.core.lvs-mcp-doc-13-repo-9"}
                ]
                new_lvs = [
                    row
                    for row in after["capabilities"]
                    if row.get("id") in {"api.core.lvs-17", "api.core.lvs-mcp-doc-13-repo-9"}
                ]
                self.assertEqual(old_lvs, new_lvs)

    def test_review_and_rollback_plan_are_read_only_and_exact(self):
        review = MODULE.review()
        rollback = MODULE.rollback_plan()
        self.assertFalse(review["writes_performed"])
        self.assertFalse(rollback["writes_performed"])
        self.assertEqual(review["semantic_leaf_change_count"], 12)
        self.assertTrue(all(row["matches_locked_predecessor"] for row in rollback["targets"]))

    def test_manifest_and_acceptance_are_locked_but_not_write_targets(self):
        review_paths = {row["path"] for row in MODULE.review()["write_targets"]}
        self.assertNotIn("deploy/docker/thor-local/parity/manifest.json", review_paths)
        self.assertNotIn(
            "deploy/docker/thor-local/qualification/acceptance_inventory.json",
            review_paths,
        )
        self.assertEqual(
            MODULE._sha256(MODULE._regular_bytes(MODULE.MANIFEST)),
            MODULE.PREDECESSOR_RAW_SHA256[
                "deploy/docker/thor-local/parity/manifest.json"
            ],
        )

    def test_live_validation(self):
        result = MODULE.validate()
        self.assertEqual(result["semantic_leaf_change_count"], 12)
        self.assertEqual(result["runtime_evidence_records"], 0)
        self.assertEqual(result["passed_current_promotions"], 0)

    def test_alerts_contract_and_workload_are_bound_to_twenty_one_operations(self):
        outputs, _receipt = MODULE.build_expected()
        ledger = MODULE._strict_json_bytes(
            outputs["deploy/docker/thor-local/parity/official-capabilities.json"],
            "official successor",
        )
        oracles = MODULE._strict_json_bytes(
            outputs["deploy/docker/thor-local/parity/capability-oracles.json"],
            "oracle successor",
        )
        capability = ledger["capabilities"][118]
        oracle = oracles["oracles"][118]
        self.assertEqual(capability["id"], "api.core.alerts-19")
        self.assertEqual(capability["contract"]["operation_count"], 21)
        self.assertEqual(oracle["ledger_binding"]["contract"]["operation_count"], 21)
        self.assertEqual(oracle["fixture"]["input"]["contract"]["operation_count"], 21)
        self.assertEqual(oracle["assertions"][4]["expected"], 21)
        self.assertEqual(oracle["execution_bounds"]["workload"]["units"], 21)
        self.assertEqual(
            oracle["execution_bounds"]["workload"]["calculated_max_requests"], 85
        )
        self.assertEqual(oracle["execution_bounds"]["max_requests"], 85)
        self.assertEqual(oracle["execution_bounds"]["max_actions"], 85)


if __name__ == "__main__":
    unittest.main()
