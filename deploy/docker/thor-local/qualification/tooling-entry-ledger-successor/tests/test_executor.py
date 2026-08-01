from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from jsonschema import Draft202012Validator


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
EXECUTOR_PATH = PACKAGE_ROOT / "executor.py"
CONTRACT_PATH = PACKAGE_ROOT / "contract.json"


def _load_executor():
    spec = importlib.util.spec_from_file_location("tooling_ledger_successor", EXECUTOR_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ToolingEntryLedgerSuccessorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_executor()
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    def _execute_mutated(self, value):
        with tempfile.TemporaryDirectory(prefix="tooling-ledger-successor-") as temp_dir:
            path = Path(temp_dir) / "contract.json"
            raw = json.dumps(value, indent=2, ensure_ascii=True).encode("utf-8") + b"\n"
            path.write_bytes(raw)
            return self.module.execute(path, hashlib.sha256(raw).hexdigest())

    def _cores(self):
        old = self.module._predecessor_core(self.contract)
        _raw, new = self.module._current_core(self.contract)
        return old, new

    def test_baseline_is_exact_and_non_advancing(self):
        result = self.module.execute()
        self.assertEqual(
            (
                result["predecessor"]["official_capability_count"],
                result["predecessor"]["capability_oracle_count"],
                result["predecessor"]["advertised_gap_count"],
            ),
            (277, 277, 86),
        )
        self.assertEqual(
            (
                result["successor"]["official_capability_count"],
                result["successor"]["capability_oracle_count"],
                result["successor"]["advertised_gap_count"],
            ),
            (289, 289, 74),
        )
        self.assertFalse(result["effects"]["can_mark_passed_current"])
        self.assertEqual(result["effects"]["runtime_evidence"], [])
        self.assertEqual(
            (
                result["transition"]["advertised_entries_without_entry_specific_capability_mapping"],
                result["transition"]["family_only_entries_outside_this_plan"],
            ),
            (487, 413),
        )

    def test_output_is_deterministic(self):
        first = self.module._canonical(self.module.execute())
        second = self.module._canonical(self.module.execute())
        self.assertEqual(first, second)

    def test_exact_twelve_id_sets_and_full_oracle_ids(self):
        result = self.module.execute()
        self.assertEqual(len(result["successor"]["retired_gap_ids"]), 12)
        self.assertEqual(len(result["successor"]["added_capability_ids"]), 12)
        self.assertEqual(
            result["successor"]["added_oracle_ids"],
            [f"oracle.{item}" for item in result["successor"]["added_capability_ids"]],
        )

    def test_frozen_closure_includes_required_historical_packages(self):
        result = self.module.execute()
        checks = {item["id"]: item for item in result["frozen_direct_dependents"]["checks"]}
        self.assertEqual(len(checks), 20)
        self.assertEqual(result["frozen_direct_dependents"]["direct_core_artifact_count"], 30)
        for package_id in (
            "cpu-multimedia-ledger-successor",
            "detection-map-static-executor",
            "external-entry-attestations",
        ):
            self.assertEqual(checks[package_id]["execution_state"], "identity_verified_not_reexecuted")

    def test_raw_contract_drift_fails_closed(self):
        with tempfile.TemporaryDirectory(prefix="tooling-ledger-successor-") as temp_dir:
            path = Path(temp_dir) / "contract.json"
            path.write_bytes(CONTRACT_PATH.read_bytes() + b" ")
            with self.assertRaisesRegex(self.module.QualificationError, "raw digest"):
                self.module.execute(path)

    def test_contract_schema_rejects_unknown_fields(self):
        schema = json.loads((PACKAGE_ROOT / "contract.schema.json").read_text(encoding="utf-8"))
        value = copy.deepcopy(self.contract)
        value["promote"] = True
        self.assertTrue(list(Draft202012Validator(schema).iter_errors(value)))

    def test_transition_reordering_is_rejected(self):
        value = copy.deepcopy(self.contract)
        value["successor"]["transition_entries"][0], value["successor"]["transition_entries"][1] = (
            value["successor"]["transition_entries"][1],
            value["successor"]["transition_entries"][0],
        )
        with self.assertRaisesRegex(self.module.QualificationError, "identity/order"):
            self._execute_mutated(value)

    def test_frozen_tree_oid_tamper_is_rejected(self):
        value = copy.deepcopy(self.contract)
        value["frozen_direct_dependents"][3]["tree_oid"] = "0" * 40
        with self.assertRaisesRegex(self.module.QualificationError, "tree mismatch"):
            self._execute_mutated(value)

    def test_common_capability_mutation_is_rejected(self):
        old, new = self._cores()
        new = copy.deepcopy(new)
        new[self.module.CAPABILITIES_PATH]["capabilities"][0]["title"] += " drift"
        with self.assertRaisesRegex(self.module.QualificationError, "predecessor capability record"):
            self.module._verify_transition(self.contract, old, new)

    def test_new_oracle_evidence_is_rejected(self):
        old, new = self._cores()
        new = copy.deepcopy(new)
        oracle_id = self.contract["successor"]["transition_entries"][0]["oracle_id"]
        oracle = next(item for item in new[self.module.ORACLES_PATH]["oracles"] if item["oracle_id"] == oracle_id)
        oracle["evidence"] = [{"claim": "family pass"}]
        with self.assertRaisesRegex(self.module.QualificationError, "has evidence"):
            self.module._verify_transition(self.contract, old, new)

    def test_family_level_passed_promotion_is_rejected(self):
        old, new = self._cores()
        new = copy.deepcopy(new)
        new[self.module.MANIFEST_PATH]["features"][30]["runtime_state"] = "passed_current"
        with self.assertRaisesRegex(self.module.QualificationError, "conservatively retired"):
            self.module._verify_transition(self.contract, old, new)

    def test_warehouse_sample_inclusion_is_rejected(self):
        old, new = self._cores()
        new = copy.deepcopy(new)
        new[self.module.PLAN_PATH]["policy"]["warehouse_sample_bundle"] = "included"
        with self.assertRaisesRegex(self.module.QualificationError, "Warehouse sample"):
            self.module._verify_transition(self.contract, old, new)

    def test_global_denominator_drift_is_rejected(self):
        old, new = self._cores()
        new = copy.deepcopy(new)
        new[self.module.PLAN_PATH]["summary"][
            "advertised_entries_without_entry_specific_capability_mapping"
        ] = 486
        with self.assertRaisesRegex(self.module.QualificationError, "global denominator"):
            self.module._verify_transition(self.contract, old, new)

    def test_aws_gcs_is_the_only_external_boundary(self):
        rows = self.contract["successor"]["transition_entries"]
        external = [row for row in rows if row["acceptance_class"] == "external_optional"]
        self.assertEqual([row["capability_id"] for row in external], ["manifest-entry.spatial-ai-utils.07-aws-gcs-validation"])

    def test_prohibited_git_command_is_rejected(self):
        with self.assertRaisesRegex(self.module.QualificationError, "prohibited git command"):
            self.module._git("status")

    def test_executor_subprocess_is_shell_free_and_read_only(self):
        tree = ast.parse(EXECUTOR_PATH.read_bytes(), filename=str(EXECUTOR_PATH))
        imports = set()
        calls = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".", 1)[0])
            elif isinstance(node, ast.Call):
                calls.append(node)
        self.assertTrue(imports.isdisjoint({"socket", "requests", "urllib", "docker", "boto3"}))
        run_calls = [node for node in calls if isinstance(node.func, ast.Attribute) and node.func.attr == "run"]
        self.assertEqual(len(run_calls), 1)
        keywords = {item.arg: item.value for item in run_calls[0].keywords}
        self.assertIsInstance(keywords["shell"], ast.Constant)
        self.assertFalse(keywords["shell"].value)
        source = EXECUTOR_PATH.read_text(encoding="utf-8")
        for command in ("rev-parse", "cat-file", "show"):
            self.assertIn(command, source)
        self.assertNotIn("write_text(", source)
        self.assertNotIn("write_bytes(", source)

    def test_duplicate_json_keys_are_rejected(self):
        with self.assertRaisesRegex(self.module.QualificationError, "duplicate JSON"):
            self.module._json_bytes(b'{"x":1,"x":2}', "duplicate")


if __name__ == "__main__":
    unittest.main()
