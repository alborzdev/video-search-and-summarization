from __future__ import annotations

import ast
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

from jsonschema import Draft202012Validator


LANE = Path(__file__).resolve().parents[1]
MODULE_PATH = LANE / "executor.py"
SPEC = importlib.util.spec_from_file_location("executor_cases", MODULE_PATH)
assert SPEC and SPEC.loader
EXECUTOR = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = EXECUTOR
SPEC.loader.exec_module(EXECUTOR)


class ExecutorCaseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.inventory = EXECUTOR.load_and_validate_inventory()
        cls.inventory_schema = json.loads(
            (LANE / "inventory.schema.json").read_text(encoding="utf-8")
        )
        cls.result_schema = json.loads(
            (LANE / "result.schema.json").read_text(encoding="utf-8")
        )

    def test_exact_ten_case_materialized_denominator(self) -> None:
        cases = self.inventory["cases"]
        self.assertEqual(len(cases), 10)
        self.assertEqual(
            {case["case_id"] for case in cases}, EXECUTOR.EXPECTED_CASE_IDS
        )
        self.assertEqual(len({case["planning_requirement_id"] for case in cases}), 10)
        self.assertEqual(len({case["capability_id"] for case in cases}), 10)
        self.assertTrue(all(case["materialized"] for case in cases))
        self.assertTrue(
            all(
                case["materialization_scope"] == "isolated_candidate_only"
                for case in cases
            )
        )
        self.assertTrue(all(case["executor_ready"] for case in cases))

    def test_inventory_assertion_contract_is_canonical_digest_pinned(self) -> None:
        self.assertEqual(
            EXECUTOR._sha_json(self.inventory), EXECUTOR.INVENTORY_CANONICAL_SHA256
        )
        altered = copy.deepcopy(self.inventory)
        altered["cases"][0]["assertions"][0]["expected"].pop()
        self.assertNotEqual(
            EXECUTOR._sha_json(altered), EXECUTOR.INVENTORY_CANONICAL_SHA256
        )

    def test_policy_is_static_only_and_non_advancing(self) -> None:
        policy = self.inventory["policy"]
        self.assertEqual(
            policy["evidence_class"], "deterministic_file_static_evidence_not_runtime"
        )
        self.assertIs(policy["can_advance_capability"], False)
        self.assertIs(policy["can_mark_passed_current"], False)
        self.assertEqual(policy["network"], "forbidden")
        self.assertEqual(policy["docker"], "forbidden")
        self.assertEqual(policy["subprocess"], "forbidden")
        self.assertEqual(policy["environment_mutation"], "forbidden")
        self.assertEqual(policy["warehouse_sample_bundle"], "excluded")

    def test_plan_is_executor_ready_but_cannot_advance_capabilities(self) -> None:
        plan = EXECUTOR.plan(self.inventory)
        self.assertEqual(plan["case_count"], 10)
        self.assertEqual(plan["executor_ready_count"], 10)
        self.assertIs(plan["can_advance_capability"], False)
        self.assertIs(plan["can_mark_passed_current"], False)
        self.assertTrue(all(case["materialized"] for case in plan["cases"]))
        self.assertTrue(
            all(
                case["materialization_scope"] == "isolated_candidate_only"
                for case in plan["cases"]
            )
        )
        self.assertTrue(all(case["executor_ready"] for case in plan["cases"]))

    def test_all_results_are_schema_valid_and_source_stable(self) -> None:
        validator = Draft202012Validator(self.result_schema)
        for case in self.inventory["cases"]:
            with self.subTest(case=case["case_id"]):
                result = EXECUTOR.run_case(self.inventory, case["case_id"])
                self.assertEqual(list(validator.iter_errors(result)), [])
                self.assertEqual(
                    result["source_hashes_before"], result["source_hashes_after"]
                )
                self.assertEqual(result["runtime_evidence"], [])
                self.assertIs(result["can_advance_capability"], False)
                self.assertIs(result["can_mark_passed_current"], False)
                self.assertLessEqual(result["bounds"]["files_read"], EXECUTOR.MAX_FILES)
                self.assertLessEqual(result["bounds"]["bytes_read"], EXECUTOR.MAX_BYTES)

    def test_current_outcomes_are_eight_matches_and_two_honest_mismatches(self) -> None:
        report = EXECUTOR.run_all(self.inventory)
        self.assertEqual(report["candidate_materialized_count"], 10)
        self.assertEqual(report["candidate_executor_ready_count"], 10)
        self.assertEqual(report["live_requirement_materialized_count"], 0)
        self.assertEqual(report["live_requirement_executor_ready_count"], 0)
        self.assertEqual(report["runtime_evidence_count"], 0)
        self.assertEqual(report["can_advance_capability_count"], 0)
        self.assertEqual(report["can_mark_passed_current_count"], 0)
        self.assertEqual(
            report["outcomes"], {"observed_match": 8, "observed_mismatch": 2}
        )
        mismatches = {
            result["case_id"]
            for result in report["results"]
            if result["outcome"] == "observed_mismatch"
        }
        self.assertEqual(
            mismatches,
            {
                "executor-case.nvschema-protobuf-fields",
                "executor-case.alert-warmup-default",
            },
        )

    def test_results_are_deterministic(self) -> None:
        case_id = "executor-case.vios-effective-upload-limit"
        self.assertEqual(
            EXECUTOR.run_case(self.inventory, case_id),
            EXECUTOR.run_case(self.inventory, case_id),
        )

    def test_upload_limit_adapter_computes_minimum(self) -> None:
        result = EXECUTOR.run_case(
            self.inventory, "executor-case.vios-effective-upload-limit"
        )
        observation = result["observations"][-1]
        self.assertEqual(observation["status"], "match")
        self.assertEqual(
            observation["observed"],
            {"nginx_mb": 25600, "nvstreamer_mb": 25600, "effective_mb": 25600},
        )

    def test_proto_mismatch_is_exact_field_name_drift(self) -> None:
        result = EXECUTOR.run_case(
            self.inventory, "executor-case.nvschema-protobuf-fields"
        )
        incident = next(
            item
            for item in result["observations"]
            if item["assertion_id"] == "incident-field-tags"
        )
        self.assertEqual(incident["status"], "mismatch")
        self.assertEqual(incident["expected"]["analytics"], 7)
        self.assertEqual(incident["observed"]["analyticsModule"], 7)
        self.assertNotIn("analytics", incident["observed"])

    def test_warmup_override_is_not_reported_as_official_default(self) -> None:
        result = EXECUTOR.run_case(self.inventory, "executor-case.alert-warmup-default")
        self.assertEqual(result["outcome"], "observed_mismatch")
        assertion = result["observations"][-1]
        self.assertEqual(
            assertion["observed"]["missing"], ['VLM_WARMUP_ENABLED: "true"']
        )

    def test_every_planning_binding_still_has_zero_runtime_evidence(self) -> None:
        planning = json.loads(
            (EXECUTOR.REPO_ROOT / self.inventory["planning_source"]["path"]).read_text(
                encoding="utf-8"
            )
        )
        records = {
            item["id"]: item
            for item in planning["wave3_contracts"]["planning_requirements"]
        }
        self.assertEqual(len(records), 110)
        for case in self.inventory["cases"]:
            record = records[case["planning_requirement_id"]]
            self.assertIs(record["materialized"], False)
            self.assertIs(record["executor_ready"], False)
            self.assertEqual(record["runtime_evidence"], [])

    def test_planning_hash_tamper_fails_closed(self) -> None:
        altered = copy.deepcopy(self.inventory)
        altered["cases"][0]["planning_payload_sha256"] = "0" * 64
        with self.assertRaises(EXECUTOR.ExecutorCaseError):
            EXECUTOR.run_case(altered, altered["cases"][0]["case_id"])

    def test_schema_rejects_runtime_promotion_and_executor_demotion(self) -> None:
        validator = Draft202012Validator(self.inventory_schema)
        promoted = copy.deepcopy(self.inventory)
        promoted["policy"]["can_mark_passed_current"] = True
        self.assertGreater(len(list(validator.iter_errors(promoted))), 0)
        demoted = copy.deepcopy(self.inventory)
        demoted["cases"][0]["executor_ready"] = False
        self.assertGreater(len(list(validator.iter_errors(demoted))), 0)

    def test_executor_ast_has_no_network_process_or_environment_mutation_primitives(
        self,
    ) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertTrue(
            imported.isdisjoint(
                {
                    "asyncio",
                    "docker",
                    "http",
                    "requests",
                    "socket",
                    "subprocess",
                    "urllib",
                }
            )
        )
        self.assertNotIn("os.environ", source)
        self.assertNotIn("os.system", source)
        self.assertNotIn("Popen", source)

    def test_safe_reader_rejects_escape_and_symlink(self) -> None:
        with self.assertRaises(EXECUTOR.ExecutorCaseError):
            EXECUTOR._repo_file("../outside")
        original_root = EXECUTOR.REPO_ROOT
        with tempfile.TemporaryDirectory() as temporary_name:
            root = Path(temporary_name)
            (root / "real").write_text("safe", encoding="utf-8")
            (root / "link").symlink_to(root / "real")
            EXECUTOR.REPO_ROOT = root
            try:
                with self.assertRaises(EXECUTOR.ExecutorCaseError):
                    EXECUTOR._repo_file("link")
            finally:
                EXECUTOR.REPO_ROOT = original_root

    def test_budget_rejects_oversize_and_detects_source_change(self) -> None:
        original_root = EXECUTOR.REPO_ROOT
        with tempfile.TemporaryDirectory() as temporary_name:
            root = Path(temporary_name)
            EXECUTOR.REPO_ROOT = root
            try:
                (root / "large").write_bytes(b"x" * (EXECUTOR.MAX_BYTES + 1))
                with self.assertRaises(EXECUTOR.BoundError):
                    EXECUTOR.Budget().read("large")
                source = root / "source"
                source.write_text("before", encoding="utf-8")
                budget = EXECUTOR.Budget()
                budget.read("source")
                source.write_text("after", encoding="utf-8")
                self.assertNotEqual(budget.hashes, budget.rehash())
            finally:
                EXECUTOR.REPO_ROOT = original_root

    def test_duplicate_json_keys_fail_closed(self) -> None:
        with self.assertRaises(EXECUTOR.ExecutorCaseError):
            EXECUTOR._strict_json(b'{"x":1,"x":2}', "duplicate")

    def test_warehouse_sample_markers_are_absent(self) -> None:
        inventory_text = (LANE / "inventory.json").read_text(encoding="utf-8")
        for marker in EXECUTOR.EXCLUDED_SAMPLE_MARKERS:
            self.assertNotIn(marker, inventory_text)


if __name__ == "__main__":
    unittest.main()
