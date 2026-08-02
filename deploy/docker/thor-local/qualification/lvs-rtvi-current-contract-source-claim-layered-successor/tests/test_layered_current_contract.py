import importlib.util
import json
from pathlib import Path
import sys
import unittest

from jsonschema import Draft202012Validator


LANE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "lvs_rtvi_layered_contract", LANE / "compiler.py"
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class LayeredCurrentContractTests(unittest.TestCase):
    def test_exact_three_current_records(self):
        artifact = MODULE.build_expected()
        self.assertEqual(
            [row["capability_id"] for row in artifact["changed_records"]],
            [
                "api.core.rt-vlm-27",
                "api.core.lvs-17",
                "api.core.lvs-mcp-doc-13-repo-9",
            ],
        )
        self.assertEqual(artifact["summary"]["changed_capability_records"], 3)
        self.assertEqual(artifact["summary"]["changed_oracle_records"], 3)

    def test_exact_semantic_allowlists(self):
        artifact = MODULE.build_expected()
        transitions = {row["path"]: row for row in artifact["transitions"]}
        self.assertEqual(
            transitions[MODULE.OFFICIAL]["semantic_pointers"],
            sorted(MODULE.OFFICIAL_CHANGES),
        )
        self.assertEqual(
            transitions[MODULE.ORACLES]["semantic_pointers"],
            sorted(MODULE.ORACLE_CHANGES),
        )
        self.assertEqual(transitions[MODULE.OFFICIAL]["semantic_leaf_count"], 11)
        self.assertEqual(transitions[MODULE.ORACLES]["semantic_leaf_count"], 21)

    def test_prior_alerts_and_source_claim_layers_are_bound(self):
        artifact = MODULE.build_expected()
        predecessor = artifact["predecessor_layers"]
        self.assertEqual(
            predecessor["official_raw_sha256"],
            MODULE.PREDECESSOR_HASHES[MODULE.OFFICIAL],
        )
        self.assertEqual(
            predecessor["oracles_raw_sha256"], MODULE.PREDECESSOR_HASHES[MODULE.ORACLES]
        )
        self.assertEqual(
            predecessor["source_claim_receipt_raw_sha256"],
            MODULE.PRIOR_LAYER_HASHES[MODULE.SOURCE_RECEIPT],
        )
        self.assertEqual(
            predecessor["alerts_receipt_raw_sha256"],
            MODULE.PRIOR_LAYER_HASHES[MODULE.ALERTS_RECEIPT],
        )

    def test_current_contract_counts_and_exact_abort_route(self):
        artifact = MODULE.build_expected()
        self.assertEqual(artifact["summary"]["rt_vlm_operation_count"], 28)
        self.assertEqual(artifact["summary"]["lvs_operation_count"], 18)
        self.assertEqual(artifact["summary"]["lvs_mcp_tool_count"], 13)
        rt = MODULE.strict_json(
            MODULE.regular_bytes(
                "deploy/docker/thor-local/qualification/expected/rt-vlm.json"
            ),
            "RT-VLM expected manifest",
        )
        self.assertIn(
            ("DELETE", "/v1/generate_captions/requests/{request_id}"),
            {(row["method"], row["path"]) for row in rt["operations"]},
        )

    def test_all_source_claim_hashes_are_derived(self):
        _predecessor, official = MODULE.transition(MODULE.OFFICIAL)
        derived = MODULE.derived_claim_hashes(official)
        self.assertTrue(
            all(
                source["claim_set_sha256"] == derived[source["id"]]
                for source in official["sources"]
            )
        )

    def test_schema_and_checked_artifact(self):
        expected = MODULE.build_expected()
        observed = json.loads(MODULE.ARTIFACT.read_text(encoding="utf-8"))
        schema = json.loads(MODULE.SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        self.assertEqual(list(Draft202012Validator(schema).iter_errors(observed)), [])
        self.assertEqual(observed, expected)

    def test_zero_advancement_and_warehouse_exclusion(self):
        artifact = MODULE.build_expected()
        self.assertFalse(artifact["policy"]["runtime_evidence_added"])
        self.assertEqual(artifact["policy"]["passed_current_promotions"], 0)
        self.assertEqual(artifact["policy"]["warehouse_sample_bundle"], "excluded")
        self.assertFalse(artifact["policy"]["network_allowed"])
        self.assertFalse(artifact["policy"]["docker_allowed"])
        self.assertFalse(artifact["policy"]["services_allowed"])

    def test_live_validation_and_read_only_rollback_plan(self):
        result = MODULE.validate()
        rollback = MODULE.rollback_plan()
        self.assertEqual(result["status"], "valid")
        self.assertFalse(result["writes_performed"])
        self.assertEqual(result["runtime_evidence_records"], 0)
        self.assertFalse(rollback["writes_performed"])
        self.assertEqual(rollback["semantic_leaf_count"], 32)


if __name__ == "__main__":
    unittest.main()
