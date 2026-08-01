# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jsonschema import Draft202012Validator


LANE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("wave7_executor", LANE / "executor.py")
assert SPEC is not None and SPEC.loader is not None
executor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(executor)


class Wave7ExecutorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.inventory = json.loads(
            (LANE / "inventory.json").read_text(encoding="utf-8")
        )
        cls.inventory_schema = json.loads(
            (LANE / "inventory.schema.json").read_text(encoding="utf-8")
        )
        cls.result_schema = json.loads(
            (LANE / "result.schema.json").read_text(encoding="utf-8")
        )

    def _copy_inputs(self, root: Path) -> list[str]:
        paths = {
            self.inventory["source_plan"]["path"],
            self.inventory["source_manifest"]["path"],
            self.inventory["live_official_capabilities"]["path"],
            self.inventory["live_capability_oracles"]["path"],
            self.inventory["separate_detection_map_candidate"]["path"],
            *(
                item["path"]
                for item in self.inventory["previous_candidate_inventories"]
            ),
            *(
                lock["path"]
                for case in self.inventory["cases"]
                for lock in case["source_locks"]
            ),
        }
        for relative in paths:
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(executor.REPO_ROOT / relative, destination)
        return sorted(paths)

    def test_checked_in_candidate_executes_with_exact_nonadvancing_partition(
        self,
    ) -> None:
        result = executor.execute()
        self.assertEqual(len(result["observations"]), 11)
        self.assertEqual(len(result["blocked_entries"]), 4)
        self.assertEqual(result["denominator"]["candidate_total"], 83)
        self.assertEqual(result["denominator"]["official_open_entries"], 87)
        self.assertIs(result["candidate_only"], True)
        self.assertIs(result["can_mark_passed_current"], False)
        self.assertEqual(result["official_capability_effect"], "none_candidate_only")
        self.assertEqual(result["runtime_evidence"], [])
        self.assertTrue(
            all(
                row["full_oracle_status"] == "open_unexecuted"
                for row in result["observations"]
            )
        )
        self.assertTrue(
            all(
                row["candidate_materialized"] is False
                for row in result["blocked_entries"]
            )
        )
        Draft202012Validator(self.result_schema).validate(result)

    def test_denominator_is_exact_disjoint_87_entry_partition(self) -> None:
        plan = json.loads(
            (executor.REPO_ROOT / self.inventory["source_plan"]["path"]).read_text()
        )
        previous: set[str] = set()
        for lock in self.inventory["previous_candidate_inventories"]:
            prior = json.loads((executor.REPO_ROOT / lock["path"]).read_text())
            ids = {row["entry_id"] for row in prior["cases"]}
            self.assertFalse(previous & ids)
            previous |= ids
        detection = self.inventory["separate_detection_map_candidate"]["entry_id"]
        cases = {row["entry_id"] for row in self.inventory["cases"]}
        blocked = {row["entry_id"] for row in self.inventory["blocked_entries"]}
        self.assertEqual((len(previous), len(cases), len(blocked)), (71, 11, 4))
        self.assertFalse(previous & cases)
        self.assertFalse(previous & blocked)
        self.assertFalse(cases & blocked)
        self.assertNotIn(detection, previous | cases | blocked)
        self.assertEqual(
            previous | {detection} | cases | blocked,
            {row["entry_id"] for row in plan["entries"]},
        )

    def test_all_locked_inputs_and_schemas_are_raw_sha_bound(self) -> None:
        self.assertEqual(
            hashlib.sha256((LANE / "inventory.json").read_bytes()).hexdigest(),
            executor.EXPECTED_INVENTORY_SHA256,
        )
        self.assertEqual(
            hashlib.sha256((LANE / "inventory.schema.json").read_bytes()).hexdigest(),
            executor.EXPECTED_INVENTORY_SCHEMA_SHA256,
        )
        self.assertEqual(
            hashlib.sha256((LANE / "result.schema.json").read_bytes()).hexdigest(),
            executor.EXPECTED_RESULT_SCHEMA_SHA256,
        )
        for lock in [
            self.inventory["source_plan"],
            self.inventory["source_manifest"],
            self.inventory["live_official_capabilities"],
            self.inventory["live_capability_oracles"],
            *self.inventory["previous_candidate_inventories"],
            self.inventory["separate_detection_map_candidate"],
        ]:
            self.assertEqual(
                hashlib.sha256(
                    (executor.REPO_ROOT / lock["path"]).read_bytes()
                ).hexdigest(),
                lock["raw_sha256"],
                lock["path"],
            )

    def test_every_source_lock_is_rehashed_and_fails_closed(self) -> None:
        unique_sources = sorted(
            {
                lock["path"]
                for case in self.inventory["cases"]
                for lock in case["source_locks"]
            }
        )
        self.assertGreaterEqual(len(unique_sources), 12)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._copy_inputs(root)
            for relative in unique_sources:
                with self.subTest(relative=relative):
                    path = root / relative
                    original = path.read_bytes()
                    path.write_bytes(original + b"\nwave7-source-tamper")
                    with self.assertRaisesRegex(
                        executor.QualificationError, "source digest mismatch"
                    ):
                        executor.execute(root)
                    path.write_bytes(original)

    def test_missing_semantic_fragment_fails_after_reviewed_relock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._copy_inputs(root)
            inventory = copy.deepcopy(self.inventory)
            case = inventory["cases"][0]
            assertion = case["source_assertions"][0]
            assertion["fragments"][0] = "fragment-that-does-not-exist"
            raw = (json.dumps(inventory, indent=2) + "\n").encode()
            inventory_path = root / "inventory.json"
            inventory_path.write_bytes(raw)
            with (
                mock.patch.object(executor, "INVENTORY_PATH", inventory_path),
                mock.patch.object(
                    executor,
                    "EXPECTED_INVENTORY_SHA256",
                    hashlib.sha256(raw).hexdigest(),
                ),
            ):
                with self.assertRaisesRegex(
                    executor.QualificationError, "semantic source fragment missing"
                ):
                    executor.execute(root)

    def test_inventory_raw_tamper_fails_before_schema_or_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "inventory.json"
            path.write_bytes((LANE / "inventory.json").read_bytes() + b" ")
            with mock.patch.object(executor, "INVENTORY_PATH", path):
                with self.assertRaisesRegex(
                    executor.QualificationError, "inventory raw digest mismatch"
                ):
                    executor.execute()

    def test_plan_manifest_predecessor_and_detection_raw_tamper_fail_closed(
        self,
    ) -> None:
        targets = [
            self.inventory["source_plan"]["path"],
            self.inventory["source_manifest"]["path"],
            self.inventory["live_official_capabilities"]["path"],
            self.inventory["live_capability_oracles"]["path"],
            *(
                lock["path"]
                for lock in self.inventory["previous_candidate_inventories"]
            ),
            self.inventory["separate_detection_map_candidate"]["path"],
        ]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._copy_inputs(root)
            for relative in targets:
                with self.subTest(relative=relative):
                    path = root / relative
                    original = path.read_bytes()
                    path.write_bytes(original + b" ")
                    with self.assertRaisesRegex(
                        executor.QualificationError, "raw digest mismatch"
                    ):
                        executor.execute(root)
                    path.write_bytes(original)

    def test_source_symlink_and_path_escape_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._copy_inputs(root)
            relative = self.inventory["cases"][0]["source_locks"][0]["path"]
            path = root / relative
            outside = root / "outside.txt"
            outside.write_bytes(path.read_bytes())
            path.unlink()
            path.symlink_to(outside)
            with self.assertRaisesRegex(
                executor.QualificationError, "contains a symlink"
            ):
                executor.execute(root)
        with self.assertRaisesRegex(
            executor.QualificationError, "unsafe repository path"
        ):
            executor._safe_repo_path(executor.REPO_ROOT, "../escape")

    def test_duplicate_json_and_additional_properties_are_rejected(self) -> None:
        with self.assertRaisesRegex(executor.QualificationError, "duplicate JSON key"):
            executor._strict_json_bytes(
                b'{"schema_version":1,"schema_version":2}', "dup"
            )
        inventory = copy.deepcopy(self.inventory)
        inventory["unexpected"] = True
        errors = list(
            Draft202012Validator(self.inventory_schema).iter_errors(inventory)
        )
        self.assertTrue(errors)

    def test_external_blockers_cannot_be_promoted_to_candidates(self) -> None:
        inventory = copy.deepcopy(self.inventory)
        inventory["cases"].append(inventory["blocked_entries"].pop())
        with self.assertRaisesRegex(
            executor.QualificationError, "candidate identity set drift"
        ):
            executor._verify_inventory_boundary(inventory)
        result = executor.execute()
        result["blocked_entries"][0]["candidate_materialized"] = True
        errors = list(Draft202012Validator(self.result_schema).iter_errors(result))
        self.assertTrue(errors)

    def test_runtime_or_candidate_promotion_is_schema_forbidden(self) -> None:
        result = executor.execute()
        for mutation in (
            lambda value: value.update(can_mark_passed_current=True),
            lambda value: value["runtime_evidence"].append({"result": "pass"}),
            lambda value: value["observations"][0].update(
                full_oracle_status="passed_current"
            ),
            lambda value: value.update(network_used=True),
            lambda value: value.update(warehouse_sample_bundle_used=True),
        ):
            with self.subTest(mutation=mutation):
                changed = copy.deepcopy(result)
                mutation(changed)
                self.assertTrue(
                    list(Draft202012Validator(self.result_schema).iter_errors(changed))
                )

    def test_nested_required_oracle_promotion_is_schema_forbidden(self) -> None:
        result = executor.execute()
        mutations = (
            lambda value: value["observations"][0]["required_oracle"].update(
                status="passed_current"
            ),
            lambda value: value["observations"][0]["required_oracle"][
                "runtime_evidence"
            ].append({"result": "pass"}),
            lambda value: value["observations"][0]["required_oracle"].update(
                type="external_optional_boundary"
            ),
            lambda value: value["blocked_entries"][0]["required_oracle"].update(
                status="passed_current"
            ),
            lambda value: value["blocked_entries"][0]["required_oracle"][
                "runtime_evidence"
            ].append({"result": "pass"}),
            lambda value: value["blocked_entries"][0]["required_oracle"].update(
                type="runtime_scale_benchmark"
            ),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                changed = copy.deepcopy(result)
                mutation(changed)
                self.assertTrue(
                    list(Draft202012Validator(self.result_schema).iter_errors(changed))
                )

    def test_all_87_proposed_ids_remain_absent_and_plan_oracles_open(self) -> None:
        plan = json.loads(
            (executor.REPO_ROOT / self.inventory["source_plan"]["path"]).read_text()
        )
        capabilities = json.loads(
            (
                executor.REPO_ROOT
                / self.inventory["live_official_capabilities"]["path"]
            ).read_text()
        )
        oracles = json.loads(
            (
                executor.REPO_ROOT / self.inventory["live_capability_oracles"]["path"]
            ).read_text()
        )
        proposed = {entry["proposed_capability"]["id"] for entry in plan["entries"]}
        self.assertEqual(len(proposed), 87)
        self.assertTrue(
            proposed.isdisjoint(row["id"] for row in capabilities["capabilities"])
        )
        self.assertTrue(
            proposed.isdisjoint(row["capability_id"] for row in oracles["oracles"])
        )
        self.assertTrue(
            all(
                entry["coverage_state"] == "open_missing_entry_capability_and_oracle"
                and entry["required_oracle"]["status"] == "open_unexecuted"
                and entry["required_oracle"]["runtime_evidence"] == []
                for entry in plan["entries"]
            )
        )

    def test_live_capability_or_oracle_promotion_fails_closed(self) -> None:
        plan = json.loads(
            (executor.REPO_ROOT / self.inventory["source_plan"]["path"]).read_text()
        )
        capabilities = json.loads(
            (
                executor.REPO_ROOT
                / self.inventory["live_official_capabilities"]["path"]
            ).read_text()
        )
        oracles = json.loads(
            (
                executor.REPO_ROOT / self.inventory["live_capability_oracles"]["path"]
            ).read_text()
        )
        proposed = plan["entries"][0]["proposed_capability"]["id"]

        changed_capabilities = copy.deepcopy(capabilities)
        changed_capabilities["capabilities"].append({"id": proposed})
        with self.assertRaisesRegex(
            executor.QualificationError, "capability was promoted live"
        ):
            executor._verify_live_open(plan, changed_capabilities, oracles)

        changed_oracles = copy.deepcopy(oracles)
        changed_oracles["oracles"].append({"capability_id": proposed})
        with self.assertRaisesRegex(
            executor.QualificationError, "oracle was materialized live"
        ):
            executor._verify_live_open(plan, capabilities, changed_oracles)

        changed_plan = copy.deepcopy(plan)
        changed_plan["entries"][0]["required_oracle"]["status"] = "passed_current"
        with self.assertRaisesRegex(
            executor.QualificationError, "plan entry is not live-open"
        ):
            executor._verify_live_open(changed_plan, capabilities, oracles)

    def test_execute_performs_no_file_writes(self) -> None:
        with (
            mock.patch.object(
                Path, "write_bytes", side_effect=AssertionError("write_bytes called")
            ),
            mock.patch.object(
                Path, "write_text", side_effect=AssertionError("write_text called")
            ),
            mock.patch.object(
                Path, "mkdir", side_effect=AssertionError("mkdir called")
            ),
            mock.patch.object(
                Path, "unlink", side_effect=AssertionError("unlink called")
            ),
        ):
            result = executor.execute()
        self.assertIs(result["file_writes_used"], False)

    def test_executor_has_no_network_subprocess_docker_or_mutation_primitives(
        self,
    ) -> None:
        tree = ast.parse((LANE / "executor.py").read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertTrue(
            imported.isdisjoint(
                {
                    "subprocess",
                    "socket",
                    "requests",
                    "httpx",
                    "urllib",
                    "aiohttp",
                    "docker",
                    "boto3",
                    "os",
                }
            )
        )
        forbidden_calls = {
            "write_bytes",
            "write_text",
            "mkdir",
            "unlink",
            "rename",
            "rmdir",
            "system",
            "popen",
            "run",
            "call",
            "urlopen",
            "connect",
        }
        called_attributes = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertTrue(called_attributes.isdisjoint(forbidden_calls))


if __name__ == "__main__":
    unittest.main()
