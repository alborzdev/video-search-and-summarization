#!/usr/bin/env python3
"""Adversarial tests for the candidate-only advertised-entry executors."""

from __future__ import annotations

import ast
import copy
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import jsonschema


PACKAGE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "advertised_entry_executor", PACKAGE / "executor.py"
)
assert SPEC and SPEC.loader
executor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(executor)


EXPECTED_IDS = [
    "manifest-gap.rt-cv-3d-mv3dt.05-associated-skill",
    "manifest-gap.spatial-ai-utils.00-calibration-and-camera-grouping",
    "manifest-gap.spatial-ai-utils.01-3d-2d-geometry",
    "manifest-gap.spatial-ai-utils.02-multiview-visualization",
    "manifest-gap.spatial-ai-utils.04-tracking-hota-clear-identity-count",
    "manifest-gap.spatial-ai-utils.05-nvschema-conversion",
    "manifest-gap.spatial-ai-utils.06-video-frame-tools",
    "manifest-gap.synthetic-data-tools.01-dataset-checks",
]


class AdvertisedEntryExecutorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inventory = json.loads((PACKAGE / "inventory.json").read_text())
        cls.inventory_schema = json.loads(
            (PACKAGE / "inventory.schema.json").read_text()
        )
        cls.result_schema = json.loads((PACKAGE / "result.schema.json").read_text())
        cls.result = executor.execute()

    def test_inventory_and_result_validate_against_schemas(self):
        jsonschema.Draft202012Validator(self.inventory_schema).validate(self.inventory)
        jsonschema.Draft202012Validator(self.result_schema).validate(self.result)

    def test_exact_denominator_entry_ids_and_pointers(self):
        self.assertEqual(
            self.inventory["denominator"],
            {
                "advertised_gap_entries": 87,
                "selected_candidate_entries": 8,
                "entries_left_open": 79,
            },
        )
        self.assertEqual(
            [case["entry_id"] for case in self.inventory["cases"]], EXPECTED_IDS
        )
        self.assertEqual(
            [result["entry_id"] for result in self.result["results"]], EXPECTED_IDS
        )
        self.assertEqual(
            len({case["manifest_pointer"] for case in self.inventory["cases"]}), 8
        )

    def test_results_are_candidate_observations_not_live_acceptance(self):
        self.assertTrue(self.result["candidate_only"])
        self.assertEqual(self.result["runtime_evidence"], [])
        self.assertEqual(
            self.result["official_capability_effect"], "none_candidate_only"
        )
        for case in self.result["results"]:
            self.assertEqual(case["observation"], "observed_match")
            self.assertEqual(case["runtime_evidence"], [])
            self.assertEqual(case["official_capability_effect"], "none_candidate_only")
            self.assertTrue(case["evidence_scope"].startswith("subset:"))
            self.assertNotIn("passed_current", json.dumps(case))

    def test_each_case_runs_in_isolation(self):
        for entry_id in EXPECTED_IDS:
            with self.subTest(entry_id=entry_id):
                result = executor.execute([entry_id])
                self.assertEqual(len(result["results"]), 1)
                self.assertEqual(result["results"][0]["entry_id"], entry_id)
                self.assertEqual(result["results"][0]["observation"], "observed_match")

    def test_unknown_case_is_rejected(self):
        with self.assertRaises(executor.QualificationError):
            executor.execute(["manifest-gap.not-real"])

    def test_duplicate_inventory_key_is_rejected_before_adapter(self):
        raw = (PACKAGE / "inventory.json").read_text()
        duplicate = raw.replace(
            '"schema_version": 1,',
            '"schema_version": 1,\n  "schema_version": 1,',
            1,
        )
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "inventory.json"
            path.write_text(duplicate)
            with mock.patch.object(executor, "INVENTORY_PATH", path):
                with mock.patch.dict(
                    executor.ADAPTERS, {"calibration_grouping": mock.Mock()}
                ):
                    with self.assertRaisesRegex(
                        executor.QualificationError, "duplicate JSON key"
                    ):
                        executor.execute([EXPECTED_IDS[1]])
                    executor.ADAPTERS["calibration_grouping"].assert_not_called()

    def test_executor_validates_its_own_result_schema(self):
        schema = copy.deepcopy(self.result_schema)
        schema["properties"]["official_capability_effect"]["const"] = "impossible"
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "result.schema.json"
            path.write_text(json.dumps(schema))
            with mock.patch.object(executor, "RESULT_SCHEMA_PATH", path):
                with self.assertRaisesRegex(
                    executor.QualificationError, "result schema validation failed"
                ):
                    executor.execute([EXPECTED_IDS[0]])

    def test_source_tamper_fails_before_adapter(self):
        original = executor._read_bytes
        target = self.inventory["cases"][1]["source_locks"][0]["path"]

        def tampered(path, *args, **kwargs):
            data = original(path, *args, **kwargs)
            return data + b"\n# tampered" if path == target else data

        with mock.patch.object(executor, "_read_bytes", side_effect=tampered):
            with mock.patch.dict(
                executor.ADAPTERS, {"calibration_grouping": mock.Mock()}
            ):
                with self.assertRaises(executor.QualificationError):
                    executor.execute([EXPECTED_IDS[1]])
                executor.ADAPTERS["calibration_grouping"].assert_not_called()

    def test_bounded_adapter_and_source_sets_are_exact(self):
        for case in self.inventory["cases"]:
            pointer, adapter_id, source_paths = executor.EXPECTED_CASE_BINDINGS[
                case["entry_id"]
            ]
            self.assertEqual(case["manifest_pointer"], pointer)
            self.assertEqual(case["adapter_id"], adapter_id)
            self.assertEqual(
                {lock["path"] for lock in case["source_locks"]}, source_paths
            )

    def test_schema_rejects_denominator_policy_and_scope_tamper(self):
        validator = jsonschema.Draft202012Validator(self.inventory_schema)
        for mutate in (
            lambda value: value["denominator"].__setitem__("entries_left_open", 78),
            lambda value: value["policy"].__setitem__("can_mark_passed_current", True),
            lambda value: value["policy"]["runtime_evidence"].append("fake"),
            lambda value: value["cases"][0].__setitem__(
                "evidence_scope", "whole family"
            ),
            lambda value: value["cases"].pop(),
        ):
            candidate = copy.deepcopy(self.inventory)
            mutate(candidate)
            with self.subTest(candidate=candidate.get("denominator")):
                self.assertTrue(list(validator.iter_errors(candidate)))

    def test_result_schema_rejects_runtime_or_official_effect_tamper(self):
        validator = jsonschema.Draft202012Validator(self.result_schema)
        for field, value in (
            ("runtime_evidence", ["fake"]),
            ("official_capability_effect", "passed_current"),
        ):
            candidate = copy.deepcopy(self.result)
            candidate[field] = value
            self.assertTrue(list(validator.iter_errors(candidate)))

    def test_executor_has_no_forbidden_imports_or_process_calls(self):
        tree = ast.parse((PACKAGE / "executor.py").read_text())
        forbidden_roots = {"subprocess", "socket", "requests", "urllib", "docker"}
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertFalse(imported & forbidden_roots)
        source = (PACKAGE / "executor.py").read_text()
        self.assertNotIn("os.system", source)
        self.assertNotIn("Popen", source)
        self.assertNotIn("Path.write_", source)

    def test_no_repository_files_created_by_execution(self):
        monitored = {executor.INVENTORY_PATH}
        monitored.add(executor.REPO_ROOT / self.inventory["source_plan"]["path"])
        monitored.add(executor.REPO_ROOT / self.inventory["source_manifest"]["path"])
        monitored.update(
            executor.REPO_ROOT / lock["path"]
            for case in self.inventory["cases"]
            for lock in case["source_locks"]
        )
        before = {
            path: (path.stat().st_size, path.stat().st_mtime_ns) for path in monitored
        }
        executor.execute()
        after = {
            path: (path.stat().st_size, path.stat().st_mtime_ns) for path in monitored
        }
        self.assertEqual(before, after)


if __name__ == "__main__":
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    unittest.main()
