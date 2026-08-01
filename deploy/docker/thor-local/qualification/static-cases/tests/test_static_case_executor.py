from __future__ import annotations

import ast
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

from jsonschema import Draft7Validator, Draft202012Validator


LANE = Path(__file__).resolve().parents[1]
REPO_ROOT = LANE.parents[4]
MODULE_PATH = LANE / "static_case_executor.py"
SPEC = importlib.util.spec_from_file_location("static_case_executor", MODULE_PATH)
assert SPEC and SPEC.loader
EXECUTOR = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = EXECUTOR
SPEC.loader.exec_module(EXECUTOR)


class StaticCasePackageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.inventory = EXECUTOR.load_and_validate_inventory()
        cls.inventory_schema = json.loads(
            (LANE / "inventory.schema.json").read_text(encoding="utf-8")
        )
        cls.result_schema = json.loads(
            (LANE / "static-result.schema.json").read_text(encoding="utf-8")
        )

    def test_exact_24_id_tranche_and_family_split(self) -> None:
        cases = self.inventory["cases"]
        self.assertEqual(len(cases), 24)
        self.assertEqual(
            {case["capability_id"] for case in cases}, EXECUTOR.EXPECTED_CAPABILITY_IDS
        )
        self.assertEqual(
            sum(case["family"] == "calibration_warehouse" for case in cases), 13
        )
        self.assertEqual(sum(case["family"] == "live_static" for case in cases), 11)

    def test_every_case_remains_candidate_only_and_non_advancing(self) -> None:
        for case in self.inventory["cases"]:
            self.assertEqual(case["integration_state"], "candidate_only")
            self.assertIs(case["executor_ready"], False)
            self.assertIs(case["can_advance_capability"], False)

    def test_policy_is_strict_and_has_only_static_outcomes(self) -> None:
        policy = self.inventory["policy"]
        self.assertEqual(policy["network"], "forbidden")
        self.assertEqual(policy["docker"], "forbidden")
        self.assertEqual(policy["subprocess_lifecycle"], "forbidden")
        self.assertEqual(policy["warehouse_sample_bundle"], "excluded")
        self.assertEqual(policy["max_bytes"], 8 * 1024 * 1024)
        self.assertEqual(policy["max_files"], 64)
        self.assertEqual(policy["deadline_seconds"], 10)
        self.assertEqual(
            policy["allowed_outcomes"],
            ["observed_match", "observed_mismatch", "blocked", "not_applicable"],
        )

    def test_runtime_evidence_schema_is_shape_reference_only_and_hash_bound(self) -> None:
        binding = self.inventory["evidence_schema_binding"]
        path = REPO_ROOT / binding["path"]
        self.assertEqual(binding["usage"], "shape_reference_only_no_runtime_evidence")
        self.assertEqual(EXECUTOR._sha_bytes(path.read_bytes()), binding["sha256"])

    def test_plan_is_inert(self) -> None:
        plan = EXECUTOR.plan(self.inventory)
        self.assertEqual(plan["mode"], "candidate_only_plan")
        self.assertIs(plan["executor_ready"], False)
        self.assertIs(plan["can_advance_capability"], False)
        self.assertEqual(plan["network"], "forbidden")
        self.assertEqual(plan["docker"], "forbidden")
        self.assertEqual(plan["case_count"], 24)
        self.assertEqual({case["state"] for case in plan["cases"]}, {"candidate_only"})

    def test_all_24_cases_produce_schema_valid_non_advancing_observations(self) -> None:
        validator = Draft202012Validator(self.result_schema)
        for case in self.inventory["cases"]:
            with self.subTest(case=case["case_id"]):
                result = EXECUTOR.inspect_case(self.inventory, case["case_id"])
                self.assertEqual(list(validator.iter_errors(result)), [])
                self.assertIn(result["outcome"], self.inventory["policy"]["allowed_outcomes"])
                self.assertEqual(result["integration_state"], "candidate_only")
                self.assertIs(result["executor_ready"], False)
                self.assertIs(result["can_advance_capability"], False)
                self.assertEqual(
                    result["evidence_class"], "static_observation_not_runtime_evidence"
                )
                self.assertEqual(
                    result["source_hashes_before"], result["source_hashes_after"]
                )
                self.assertIs(result["cleanup"]["temporary_root_removed"], True)
                self.assertLessEqual(result["bounds"]["files_read"], 64)
                self.assertLessEqual(result["bounds"]["bytes_read"], 8 * 1024 * 1024)

    def test_calibration_fixtures_cover_positive_and_adjacent_negative_cases(self) -> None:
        schema = json.loads(
            (
                REPO_ROOT
                / "libs/analytics/spatialai-data-utils/spatialai_data_utils/schemas/calibration.json"
            ).read_text(encoding="utf-8")
        )
        validator = Draft7Validator(schema)
        valid = json.loads(
            (LANE / "fixtures/calibration-valid.json").read_text(encoding="utf-8")
        )
        missing = json.loads(
            (LANE / "fixtures/calibration-invalid-missing-field.json").read_text(
                encoding="utf-8"
            )
        )
        matrix = json.loads(
            (LANE / "fixtures/calibration-invalid-matrix-shape.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(list(validator.iter_errors(valid)), [])
        self.assertGreater(len(list(validator.iter_errors(missing))), 0)
        self.assertGreater(len(list(validator.iter_errors(matrix))), 0)

    def test_calibration_case_does_not_fabricate_official_schema_identity(self) -> None:
        result = EXECUTOR.inspect_case(
            self.inventory, "static-case.calibration-schema-vss-json"
        )
        observations = {item["id"]: item for item in result["observations"]}
        self.assertEqual(result["outcome"], "observed_mismatch")
        self.assertEqual(observations["generated_fixture_matrix"]["status"], "match")
        self.assertEqual(observations["official_schema_identity"]["status"], "mismatch")
        self.assertNotEqual(
            observations["official_schema_identity"]["expected"],
            observations["official_schema_identity"]["observed"],
        )

    def test_warehouse_sample_markers_are_absent_from_inventory_and_fixtures(self) -> None:
        paths = [LANE / "inventory.json", *sorted((LANE / "fixtures").glob("*.json"))]
        for path in paths:
            text = path.read_text(encoding="utf-8")
            for marker in EXECUTOR.EXCLUDED_SAMPLE_MARKERS:
                self.assertNotIn(marker, text, path)

    def test_executor_ast_has_no_network_docker_or_subprocess_primitives(self) -> None:
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
                {"asyncio", "docker", "http", "requests", "socket", "subprocess", "urllib"}
            )
        )
        self.assertNotIn("os.system", source)
        self.assertNotIn("Popen", source)
        self.assertNotIn("compose up", source)
        self.assertNotIn("compose down", source)

    def test_cli_has_no_execute_or_activation_subcommand(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn('add_parser("validate"', source)
        self.assertIn('add_parser("plan"', source)
        self.assertIn('add_parser(\n        "inspect"', source)
        self.assertNotIn('add_parser("execute"', source)
        self.assertNotIn("operator_ack", source)

    def test_inventory_schema_rejects_executor_ready_or_runtime_outcome(self) -> None:
        validator = Draft202012Validator(self.inventory_schema)
        ready = copy.deepcopy(self.inventory)
        ready["cases"][0]["executor_ready"] = True
        self.assertGreater(len(list(validator.iter_errors(ready))), 0)
        outcome = copy.deepcopy(self.inventory)
        outcome["policy"]["allowed_outcomes"] = ["passed"]
        self.assertGreater(len(list(validator.iter_errors(outcome))), 0)

    def test_safe_repo_reader_rejects_escape_and_symlink(self) -> None:
        with self.assertRaises(EXECUTOR.StaticCaseError):
            EXECUTOR._repo_file("../outside")
        original_root = EXECUTOR.REPO_ROOT
        with tempfile.TemporaryDirectory() as temporary_name:
            root = Path(temporary_name)
            (root / "real.txt").write_text("safe", encoding="utf-8")
            (root / "link.txt").symlink_to(root / "real.txt")
            EXECUTOR.REPO_ROOT = root
            try:
                with self.assertRaises(EXECUTOR.StaticCaseError):
                    EXECUTOR._repo_file("link.txt")
            finally:
                EXECUTOR.REPO_ROOT = original_root

    def test_budget_rejects_oversized_file_and_sixty_fifth_file(self) -> None:
        original_root = EXECUTOR.REPO_ROOT
        with tempfile.TemporaryDirectory() as temporary_name:
            root = Path(temporary_name)
            EXECUTOR.REPO_ROOT = root
            try:
                (root / "large").write_bytes(b"x" * (EXECUTOR.MAX_BYTES + 1))
                with self.assertRaises(EXECUTOR.BoundError):
                    EXECUTOR.Budget().read_repo("large")
                budget = EXECUTOR.Budget()
                for index in range(EXECUTOR.MAX_FILES + 1):
                    (root / f"f{index}").write_text("x", encoding="utf-8")
                for index in range(EXECUTOR.MAX_FILES):
                    budget.read_repo(f"f{index}")
                with self.assertRaises(EXECUTOR.BoundError):
                    budget.read_repo(f"f{EXECUTOR.MAX_FILES}")
            finally:
                EXECUTOR.REPO_ROOT = original_root

    def test_source_hash_change_is_detectable(self) -> None:
        original_root = EXECUTOR.REPO_ROOT
        with tempfile.TemporaryDirectory() as temporary_name:
            root = Path(temporary_name)
            source = root / "source.txt"
            source.write_text("before", encoding="utf-8")
            EXECUTOR.REPO_ROOT = root
            try:
                budget = EXECUTOR.Budget()
                budget.read_repo("source.txt")
                before = dict(budget.hashes)
                source.write_text("after", encoding="utf-8")
                self.assertNotEqual(before, budget.rehash())
            finally:
                EXECUTOR.REPO_ROOT = original_root

    def test_binding_drift_is_an_observed_mismatch_not_a_false_match(self) -> None:
        original_root = EXECUTOR.REPO_ROOT
        with tempfile.TemporaryDirectory() as temporary_name:
            root = Path(temporary_name)
            document = {"capabilities": [{"id": "capability.test", "contract": {"x": 2}}]}
            (root / "binding.json").write_text(json.dumps(document), encoding="utf-8")
            case = {
                "binding": {
                    "path": "binding.json",
                    "collection": "capabilities",
                    "record_id": "capability.test",
                    "contract_sha256": EXECUTOR._sha_json({"x": 1}),
                }
            }
            EXECUTOR.REPO_ROOT = root
            try:
                _, observation = EXECUTOR._binding(case, EXECUTOR.Budget())
                self.assertEqual(observation["status"], "mismatch")
            finally:
                EXECUTOR.REPO_ROOT = original_root


if __name__ == "__main__":
    unittest.main()
