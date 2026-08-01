import copy
import importlib.util
from pathlib import Path
import sys
import unittest


HERE = Path(__file__).resolve().parent
INTEGRATOR = HERE.parent / "integrate_live.py"
SPEC = importlib.util.spec_from_file_location("lvs_mcp_static_adapter_integration", INTEGRATOR)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class StaticAdapterIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger, cls.manifest, cls.acceptance, cls.oracles, cls.receipt = (
            MODULE.build_expected()
        )

    def test_exact_local_and_upstream_tool_contracts(self):
        capability = MODULE._by_id(
            self.ledger["capabilities"], "api.core.lvs-mcp-doc-13-repo-9"
        )
        self.assertEqual(capability["thor_state"], "wired")
        self.assertEqual(capability["runtime_state"], "static_only")
        self.assertEqual(capability["contract"]["repository_tool_count"], 13)
        self.assertEqual(capability["contract"]["upstream_repository_tool_count"], 9)
        self.assertEqual(
            capability["contract"]["thor_local_adapter_tools"], MODULE.ADAPTER_TOOLS
        )

    def test_upstream_discrepancy_and_runtime_boundary_remain_explicit(self):
        discrepancy = MODULE._by_id(
            self.ledger["source_discrepancies"],
            "lvs-mcp-doc-13-vs-repository-9",
        )
        self.assertIn("pinned upstream repository", discrepancy["resolution"])
        self.assertIn("live file lifecycle", discrepancy["must_not_claim"])
        self.assertEqual(self.receipt["expected_counts"]["runtime_evidence_records"], 0)
        self.assertEqual(self.receipt["expected_counts"]["passed_current_promotions"], 0)

    def test_historical_planning_contracts_are_byte_semantically_unchanged(self):
        predecessor = MODULE._historical_predecessor()
        self.assertEqual(
            self.acceptance["wave3_contracts"], predecessor[2]["wave3_contracts"]
        )
        self.assertEqual(self.receipt["predecessor"]["outputs"], MODULE.PREDECESSOR_OUTPUTS)

    def test_oracles_remain_planning_only(self):
        self.assertEqual(len(self.oracles["oracles"]), 276)
        self.assertTrue(
            all(
                row["acceptance_readiness"]["classification"] == "planning_index_only"
                for row in self.oracles["oracles"]
            )
        )
        offline = {
            row["capability_id"]: row["offline_tool_observation_bindings"][0]
            for row in self.oracles["oracles"]
            if row.get("offline_tool_observation_bindings")
        }
        self.assertEqual(
            set(offline),
            {
                "tool.mv3dt.cam-info-generator",
                "tool.mv3dt.pub-sub-generator",
            },
        )
        self.assertEqual(
            self.receipt["expected_counts"]["static_subset_oracle_bindings"], 28
        )
        self.assertEqual(
            self.receipt["expected_counts"]["offline_tool_observation_bindings"], 2
        )
        self.assertTrue(
            all(binding["can_advance_capability"] is False for binding in offline.values())
        )

    def test_live_validation_is_exact(self):
        result = MODULE.validate_live()
        self.assertEqual(result["lifecycle"], "third_static_adapter_successor_integrated")

    def test_unexpected_predecessor_state_fails_closed(self):
        predecessor = MODULE._historical_predecessor()
        ledger, manifest, acceptance = copy.deepcopy(predecessor[:3])
        capability = MODULE._by_id(
            ledger["capabilities"], "api.core.lvs-mcp-doc-13-repo-9"
        )
        capability["thor_state"] = "wired"
        with self.assertRaisesRegex(MODULE.IntegrationError, "predecessor state drift"):
            MODULE._apply_delta(ledger, manifest, acceptance)


if __name__ == "__main__":
    unittest.main()
