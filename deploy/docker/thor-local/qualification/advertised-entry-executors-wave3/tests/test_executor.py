#!/usr/bin/env python3
"""Adversarial tests for advertised-entry executor wave three."""

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
SPEC = importlib.util.spec_from_file_location("advertised_entry_executor_wave3", PACKAGE / "executor.py")
assert SPEC and SPEC.loader
executor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(executor)

EXPECTED_IDS = [
    "manifest-gap.video-summarization-live.05-sse-mcp-server",
    "manifest-gap.rt-vlm-media.08-categories",
    "manifest-gap.rt-vlm-media.10-audio-transcript",
    "manifest-gap.rt-vlm-api.00-openai-compatible-chat-completions",
    "manifest-gap.rt-vlm-api.01-text-only-chat",
    "manifest-gap.rt-vlm-api.02-multimodal-multi-turn-chat",
    "manifest-gap.rt-vlm-api.03-token-sse",
    "manifest-gap.rt-vlm-api.04-original-stream-api",
    "manifest-gap.rt-vlm-api.05-cv-compatible-stream-api",
    "manifest-gap.rt-vlm-api.06-file-api",
    "manifest-gap.rt-vlm-api.07-health-metadata-models-metrics",
    "manifest-gap.rt-vlm-models.04-remote-openai-compatible-endpoint",
    "manifest-gap.rt-vlm-performance-observability.03-vllm-tuning",
    "manifest-gap.rt-vlm-performance-observability.05-kafka-redis-error-publication",
    "manifest-gap.rt-vlm-performance-observability.06-prometheus-and-opentelemetry",
    "manifest-gap.rt-cv-3d-mv3dt.04-compose-deployment",
    "manifest-gap.agent-and-mcp-apis.01-health",
    "manifest-gap.agent-and-mcp-apis.02-upload-handshake-and-completion",
    "manifest-gap.agent-and-mcp-apis.03-video-delete",
    "manifest-gap.agent-and-mcp-apis.04-rtsp-add-delete",
    "manifest-gap.agent-and-mcp-apis.05-va-mcp",
    "manifest-gap.agent-and-mcp-apis.06-lvs-mcp",
    "manifest-gap.agent-and-mcp-apis.07-vios-mcp",
]


