#!/usr/bin/env python3
"""Adversarial tests for the candidate-only advertised-entry wave two."""

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
SPEC = importlib.util.spec_from_file_location("advertised_entry_executor_wave2", PACKAGE / "executor.py")
assert SPEC and SPEC.loader
executor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(executor)


EXPECTED_IDS = [
    "manifest-gap.rt-vlm-media.00-file-upload",
    "manifest-gap.rt-vlm-media.01-http-s",
    "manifest-gap.rt-vlm-media.02-s3",
    "manifest-gap.rt-vlm-media.03-allowlisted-file-uri",
    "manifest-gap.rt-vlm-media.04-inline-data-uri",
    "manifest-gap.rt-vlm-media.05-rtsp",
    "manifest-gap.rt-vlm-media.06-dense-captions",
    "manifest-gap.rt-vlm-media.07-incidents",
    "manifest-gap.rt-vlm-media.09-reasoning",
    "manifest-gap.rt-vlm-models.00-cosmos-reason-1-2",
    "manifest-gap.rt-vlm-models.01-cosmos-3-nano-super",
    "manifest-gap.rt-vlm-models.02-nemotron-omni",
    "manifest-gap.rt-vlm-models.03-qwen-3-5-and-moe",
    "manifest-gap.rt-vlm-performance-observability.00-efficient-video-sampling",
    "manifest-gap.rt-vlm-performance-observability.01-gop-aware-decode",
    "manifest-gap.rt-vlm-performance-observability.02-decoder-reuse",
    "manifest-gap.rt-vlm-performance-observability.04-asset-limits-and-expiry",
    "manifest-gap.rt-vlm-performance-observability.07-absolute-timestamp-metadata",
    "manifest-gap.synthetic-data-tools.00-semantic-label-helpers",
    "manifest-gap.synthetic-data-tools.02-rgb-depth-video-conversion",
    "manifest-gap.synthetic-data-tools.03-ground-truth-conversion",
]


