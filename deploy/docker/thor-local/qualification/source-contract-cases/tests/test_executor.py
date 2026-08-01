from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

from jsonschema import Draft202012Validator


LANE = Path(__file__).resolve().parents[1]
MODULE_PATH = LANE / "executor.py"
SPEC = importlib.util.spec_from_file_location("source_contract_cases", MODULE_PATH)
assert SPEC and SPEC.loader
EXECUTOR = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = EXECUTOR
SPEC.loader.exec_module(EXECUTOR)


class SourceContractExecutorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.inventory = EXECUTOR.load_and_validate_inventory()
        cls.inventory_schema = json.loads(
            (LANE / "inventory.schema.json").read_text(encoding="utf-8")
        )
        cls.result_schema = json.loads(
            (LANE / "result.schema.json").read_text(encoding="utf-8")
        )

    def test_exact_sixteen_case_denominator_and_unique_bindings(self) -> None:
        cases = self.inventory["cases"]
        self.assertEqual(len(cases), 16)
        self.assertEqual(
            {case["case_id"] for case in cases}, EXECUTOR.EXPECTED_CASE_IDS
        )
        self.assertEqual(len({case["planning_requirement_id"] for case in cases}), 16)
        self.assertEqual(len({case["capability_id"] for case in cases}), 16)

    def test_inventory_and_both_schemas_are_digest_pinned(self) -> None:
        self.assertEqual(
            EXECUTOR._sha_json(self.inventory), EXECUTOR.INVENTORY_CANONICAL_SHA256
        )
        self.assertEqual(
            hashlib.sha256((LANE / "inventory.schema.json").read_bytes()).hexdigest(),
            EXECUTOR.INVENTORY_SCHEMA_RAW_SHA256,
        )
        self.assertEqual(
            hashlib.sha256((LANE / "result.schema.json").read_bytes()).hexdigest(),
            EXECUTOR.RESULT_SCHEMA_RAW_SHA256,
        )

    def test_policy_is_file_only_nonadvancing_and_sample_free(self) -> None:
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

    def test_plan_materializes_only_isolated_executor_candidates(self) -> None:
        plan = EXECUTOR.plan(self.inventory)
        self.assertEqual(plan["case_count"], 16)
        self.assertEqual(plan["executor_ready_count"], 16)
        self.assertIs(plan["can_advance_capability"], False)
        self.assertIs(plan["can_mark_passed_current"], False)
        self.assertTrue(all(item["materialized"] for item in plan["cases"]))
        self.assertTrue(all(item["executor_ready"] for item in plan["cases"]))
        self.assertTrue(
            all(
                item["materialization_scope"] == "isolated_candidate_only"
                for item in plan["cases"]
            )
        )

    def test_every_result_is_schema_valid_stable_and_bounded(self) -> None:
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

    def test_current_outcomes_are_fifteen_matches_and_one_honest_mismatch(self) -> None:
        report = EXECUTOR.run_all(self.inventory)
        self.assertEqual(report["candidate_materialized_count"], 16)
        self.assertEqual(report["candidate_executor_ready_count"], 16)
        self.assertEqual(report["live_requirement_materialized_count"], 0)
        self.assertEqual(report["live_requirement_executor_ready_count"], 0)
        self.assertEqual(report["runtime_evidence_count"], 0)
        self.assertEqual(report["can_advance_capability_count"], 0)
        self.assertEqual(report["can_mark_passed_current_count"], 0)
        self.assertEqual(
            report["outcomes"], {"observed_match": 15, "observed_mismatch": 1}
        )
        self.assertEqual(
            [
                item["case_id"]
                for item in report["results"]
                if item["outcome"] == "observed_mismatch"
            ],
            ["source-contract-case.nvstreamer-full-config"],
        )

    def test_nvstreamer_mismatch_is_exact_thor_override_drift(self) -> None:
        result = EXECUTOR.run_case(
            self.inventory, "source-contract-case.nvstreamer-full-config"
        )
        mismatches = {
            item["assertion_id"]: (item["expected"], item["observed"])
            for item in result["observations"]
            if item["status"] == "mismatch"
        }
        self.assertEqual(
            mismatches,
            {
                "official-rtsp-port": (8554, 30554),
                "official-rtsp-instances": (8, 10),
                "official-max-upload": (10000, 25600),
                "official-https-default": (True, False),
            },
        )
        session = next(
            item
            for item in result["observations"]
            if item["assertion_id"] == "session-age"
        )
        self.assertEqual(session["status"], "match")

    def test_reference_performance_cases_never_claim_thor_results(self) -> None:
        for case in self.inventory["cases"][:7]:
            with self.subTest(case=case["case_id"]):
                result = EXECUTOR.run_case(self.inventory, case["case_id"])
                self.assertEqual(result["outcome"], "observed_match")
                boundary = next(
                    item
                    for item in result["observations"]
                    if item["assertion_id"] == "not-thor-results"
                )
                self.assertIs(boundary["expected"], False)
                self.assertIs(boundary["observed"], False)

    def test_all_source_assertions_have_exact_digest_lock_coverage(self) -> None:
        for case in self.inventory["cases"]:
            locks = {item["path"] for item in case["source_locks"]}
            sources = {
                source
                for assertion in case["assertions"]
                for source in assertion["sources"]
            }
            self.assertEqual(locks, sources, case["case_id"])

    def test_all_live_planning_records_remain_unmaterialized_with_zero_evidence(
        self,
    ) -> None:
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
            self.assertNotIn("static_executor_binding", record)

    def test_results_are_deterministic(self) -> None:
        case_id = "source-contract-case.behavior-dynamic-config"
        self.assertEqual(
            EXECUTOR.run_case(self.inventory, case_id),
            EXECUTOR.run_case(self.inventory, case_id),
        )

    def test_planning_payload_tamper_fails_closed(self) -> None:
        altered = copy.deepcopy(self.inventory)
        altered["cases"][0]["planning_payload_sha256"] = "0" * 64
        with self.assertRaises(EXECUTOR.SourceContractError):
            EXECUTOR.run_case(altered, altered["cases"][0]["case_id"])

    def test_source_digest_tamper_fails_closed(self) -> None:
        altered = copy.deepcopy(self.inventory)
        altered["cases"][0]["source_locks"][0]["sha256"] = "0" * 64
        with self.assertRaises(EXECUTOR.SourceContractError):
            EXECUTOR.run_case(altered, altered["cases"][0]["case_id"])

    def test_partial_source_lock_coverage_fails_closed(self) -> None:
        altered = copy.deepcopy(self.inventory)
        case = next(
            item
            for item in altered["cases"]
            if item["case_id"] == "source-contract-case.alert-parser"
        )
        case["source_locks"].pop()
        with self.assertRaises(EXECUTOR.SourceContractError):
            EXECUTOR.run_case(altered, case["case_id"])

    def test_schema_rejects_promotion_demotion_and_case_count_drift(self) -> None:
        validator = Draft202012Validator(self.inventory_schema)
        promoted = copy.deepcopy(self.inventory)
        promoted["policy"]["can_mark_passed_current"] = True
        self.assertTrue(list(validator.iter_errors(promoted)))
        demoted = copy.deepcopy(self.inventory)
        demoted["cases"][0]["executor_ready"] = False
        self.assertTrue(list(validator.iter_errors(demoted)))
        shortened = copy.deepcopy(self.inventory)
        shortened["cases"].pop()
        self.assertTrue(list(validator.iter_errors(shortened)))

    def test_executor_ast_has_no_network_process_or_environment_mutation(self) -> None:
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
        with self.assertRaises(EXECUTOR.SourceContractError):
            EXECUTOR._repo_file("../outside")
        original_root = EXECUTOR.REPO_ROOT
        with tempfile.TemporaryDirectory() as temporary_name:
            root = Path(temporary_name)
            (root / "real").write_text("safe", encoding="utf-8")
            (root / "link").symlink_to(root / "real")
            EXECUTOR.REPO_ROOT = root
            try:
                with self.assertRaises(EXECUTOR.SourceContractError):
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
                source.write_bytes(b"x" * (EXECUTOR.MAX_BYTES + 1))
                with self.assertRaises(EXECUTOR.BoundError):
                    budget.read("source")
                with self.assertRaises(EXECUTOR.BoundError):
                    budget.rehash()
            finally:
                EXECUTOR.REPO_ROOT = original_root

    def test_duplicate_json_keys_fail_closed(self) -> None:
        with self.assertRaises(EXECUTOR.SourceContractError):
            EXECUTOR._strict_json(b'{"x":1,"x":2}', "duplicate")

    def test_warehouse_sample_markers_are_absent(self) -> None:
        text = (LANE / "inventory.json").read_text(encoding="utf-8")
        for marker in EXECUTOR.EXCLUDED_SAMPLE_MARKERS:
            self.assertNotIn(marker, text)


if __name__ == "__main__":
    unittest.main()
