#!/usr/bin/env python3
"""Adversarial tests for the candidate-only VIOS UI/NAT wave six."""

from __future__ import annotations

import ast
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import unittest
from pathlib import Path
from unittest import mock

import jsonschema


PACKAGE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "advertised_entry_executor_wave6", PACKAGE / "executor.py"
)
assert SPEC and SPEC.loader
executor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(executor)

EXPECTED_IDS = [
    "manifest-gap.vios-ui.00-vios-dashboard",
    "manifest-gap.vios-ui.01-sensor-and-stream-management",
    "manifest-gap.vios-ui.02-recording-schedules",
    "manifest-gap.vios-ui.03-media-management-upload",
    "manifest-gap.vios-ui.04-live-replay-video-wall",
    "manifest-gap.vios-ui.05-qos-system-stream-stats",
    "manifest-gap.vios-ui.06-debug-and-playback-automation",
    "manifest-gap.agent-and-mcp-apis.00-nat-generate-chat",
]


class AdvertisedEntryExecutorWave6Tests(unittest.TestCase):
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
        self.assertEqual(len(predecessor_ids), 63)
        self.assertFalse(predecessor_ids & set(EXPECTED_IDS))
        self.assertEqual(63 + 8, 71)
        self.assertEqual(87 - 71, 16)

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

    def test_results_preserve_static_candidate_only_boundary(self):
        self.assertTrue(self.result["candidate_only"])
        self.assertEqual(self.result["runtime_evidence"], [])
        self.assertEqual(
            self.result["official_capability_effect"], "none_candidate_only"
        )
        for item in self.result["results"]:
            self.assertEqual(item["observation"], "observed_static_source_contract")
            self.assertEqual(item["runtime_evidence"], [])
            self.assertEqual(item["official_capability_effect"], "none_candidate_only")
            output = item["semantic_output"]
            self.assertEqual(
                output["contract_scope"],
                "exact-digest-locked-ui-and-nat-static-source-contract-only",
            )
            self.assertGreaterEqual(len(output["contract_edges"]), 2)
            self.assertGreaterEqual(len(output["semantic_assertions"]), 3)
            for field in (
                "browser_executed",
                "api_executed",
                "service_executed",
                "ui_render_proven",
                "backend_state_correlated",
                "request_response_proven",
                "service_readiness_proven",
            ):
                self.assertFalse(output[field])
            self.assertEqual(output["real_file_writes"], 0)
            self.assertNotIn("passed_current", json.dumps(item))

    def test_route_state_is_honest_and_exact(self):
        states = {
            item["entry_id"]: item["semantic_output"]["route_state"]
            for item in self.result["results"]
        }
        for entry_id in EXPECTED_IDS[:4]:
            self.assertEqual(states[entry_id], "mounted_source_route")
        for entry_id in EXPECTED_IDS[4:7]:
            self.assertEqual(states[entry_id], "placeholder_source_route")
        self.assertEqual(states[EXPECTED_IDS[7]], "inherited_nat_static_inventory")

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
            mock.patch.dict(
                executor.ADAPTERS, {"vios_dashboard_source_contract": adapter}
            ),
        ):
            with self.assertRaisesRegex(
                executor.QualificationError, "source lock mismatch"
            ):
                executor.execute([EXPECTED_IDS[0]])
        adapter.assert_not_called()

    def test_mounted_route_semantic_mutation_is_rejected(self):
        original = executor._read_bytes

        def tampered(path, *args, **kwargs):
            data = original(path, *args, **kwargs)
            if path == executor.ROUTES:
                return data.replace(
                    b"{ path: 'dashboard', element: <VSTDashboard /> }",
                    b"{ path: 'dashboard', element: <></> }",
                )
            return data

        with mock.patch.object(executor, "_read_bytes", side_effect=tampered):
            with self.assertRaisesRegex(
                executor.QualificationError, "semantic source fragment missing"
            ):
                executor._dashboard()

    def test_placeholder_route_cannot_be_silently_promoted(self):
        original = executor._read_bytes

        def tampered(path, *args, **kwargs):
            data = original(path, *args, **kwargs)
            if path == executor.ROUTES:
                return data.replace(
                    b"{ path: 'live-streams', element: <></> }",
                    b"{ path: 'live-streams', element: <LiveStream /> }",
                )
            return data

        with mock.patch.object(executor, "_read_bytes", side_effect=tampered):
            with self.assertRaisesRegex(
                executor.QualificationError, "semantic source fragment missing"
            ):
                executor._live_replay_wall()

    def test_placeholder_route_rejects_hidden_component_import(self):
        original = executor._read_bytes

        def tampered(path, *args, **kwargs):
            data = original(path, *args, **kwargs)
            if path == executor.ROUTES:
                return (
                    data + b"\nimport LiveStream from '../../pages/vst/LiveStream';\n"
                )
            return data

        with mock.patch.object(executor, "_read_bytes", side_effect=tampered):
            with self.assertRaisesRegex(
                executor.QualificationError, "unexpected source fragment"
            ):
                executor._live_replay_wall()

    def test_nat_operation_inventory_is_parsed_and_fail_closed(self):
        original = executor._read_bytes
        agent = json.loads(original(executor.AGENT_EXPECTED))
        agent["operations"] = [
            item for item in agent["operations"] if item.get("path") != "/generate"
        ]
        agent["declared_operation_count"] = len(agent["operations"])

        def tampered(path, *args, **kwargs):
            if path == executor.AGENT_EXPECTED:
                return json.dumps(agent).encode()
            return original(path, *args, **kwargs)

        with mock.patch.object(executor, "_read_bytes", side_effect=tampered):
            with self.assertRaisesRegex(
                executor.QualificationError,
                "static agent API inventory identity drifted",
            ):
                executor._nat_generate_chat()

    def test_nat_version_or_inherited_route_mutation_is_rejected(self):
        original = executor._read_bytes

        def tampered(path, *args, **kwargs):
            data = original(path, *args, **kwargs)
            if path == executor.AGENT_WORKER:
                return data.replace(
                    b"await super().add_routes(app, builder)",
                    b"# inherited routes removed",
                )
            return data

        with mock.patch.object(executor, "_read_bytes", side_effect=tampered):
            with self.assertRaisesRegex(
                executor.QualificationError, "semantic source fragment missing"
            ):
                executor._nat_generate_chat()

    def test_inventory_schema_rejects_policy_denominator_scope_and_count_tamper(self):
        validator = jsonschema.Draft202012Validator(self.inventory_schema)
        mutations = (
            lambda value: value["denominator"].__setitem__("entries_left_open", 15),
            lambda value: value["policy"].__setitem__("browser_allowed", True),
            lambda value: value["policy"].__setitem__("can_mark_passed_current", True),
            lambda value: value["cases"][0].__setitem__(
                "evidence_scope", "runtime: rendered"
            ),
            lambda value: value["cases"].pop(),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                altered = copy.deepcopy(self.inventory)
                mutation(altered)
                self.assertTrue(list(validator.iter_errors(altered)))

    def test_result_schema_rejects_runtime_and_official_effect_tamper(self):
        validator = jsonschema.Draft202012Validator(self.result_schema)
        mutations = (
            lambda value: value["results"][0]["semantic_output"].__setitem__(
                "browser_executed", True
            ),
            lambda value: value["results"][0]["semantic_output"].__setitem__(
                "ui_render_proven", True
            ),
            lambda value: value["results"][0].__setitem__(
                "official_capability_effect", "passed_current"
            ),
            lambda value: value["results"][0].__setitem__(
                "observation", "runtime_pass"
            ),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                altered = copy.deepcopy(self.result)
                mutation(altered)
                self.assertTrue(list(validator.iter_errors(altered)))

    def test_executor_has_no_network_lifecycle_subprocess_or_write_primitives(self):
        tree = ast.parse((PACKAGE / "executor.py").read_text())
        forbidden_import_roots = {
            "aiohttp",
            "docker",
            "httpx",
            "os",
            "requests",
            "shutil",
            "socket",
            "subprocess",
            "urllib",
        }
        forbidden_calls = {
            "open",
            "write_bytes",
            "write_text",
            "mkdir",
            "unlink",
            "rename",
            "system",
            "popen",
            "run",
            "Popen",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                self.assertFalse(
                    {alias.name.split(".")[0] for alias in node.names}
                    & forbidden_import_roots
                )
            if isinstance(node, ast.ImportFrom) and node.module:
                self.assertNotIn(node.module.split(".")[0], forbidden_import_roots)
            if isinstance(node, ast.Call):
                func = node.func
                name = (
                    func.id
                    if isinstance(func, ast.Name)
                    else func.attr
                    if isinstance(func, ast.Attribute)
                    else ""
                )
                self.assertNotIn(name, forbidden_calls)


if __name__ == "__main__":
    unittest.main()