class AdvertisedEntryExecutorWave3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inventory = json.loads((PACKAGE / "inventory.json").read_text())
        cls.inventory_schema = json.loads((PACKAGE / "inventory.schema.json").read_text())
        cls.result_schema = json.loads((PACKAGE / "result.schema.json").read_text())
        cls.result = executor.execute()

    def test_inventory_and_result_validate_against_schemas(self):
        jsonschema.Draft202012Validator(self.inventory_schema).validate(self.inventory)
        jsonschema.Draft202012Validator(self.result_schema).validate(self.result)

    def test_exact_denominator_order_and_predecessor_disjointness(self):
        self.assertEqual(
            self.inventory["denominator"],
            {
                "advertised_gap_entries": 87,
                "previously_selected_candidate_entries": 29,
                "prior_open_entries": 58,
                "selected_candidate_entries": 23,
                "entries_left_open": 35,
            },
        )
        self.assertEqual([case["entry_id"] for case in self.inventory["cases"]], EXPECTED_IDS)
        self.assertEqual([item["entry_id"] for item in self.result["results"]], EXPECTED_IDS)
        predecessor_ids = set()
        for spec in self.inventory["previous_candidate_inventories"]:
            previous = json.loads((executor.REPO_ROOT / spec["path"]).read_text())
            ids = {case["entry_id"] for case in previous["cases"]}
            self.assertFalse(ids & predecessor_ids)
            predecessor_ids.update(ids)
        self.assertEqual(len(predecessor_ids), 29)
        self.assertFalse(predecessor_ids & set(EXPECTED_IDS))

    def test_results_are_source_contract_candidates_only(self):
        self.assertTrue(self.result["candidate_only"])
        self.assertEqual(self.result["runtime_evidence"], [])
        self.assertEqual(self.result["official_capability_effect"], "none_candidate_only")
        for item in self.result["results"]:
            self.assertEqual(item["observation"], "observed_match")
            self.assertEqual(item["runtime_evidence"], [])
            self.assertEqual(item["official_capability_effect"], "none_candidate_only")
            self.assertTrue(item["evidence_scope"].startswith("subset:"))
            output = item["semantic_output"]
            self.assertEqual(output["contract_scope"], "exact-digest-locked-source-fragments-only")
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
                self.assertEqual([item["entry_id"] for item in result["results"]], [entry_id])

    def test_unknown_and_duplicate_selections_are_rejected(self):
        with self.assertRaises(executor.QualificationError):
            executor.execute(["manifest-gap.not-real"])
        with self.assertRaisesRegex(executor.QualificationError, "duplicate --case"):
            executor.execute([EXPECTED_IDS[0], EXPECTED_IDS[0]])

    def test_duplicate_inventory_key_is_rejected_before_adapter(self):
        raw = (PACKAGE / "inventory.json").read_text()
        duplicate = raw.replace('"schema_version": 1,', '"schema_version": 1,\n  "schema_version": 1,', 1)
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "inventory.json"
            path.write_text(duplicate)
            adapter = mock.Mock()
            with mock.patch.object(executor, "INVENTORY_PATH", path), mock.patch.dict(
                executor.ADAPTERS, {"lvs_sse_mcp_source": adapter}
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
            executor.ADAPTERS, {"lvs_sse_mcp_source": adapter}
        ):
            with self.assertRaisesRegex(executor.QualificationError, "source lock mismatch"):
                executor.execute([EXPECTED_IDS[0]])
        adapter.assert_not_called()

    def test_inventory_cannot_read_outside_repository(self):
        inventory = copy.deepcopy(self.inventory)
        inventory["source_plan"]["path"] = "../../etc/passwd"
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "inventory.json"
            path.write_text(json.dumps(inventory))
            with mock.patch.object(executor, "INVENTORY_PATH", path):
                with self.assertRaises(executor.QualificationError):
                    executor.execute([EXPECTED_IDS[0]])

    def test_exact_plan_manifest_and_predecessor_inputs_are_code_locked(self):
        mutations = (
            lambda value: value["source_plan"].__setitem__("raw_sha256", "0" * 64),
            lambda value: value["source_manifest"].__setitem__("raw_sha256", "0" * 64),
            lambda value: value["previous_candidate_inventories"][0].__setitem__(
                "raw_sha256", "0" * 64
            ),
        )
        for mutate in mutations:
            inventory = copy.deepcopy(self.inventory)
            mutate(inventory)
            with tempfile.TemporaryDirectory() as name:
                path = Path(name) / "inventory.json"
                path.write_text(json.dumps(inventory))
                with mock.patch.object(executor, "INVENTORY_PATH", path):
                    with self.assertRaisesRegex(executor.QualificationError, "drifted"):
                        executor.execute([EXPECTED_IDS[0]])

    def test_bounded_adapters_sources_and_fragments_are_exact(self):
        for case in self.inventory["cases"]:
            pointer, adapter_id, source_paths = executor.EXPECTED_CASE_BINDINGS[case["entry_id"]]
            self.assertEqual(case["manifest_pointer"], pointer)
            self.assertEqual(case["adapter_id"], adapter_id)
            self.assertEqual({lock["path"] for lock in case["source_locks"]}, source_paths)
            self.assertEqual(set(executor.CONTRACT_FRAGMENTS[adapter_id]), source_paths)

    def test_schema_rejects_denominator_policy_scope_path_and_count_tamper(self):
        validator = jsonschema.Draft202012Validator(self.inventory_schema)
        mutations = (
            lambda value: value["denominator"].__setitem__("entries_left_open", 34),
            lambda value: value["policy"].__setitem__("can_mark_passed_current", True),
            lambda value: value["policy"]["runtime_evidence"].append("fake"),
            lambda value: value["cases"][0].__setitem__("evidence_scope", "whole workflow"),
            lambda value: value["cases"][0]["source_locks"][0].__setitem__("path", "../../etc/passwd"),
            lambda value: value["cases"].pop(),
        )
        for mutate in mutations:
            candidate = copy.deepcopy(self.inventory)
            mutate(candidate)
            self.assertTrue(list(validator.iter_errors(candidate)))

    def test_result_schema_rejects_runtime_readiness_and_official_effect_tamper(self):
        validator = jsonschema.Draft202012Validator(self.result_schema)
        candidates = []
        candidate = copy.deepcopy(self.result)
        candidate["runtime_evidence"] = ["fake"]
        candidates.append(candidate)
        candidate = copy.deepcopy(self.result)
        candidate["official_capability_effect"] = "passed_current"
        candidates.append(candidate)
        candidate = copy.deepcopy(self.result)
        candidate["results"][0]["semantic_output"]["service_readiness_proven"] = True
        candidates.append(candidate)
        candidate = copy.deepcopy(self.result)
        candidate["results"][0]["semantic_output"]["model_availability_proven"] = True
        candidates.append(candidate)
        for candidate in candidates:
            self.assertTrue(list(validator.iter_errors(candidate)))

    def test_python_sources_are_ast_parsed_and_non_python_sources_are_not_claimed(self):
        for item in self.result["results"]:
            output = item["semantic_output"]
            expected = sorted(path for path in output["matched_source_files"] if path.endswith(".py"))
            self.assertEqual(output["python_ast_parsed"], expected)

    def test_fragment_contract_tamper_is_rejected(self):
        contract = copy.deepcopy(executor.CONTRACT_FRAGMENTS)
        contract["agent_health_source"][executor.AGENT_WORKER].append("not-a-real-source-fragment")
        with mock.patch.object(executor, "CONTRACT_FRAGMENTS", contract):
            with self.assertRaisesRegex(executor.QualificationError, "required source fragment missing"):
                executor.execute(["manifest-gap.agent-and-mcp-apis.01-health"])

    def test_executor_has_no_forbidden_imports_or_process_calls(self):
        source = (PACKAGE / "executor.py").read_text()
        tree = ast.parse(source)
        forbidden_roots = {"subprocess", "socket", "requests", "urllib", "docker", "boto3", "httpx"}
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertFalse(imported & forbidden_roots)
        for forbidden in ("os.system", "Popen", "Path.write_", "urlopen(", "requests.", "docker."):
            self.assertNotIn(forbidden, source)

    def test_no_repository_inputs_are_modified_by_execution(self):
        paths = {
            lock["path"]
            for case in self.inventory["cases"]
            for lock in case["source_locks"]
        }
        paths.update(spec["path"] for spec in self.inventory["previous_candidate_inventories"])
        paths.update([self.inventory["source_plan"]["path"], self.inventory["source_manifest"]["path"]])

        def digests():
            return {
                path: hashlib.sha256((executor.REPO_ROOT / path).read_bytes()).hexdigest()
                for path in paths
            }

        before = digests()
        executor.execute()
        self.assertEqual(digests(), before)


if __name__ == "__main__":
    unittest.main()
