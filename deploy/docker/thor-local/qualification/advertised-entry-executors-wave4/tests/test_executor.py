#!/usr/bin/env python3
"""Adversarial tests for advertised-entry executor wave four."""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import jsonschema


PACKAGE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "advertised_entry_executor_wave4", PACKAGE / "executor.py"
)
assert SPEC and SPEC.loader
executor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(executor)

EXPECTED_IDS = [
    "manifest-gap.video-summarization-live.00-live-captions",
    "manifest-gap.video-summarization-live.01-live-stream-summaries",
    "manifest-gap.video-summarization-live.02-stream-reports",
    "manifest-gap.video-summarization-live.03-caption-backed-q-a",
    "manifest-gap.video-summarization-live.04-elasticsearch-caption-storage",
]


class AdvertisedEntryExecutorWave4Tests(unittest.TestCase):
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

    def test_exact_denominator_order_and_predecessor_disjointness(self):
        self.assertEqual(self.inventory["denominator"], executor.EXPECTED_DENOMINATOR)
        self.assertEqual(
            [case["entry_id"] for case in self.inventory["cases"]], EXPECTED_IDS
        )
        self.assertEqual(
            [item["entry_id"] for item in self.result["results"]], EXPECTED_IDS
        )
        predecessor_ids = set()
        for spec in self.inventory["previous_candidate_inventories"]:
            previous = json.loads((executor.REPO_ROOT / spec["path"]).read_text())
            ids = {case["entry_id"] for case in previous["cases"]}
            self.assertFalse(ids & predecessor_ids)
            predecessor_ids.update(ids)
        self.assertEqual(len(predecessor_ids), 52)
        self.assertFalse(predecessor_ids & set(EXPECTED_IDS))

    def test_results_are_cross_layer_candidates_only(self):
        self.assertTrue(self.result["candidate_only"])
        self.assertEqual(self.result["runtime_evidence"], [])
        self.assertEqual(
            self.result["official_capability_effect"], "none_candidate_only"
        )
        for item in self.result["results"]:
            self.assertEqual(item["observation"], "observed_match")
            self.assertEqual(item["runtime_evidence"], [])
            self.assertEqual(item["official_capability_effect"], "none_candidate_only")
            output = item["semantic_output"]
            self.assertEqual(
                output["contract_scope"],
                "exact-digest-locked-cross-layer-source-contract-only",
            )
            self.assertGreaterEqual(len(output["call_graph_edges"]), 2)
            self.assertGreaterEqual(len(output["matched_assertions"]), 3)
            self.assertFalse(output["runtime_executed"])
            self.assertFalse(output["workflow_proven"])
            self.assertFalse(output["service_readiness_proven"])
            self.assertFalse(output["model_availability_proven"])
            self.assertEqual(output["real_file_writes"], 0)
            self.assertNotIn("passed_current", json.dumps(item))

    def test_each_case_runs_in_isolation(self):
        for entry_id in EXPECTED_IDS:
            with self.subTest(entry_id=entry_id):
                result = executor.execute([entry_id])
                self.assertEqual(
                    [item["entry_id"] for item in result["results"]], [entry_id]
                )

    def test_unknown_and_duplicate_selections_are_rejected(self):
        with self.assertRaises(executor.QualificationError):
            executor.execute(["manifest-gap.not-real"])
        with self.assertRaisesRegex(executor.QualificationError, "duplicate --case"):
            executor.execute([EXPECTED_IDS[0], EXPECTED_IDS[0]])

    def test_duplicate_json_key_is_rejected(self):
        with self.assertRaisesRegex(executor.QualificationError, "duplicate JSON key"):
            executor._strict_json_bytes(b'{"x":1,"x":2}', "duplicate fixture")

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
        target = self.inventory["cases"][0]["source_locks"][0]["path"]

        def tampered(path, *args, **kwargs):
            data = original(path, *args, **kwargs)
            return data + b"\n# tampered" if path == target else data

        adapter = mock.Mock()
        with (
            mock.patch.object(executor, "_read_bytes", side_effect=tampered),
            mock.patch.dict(executor.ADAPTERS, {"live_captions_cross_layer": adapter}),
        ):
            with self.assertRaisesRegex(
                executor.QualificationError, "source lock mismatch"
            ):
                executor.execute([EXPECTED_IDS[0]])
        adapter.assert_not_called()

    def test_inventory_cannot_read_outside_repository(self):
        with self.assertRaisesRegex(
            executor.QualificationError, "unsafe repository path"
        ):
            executor._read_bytes("../../etc/passwd")
        with self.assertRaisesRegex(
            executor.QualificationError, "unsafe repository path"
        ):
            executor._read_bytes("/etc/passwd")

    def test_exact_plan_manifest_predecessor_and_inventory_inputs_are_code_locked(self):
        self.assertEqual(self.inventory["source_plan"], executor.EXPECTED_SOURCE_PLAN)
        self.assertEqual(
            self.inventory["source_manifest"], executor.EXPECTED_SOURCE_MANIFEST
        )
        self.assertEqual(
            self.inventory["previous_candidate_inventories"],
            executor.EXPECTED_PREDECESSORS,
        )
        self.assertEqual(
            hashlib.sha256((PACKAGE / "inventory.json").read_bytes()).hexdigest(),
            executor.EXPECTED_INVENTORY_SHA256,
        )

    def test_bounded_adapters_sources_and_bindings_are_exact(self):
        for case in self.inventory["cases"]:
            pointer, adapter_id, source_paths = executor.EXPECTED_CASE_BINDINGS[
                case["entry_id"]
            ]
            self.assertEqual(case["manifest_pointer"], pointer)
            self.assertEqual(case["adapter_id"], adapter_id)
            self.assertEqual(
                {lock["path"] for lock in case["source_locks"]}, source_paths
            )

    def test_schema_rejects_denominator_policy_scope_path_and_count_tamper(self):
        validator = jsonschema.Draft202012Validator(self.inventory_schema)
        mutations = (
            lambda value: value["denominator"].__setitem__("entries_left_open", 29),
            lambda value: value["policy"].__setitem__("can_mark_passed_current", True),
            lambda value: value["policy"]["runtime_evidence"].append("fake"),
            lambda value: value["cases"][0].__setitem__(
                "evidence_scope", "whole workflow"
            ),
            lambda value: value["cases"][0]["source_locks"][0].__setitem__(
                "path", "../../etc/passwd"
            ),
            lambda value: value["cases"].pop(),
        )
        for mutate in mutations:
            candidate = copy.deepcopy(self.inventory)
            mutate(candidate)
            self.assertTrue(list(validator.iter_errors(candidate)))

    def test_result_schema_rejects_runtime_workflow_readiness_and_official_effect(self):
        validator = jsonschema.Draft202012Validator(self.result_schema)
        candidates = []
        for path, value in (
            (("runtime_evidence",), ["fake"]),
            (("official_capability_effect",), "passed_current"),
            (("results", 0, "semantic_output", "runtime_executed"), True),
            (("results", 0, "semantic_output", "workflow_proven"), True),
            (("results", 0, "semantic_output", "service_readiness_proven"), True),
            (("results", 0, "semantic_output", "model_availability_proven"), True),
        ):
            candidate = copy.deepcopy(self.result)
            target = candidate
            for token in path[:-1]:
                target = target[token]
            target[path[-1]] = value
            candidates.append(candidate)
        for candidate in candidates:
            self.assertTrue(list(validator.iter_errors(candidate)))

    def test_python_sources_are_ast_parsed_and_configs_are_bounded(self):
        for item in self.result["results"]:
            output = item["semantic_output"]
            expected_python = sorted(
                path for path in output["matched_source_files"] if path.endswith(".py")
            )
            expected_configs = sorted(
                path
                for path in output["matched_source_files"]
                if not path.endswith(".py")
            )
            self.assertEqual(output["python_ast_parsed"], expected_python)
            self.assertEqual(output["bounded_config_parsed"], expected_configs)

    def test_call_graph_tamper_is_rejected(self):
        def broken_adapter():
            executor._assert_function(
                executor.VIA_SERVER,
                "generate_captions",
                calls=("not.a.real.call",),
            )
            return [], [], {}

        with mock.patch.dict(
            executor.ADAPTERS,
            {"live_captions_cross_layer": broken_adapter},
        ):
            with self.assertRaisesRegex(
                executor.QualificationError, "AST contract failed"
            ):
                executor.execute([EXPECTED_IDS[0]])

    def test_bounded_yaml_and_logstash_parsers_fail_closed(self):
        original = executor._read_bytes

        def broken_yaml(path, *args, **kwargs):
            if path == executor.LVS_CONFIG:
                return b"functions: {}\ncontext_manager: {}\n"
            return original(path, *args, **kwargs)

        with mock.patch.object(executor, "_read_bytes", side_effect=broken_yaml):
            with self.assertRaisesRegex(
                executor.QualificationError, "YAML function missing"
            ):
                executor._assert_lvs_yaml()

        def broken_logstash(path, *args, **kwargs):
            if path == executor.LOGSTASH:
                return b"input {}\noutput {}\n"
            return original(path, *args, **kwargs)

        with mock.patch.object(executor, "_read_bytes", side_effect=broken_logstash):
            with self.assertRaisesRegex(
                executor.QualificationError, "Logstash contract"
            ):
                executor._assert_logstash_contract()

    def test_executor_has_no_forbidden_imports_or_process_calls(self):
        source = (PACKAGE / "executor.py").read_text()
        tree = ast.parse(source)
        forbidden_roots = {
            "subprocess",
            "socket",
            "requests",
            "urllib",
            "docker",
            "boto3",
            "httpx",
            "aiohttp",
        }
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertFalse(imported & forbidden_roots)
        for forbidden in (
            "os.system",
            "Popen",
            "Path.write_",
            "urlopen(",
            "requests.",
            "docker.",
        ):
            self.assertNotIn(forbidden, source)

    def test_no_repository_inputs_are_modified_by_execution(self):
        paths = {
            lock["path"]
            for case in self.inventory["cases"]
            for lock in case["source_locks"]
        }
        paths.update(
            spec["path"] for spec in self.inventory["previous_candidate_inventories"]
        )
        paths.update(
            [
                self.inventory["source_plan"]["path"],
                self.inventory["source_manifest"]["path"],
            ]
        )

        def digests():
            return {
                path: hashlib.sha256(
                    (executor.REPO_ROOT / path).read_bytes()
                ).hexdigest()
                for path in paths
            }

        before = digests()
        executor.execute()
        self.assertEqual(digests(), before)


if __name__ == "__main__":
    unittest.main()