class AdvertisedEntryExecutorWave2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inventory = json.loads((PACKAGE / "inventory.json").read_text())
        cls.inventory_schema = json.loads((PACKAGE / "inventory.schema.json").read_text())
        cls.result_schema = json.loads((PACKAGE / "result.schema.json").read_text())
        cls.result = executor.execute()

    def test_inventory_and_result_validate_against_schemas(self):
        jsonschema.Draft202012Validator(self.inventory_schema).validate(self.inventory)
        jsonschema.Draft202012Validator(self.result_schema).validate(self.result)

    def test_exact_denominator_order_pointers_and_predecessor_disjointness(self):
        self.assertEqual(
            self.inventory["denominator"],
            {
                "advertised_gap_entries": 87,
                "previously_selected_candidate_entries": 8,
                "prior_open_entries": 79,
                "selected_candidate_entries": 21,
                "entries_left_open": 58,
            },
        )
        self.assertEqual([case["entry_id"] for case in self.inventory["cases"]], EXPECTED_IDS)
        self.assertEqual([result["entry_id"] for result in self.result["results"]], EXPECTED_IDS)
        self.assertEqual(len({case["manifest_pointer"] for case in self.inventory["cases"]}), 21)
        predecessor = json.loads(
            (executor.REPO_ROOT / self.inventory["previous_candidate_inventory"]["path"]).read_text()
        )
        predecessor_ids = {case["entry_id"] for case in predecessor["cases"]}
        self.assertEqual(len(predecessor_ids), 8)
        self.assertFalse(predecessor_ids & set(EXPECTED_IDS))

    def test_results_are_candidate_observations_not_live_acceptance(self):
        self.assertTrue(self.result["candidate_only"])
        self.assertEqual(self.result["runtime_evidence"], [])
        self.assertEqual(self.result["official_capability_effect"], "none_candidate_only")
        for result in self.result["results"]:
            self.assertEqual(result["observation"], "observed_match")
            self.assertEqual(result["runtime_evidence"], [])
            self.assertEqual(result["official_capability_effect"], "none_candidate_only")
            self.assertTrue(result["evidence_scope"].startswith("subset:"))
            self.assertNotIn("passed_current", json.dumps(result))

    def test_each_case_runs_in_isolation(self):
        for entry_id in EXPECTED_IDS:
            with self.subTest(entry_id=entry_id):
                result = executor.execute([entry_id])
                self.assertEqual([item["entry_id"] for item in result["results"]], [entry_id])

    def test_unknown_case_is_rejected(self):
        with self.assertRaises(executor.QualificationError):
            executor.execute(["manifest-gap.not-real"])

    def test_duplicate_inventory_key_is_rejected_before_adapter(self):
        raw = (PACKAGE / "inventory.json").read_text()
        duplicate = raw.replace('"schema_version": 1,', '"schema_version": 1,\n  "schema_version": 1,', 1)
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "inventory.json"
            path.write_text(duplicate)
            adapter = mock.Mock()
            with mock.patch.object(executor, "INVENTORY_PATH", path), mock.patch.dict(
                executor.ADAPTERS, {"file_upload_helper": adapter}
            ):
                with self.assertRaisesRegex(executor.QualificationError, "duplicate JSON key"):
                    executor.execute([EXPECTED_IDS[0]])
            adapter.assert_not_called()

    def test_executor_validates_its_own_result_schema(self):
        schema = copy.deepcopy(self.result_schema)
        schema["properties"]["official_capability_effect"]["const"] = "impossible"
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "result.schema.json"
            path.write_text(json.dumps(schema))
            with mock.patch.object(executor, "RESULT_SCHEMA_PATH", path):
                with self.assertRaisesRegex(executor.QualificationError, "result schema validation failed"):
                    executor.execute([EXPECTED_IDS[0]])

    def test_source_tamper_fails_before_adapter(self):
        original = executor._read_bytes
        target = self.inventory["cases"][0]["source_locks"][0]["path"]

        def tampered(path, *args, **kwargs):
            data = original(path, *args, **kwargs)
            return data + b"\n# tampered" if path == target else data

        adapter = mock.Mock()
        with mock.patch.object(executor, "_read_bytes", side_effect=tampered), mock.patch.dict(
            executor.ADAPTERS, {"file_upload_helper": adapter}
        ):
            with self.assertRaises(executor.QualificationError):
                executor.execute([EXPECTED_IDS[0]])
        adapter.assert_not_called()

    def test_inventory_cannot_read_outside_repository(self):
        inventory = copy.deepcopy(self.inventory)
        inventory["source_plan"]["path"] = "../../etc/passwd"
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "inventory.json"
            path.write_text(json.dumps(inventory))
            with mock.patch.object(executor, "INVENTORY_PATH", path):
                with self.assertRaisesRegex(
                    executor.QualificationError, "unsafe repository path"
                ):
                    executor.execute([EXPECTED_IDS[0]])

    def test_bounded_adapters_and_source_sets_are_exact(self):
        for case in self.inventory["cases"]:
            pointer, adapter_id, source_paths = executor.EXPECTED_CASE_BINDINGS[case["entry_id"]]
            self.assertEqual(case["manifest_pointer"], pointer)
            self.assertEqual(case["adapter_id"], adapter_id)
            self.assertEqual({lock["path"] for lock in case["source_locks"]}, source_paths)

    def test_schema_rejects_denominator_policy_scope_and_count_tamper(self):
        validator = jsonschema.Draft202012Validator(self.inventory_schema)
        for mutate in (
            lambda value: value["denominator"].__setitem__("entries_left_open", 57),
            lambda value: value["policy"].__setitem__("can_mark_passed_current", True),
            lambda value: value["policy"]["runtime_evidence"].append("fake"),
            lambda value: value["cases"][0].__setitem__("evidence_scope", "whole family"),
            lambda value: value["cases"].pop(),
        ):
            candidate = copy.deepcopy(self.inventory)
            mutate(candidate)
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

    def test_model_cases_preserve_unqualified_nonreadiness(self):
        model_results = [result for result in self.result["results"] if ".rt-vlm-models." in result["entry_id"]]
        self.assertEqual(len(model_results), 4)
        for result in model_results:
            output = result["semantic_output"]
            self.assertFalse(output["availability_proven"])
            self.assertFalse(output["readiness_proven"])
            self.assertEqual(output["contract_scope"], "exact-source-listing-only")
            self.assertTrue(all("unqualified" in status for status in output["thor_statuses"]))

    def test_helper_outputs_record_no_real_writes_or_omitted_workflows(self):
        outputs = {result["entry_id"]: result["semantic_output"] for result in self.result["results"]}
        for output in outputs.values():
            for key, value in output.items():
                if key.startswith("real_"):
                    self.assertEqual(value, 0)
        self.assertFalse(outputs["manifest-gap.synthetic-data-tools.02-rgb-depth-video-conversion"]["video_overlay_executed"])
        self.assertFalse(outputs["manifest-gap.synthetic-data-tools.03-ground-truth-conversion"]["full_dataset_conversion_executed"])

    def test_executor_has_no_forbidden_imports_or_process_calls(self):
        source = (PACKAGE / "executor.py").read_text()
        tree = ast.parse(source)
        forbidden_roots = {"subprocess", "socket", "requests", "urllib", "docker", "boto3"}
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertFalse(imported & forbidden_roots)
        for forbidden in ("os.system", "Popen", "Path.write_", "urlopen(", "requests."):
            self.assertNotIn(forbidden, source)

    def test_no_repository_inputs_are_modified_by_execution(self):
        monitored = {
            executor.INVENTORY_PATH,
            executor.REPO_ROOT / self.inventory["source_plan"]["path"],
            executor.REPO_ROOT / self.inventory["source_manifest"]["path"],
            executor.REPO_ROOT / self.inventory["previous_candidate_inventory"]["path"],
        }
        monitored.update(
            executor.REPO_ROOT / lock["path"]
            for case in self.inventory["cases"]
            for lock in case["source_locks"]
        )
        before = {path: (path.stat().st_size, path.stat().st_mtime_ns) for path in monitored}
        executor.execute()
        after = {path: (path.stat().st_size, path.stat().st_mtime_ns) for path in monitored}
        self.assertEqual(before, after)


if __name__ == "__main__":
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    unittest.main()
