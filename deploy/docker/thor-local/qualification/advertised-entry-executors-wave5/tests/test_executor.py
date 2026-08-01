#!/usr/bin/env python3
"""Adversarial tests for the candidate-only VIOS codec/audio wave five."""

from __future__ import annotations

import ast
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import jsonschema


PACKAGE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "advertised_entry_executor_wave5", PACKAGE / "executor.py"
)
assert SPEC and SPEC.loader
executor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(executor)

EXPECTED_IDS = [
    "manifest-gap.vios-codecs-audio.00-b-frame-handling",
    "manifest-gap.vios-codecs-audio.01-hevc-multislice-rfc7798",
    "manifest-gap.vios-codecs-audio.02-h-264-h-265",
    "manifest-gap.vios-codecs-audio.03-audio-recording",
    "manifest-gap.vios-codecs-audio.04-audio-rtsp-republish",
    "manifest-gap.vios-codecs-audio.05-cpu-multimedia-support",
]


class AdvertisedEntryExecutorWave5Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inventory = json.loads((PACKAGE / "inventory.json").read_text())
        cls.inventory_schema = json.loads(
            (PACKAGE / "inventory.schema.json").read_text()
        )
        cls.result_schema = json.loads((PACKAGE / "result.schema.json").read_text())
        cls.result = executor.execute()

    def test_inventory_and_result_validate_against_strict_schemas(self):
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
        for lock in self.inventory["previous_candidate_inventories"]:
            previous = json.loads((executor.REPO_ROOT / lock["path"]).read_text())
            ids = {case["entry_id"] for case in previous["cases"]}
            self.assertFalse(ids & predecessor_ids)
            predecessor_ids.update(ids)
        self.assertEqual(len(predecessor_ids), 57)
        self.assertFalse(predecessor_ids & set(EXPECTED_IDS))
        self.assertEqual(57 + 6, 63)
        self.assertEqual(87 - 63, 24)

    def test_plan_manifest_predecessors_and_inventory_are_code_locked(self):
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

    def test_case_bindings_and_source_sets_are_exact(self):
        for case in self.inventory["cases"]:
            pointer, adapter_id, source_paths = executor.EXPECTED_CASE_BINDINGS[
                case["entry_id"]
            ]
            self.assertEqual(case["manifest_pointer"], pointer)
            self.assertEqual(case["adapter_id"], adapter_id)
            self.assertEqual(
                {lock["path"] for lock in case["source_locks"]}, source_paths
            )

    def test_results_are_static_candidates_only(self):
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
                "exact-digest-locked-vios-source-and-offline-package-contract-only",
            )
            self.assertGreaterEqual(len(output["contract_edges"]), 2)
            self.assertGreaterEqual(len(output["semantic_assertions"]), 3)
            for field in (
                "runtime_executed",
                "codec_fixture_executed",
                "rtsp_session_executed",
                "recording_executed",
                "cpu_pipeline_executed",
                "service_readiness_proven",
            ):
                self.assertFalse(output[field])
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

    def test_list_is_exact_and_rejects_case_combination(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(executor.main(["--list"]), 0)
        self.assertEqual(output.getvalue().splitlines(), EXPECTED_IDS)
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stderr(io.StringIO()):
                executor.main(["--list", "--case", EXPECTED_IDS[0]])

    def test_duplicate_json_key_and_unsafe_paths_are_rejected(self):
        with self.assertRaisesRegex(executor.QualificationError, "duplicate JSON key"):
            executor._strict_json_bytes(b'{"x":1,"x":2}', "duplicate fixture")
        for path in ("../../etc/passwd", "/etc/passwd"):
            with self.assertRaisesRegex(
                executor.QualificationError, "unsafe repository path"
            ):
                executor._read_bytes(path)

    def test_source_tamper_fails_before_adapter(self):
        original = executor._read_bytes
        target = self.inventory["cases"][0]["source_locks"][0]["path"]

        def tampered(path, *args, **kwargs):
            data = original(path, *args, **kwargs)
            return data + b"\n// tampered" if path == target else data

        adapter = mock.Mock()
        with (
            mock.patch.object(executor, "_read_bytes", side_effect=tampered),
            mock.patch.dict(executor.ADAPTERS, {"b_frame_contract": adapter}),
        ):
            with self.assertRaisesRegex(
                executor.QualificationError, "source lock mismatch"
            ):
                executor.execute([EXPECTED_IDS[0]])
        adapter.assert_not_called()

    def test_semantic_mutation_is_rejected_by_adapter(self):
        original = executor._read_bytes

        def tampered(path, *args, **kwargs):
            data = original(path, *args, **kwargs)
            if path == executor.BYTE_STREAM:
                return data.replace(
                    b"return (content[2] & 0x80) == 0;",
                    b"return false; // removed semantic branch",
                )
            return data

        with mock.patch.object(executor, "_read_bytes", side_effect=tampered):
            with self.assertRaisesRegex(
                executor.QualificationError, "semantic source fragment missing"
            ):
                executor._hevc_multislice()

    def test_structured_config_and_package_contracts_fail_closed(self):
        original = executor._read_bytes

        def bad_config(path, *args, **kwargs):
            if path == executor.VST_CONFIG:
                return b'{"data":{"supported_video_codecs":["h264"]}}'
            return original(path, *args, **kwargs)

        with mock.patch.object(executor, "_read_bytes", side_effect=bad_config):
            with self.assertRaisesRegex(
                executor.QualificationError, "allowlist drifted"
            ):
                executor._vios_config()

        lock = json.loads(original(executor.CODEC_LOCK))
        lock["package_count"] = 58

        def bad_lock(path, *args, **kwargs):
            if path == executor.CODEC_LOCK:
                return json.dumps(lock).encode()
            return original(path, *args, **kwargs)

        with mock.patch.object(executor, "_read_bytes", side_effect=bad_lock):
            with self.assertRaisesRegex(executor.QualificationError, "59-package"):
                executor._codec_package_contract()

    def test_dockerfiles_fail_closed_on_network_package_operation(self):
        original = executor._read_bytes

        def tampered(path, *args, **kwargs):
            data = original(path, *args, **kwargs)
            if path == executor.DOCKERFILE_VIOS:
                return data + b"\nRUN apt-get update\n"
            return data

        with mock.patch.object(executor, "_read_bytes", side_effect=tampered):
            with self.assertRaisesRegex(
                executor.QualificationError, "network/package operation"
            ):
                executor._dockerfile_contract(executor.DOCKERFILE_VIOS)

    def test_inventory_schema_rejects_policy_denominator_scope_and_count_tamper(self):
        validator = jsonschema.Draft202012Validator(self.inventory_schema)
        mutations = (
            lambda value: value["denominator"].__setitem__("entries_left_open", 23),
            lambda value: value["policy"].__setitem__("can_mark_passed_current", True),
            lambda value: value["policy"]["runtime_evidence"].append("fake"),
            lambda value: value["cases"][0].__setitem__("evidence_scope", "runtime"),
            lambda value: value["cases"][0]["source_locks"][0].__setitem__(
                "path", "../../etc/passwd"
            ),
            lambda value: value["cases"].pop(),
        )
        for mutate in mutations:
            candidate = copy.deepcopy(self.inventory)
            mutate(candidate)
            self.assertTrue(list(validator.iter_errors(candidate)))

    def test_result_schema_rejects_every_runtime_or_official_promotion(self):
        validator = jsonschema.Draft202012Validator(self.result_schema)
        mutations = (
            lambda value: value["runtime_evidence"].append("fake"),
            lambda value: value.__setitem__(
                "official_capability_effect", "passed_current"
            ),
            lambda value: value["results"][0]["semantic_output"].__setitem__(
                "runtime_executed", True
            ),
            lambda value: value["results"][0]["semantic_output"].__setitem__(
                "codec_fixture_executed", True
            ),
            lambda value: value["results"][0]["semantic_output"].__setitem__(
                "rtsp_session_executed", True
            ),
            lambda value: value["results"][0]["semantic_output"].__setitem__(
                "recording_executed", True
            ),
            lambda value: value["results"][0]["semantic_output"].__setitem__(
                "cpu_pipeline_executed", True
            ),
        )
        for mutate in mutations:
            candidate = copy.deepcopy(self.result)
            mutate(candidate)
            self.assertTrue(list(validator.iter_errors(candidate)))

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

    def test_source_classification_is_exact(self):
        for item in self.result["results"]:
            output = item["semantic_output"]
            expected_cpp = sorted(
                path
                for path in output["matched_source_files"]
                if path.endswith((".cpp", ".h", ".hh"))
            )
            expected_config = sorted(
                path
                for path in output["matched_source_files"]
                if not path.endswith((".cpp", ".h", ".hh"))
            )
            self.assertEqual(output["bounded_cpp_parsed"], expected_cpp)
            self.assertEqual(output["bounded_config_parsed"], expected_config)

    def test_executor_has_no_forbidden_imports_or_process_write_calls(self):
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
            "os",
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
            lock["path"] for lock in self.inventory["previous_candidate_inventories"]
        )
        paths.update(
            (
                self.inventory["source_plan"]["path"],
                self.inventory["source_manifest"]["path"],
            )
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
