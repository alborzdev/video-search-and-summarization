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
COMPILER_PATH = PACKAGE_ROOT / "compiler.py"
CONTRACT_PATH = PACKAGE_ROOT / "contract.json"


def _load_compiler():
    spec = importlib.util.spec_from_file_location("exact_title_mapping_successor", COMPILER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ExactTitleEntryMappingSuccessorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_compiler()
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    def _execute_mutated_contract(self, value):
        with tempfile.TemporaryDirectory(prefix="exact-title-successor-") as temp_dir:
            path = Path(temp_dir) / "contract.json"
            raw = json.dumps(value, ensure_ascii=True, indent=2).encode("utf-8") + b"\n"
            path.write_bytes(raw)
            return self.module.execute(path, hashlib.sha256(raw).hexdigest())

    def _sources(self):
        old_raw, old = self.module._load_predecessor(self.contract)
        new_raw, new = self.module._load_current(self.contract)
        return old_raw, old, new_raw, new

    def test_baseline_is_exact_and_non_advancing(self):
        proof = self.module.execute()
        self.assertEqual(
            (proof["predecessor"]["exact_mapping_count"], proof["successor"]["exact_mapping_count"]),
            (13, 289),
        )
        self.assertEqual(
            (proof["transition"]["new_exact_mapping_count"], proof["successor"]["missing_exact_mapping_count"]),
            (276, 211),
        )
        self.assertEqual(proof["successor"]["explicit_missing_entry_gap_count"], 74)
        self.assertFalse(proof["effects"]["can_mark_passed_current"])
        self.assertEqual(proof["effects"]["runtime_evidence"], [])

    def test_committed_proof_is_deterministic(self):
        rendered = self.module._render(self.module.execute())
        self.assertEqual(rendered, (PACKAGE_ROOT / "proof.json").read_bytes())

    def test_all_289_exact_rows_are_unique_and_cover_every_capability(self):
        _old_raw, _old, _new_raw, new = self._sources()
        rows, advertised_total = self.module._exact_mappings(
            new[self.module.MANIFEST_PATH],
            new[self.module.CAPABILITIES_PATH],
            new[self.module.ORACLES_PATH],
        )
        self.assertEqual((advertised_total, len(rows)), (500, 289))
        self.assertEqual(len({row["manifest_pointer"] for row in rows}), 289)
        self.assertEqual(len({row["capability_id"] for row in rows}), 289)

    def test_raw_contract_drift_fails_closed(self):
        with tempfile.TemporaryDirectory(prefix="exact-title-successor-") as temp_dir:
            path = Path(temp_dir) / "contract.json"
            path.write_bytes(CONTRACT_PATH.read_bytes() + b" ")
            with self.assertRaisesRegex(self.module.ProofError, "raw digest"):
                self.module.execute(path)

    def test_contract_schema_rejects_unknown_fields(self):
        schema = json.loads((PACKAGE_ROOT / "contract.schema.json").read_text(encoding="utf-8"))
        value = copy.deepcopy(self.contract)
        value["promote"] = True
        self.assertTrue(list(Draft202012Validator(schema).iter_errors(value)))

    def test_capability_title_drift_is_rejected(self):
        old_raw, old, new_raw, new = self._sources()
        new = copy.deepcopy(new)
        new[self.module.CAPABILITIES_PATH]["capabilities"][0]["title"] += " drift"
        with self.assertRaisesRegex(self.module.ProofError, "mapping denominator"):
            self.module.compile_proof(self.contract, old_raw, old, new_raw, new)

    def test_capability_feature_drift_is_rejected(self):
        old_raw, old, new_raw, new = self._sources()
        new = copy.deepcopy(new)
        capability_id = new[self.module.MANIFEST_PATH]["features"][0]["official_capability_ids"][0]
        capability = next(row for row in new[self.module.CAPABILITIES_PATH]["capabilities"] if row["id"] == capability_id)
        capability["feature_id"] = "wrong-family"
        with self.assertRaisesRegex(self.module.ProofError, "feature mismatch"):
            self.module.compile_proof(self.contract, old_raw, old, new_raw, new)

    def test_oracle_evidence_promotion_is_rejected(self):
        old_raw, old, new_raw, new = self._sources()
        new = copy.deepcopy(new)
        new[self.module.ORACLES_PATH]["oracles"][0]["evidence"] = [{"claim": "runtime pass"}]
        with self.assertRaisesRegex(self.module.ProofError, "oracle runtime evidence"):
            self.module.compile_proof(self.contract, old_raw, old, new_raw, new)

    def test_gap_semantic_mutation_is_rejected(self):
        old_raw, old, new_raw, new = self._sources()
        new = copy.deepcopy(new)
        new[self.module.PLAN_PATH]["entries"][0]["advertised"] += " drift"
        with self.assertRaisesRegex(self.module.ProofError, "gap plan changed"):
            self.module.compile_proof(self.contract, old_raw, old, new_raw, new)

    def test_warehouse_sample_inclusion_is_rejected(self):
        old_raw, old, new_raw, new = self._sources()
        new = copy.deepcopy(new)
        new[self.module.PLAN_PATH]["policy"]["warehouse_sample_bundle"] = "included"
        with self.assertRaisesRegex(self.module.ProofError, "gap plan changed|Warehouse sample"):
            self.module.compile_proof(self.contract, old_raw, old, new_raw, new)

    def test_frozen_tooling_tree_tamper_is_rejected(self):
        value = copy.deepcopy(self.contract)
        value["frozen_predecessor_package"]["tree_oid"] = "0" * 40
        with self.assertRaisesRegex(self.module.ProofError, "schema validation|tree mismatch"):
            self._execute_mutated_contract(value)

    def test_predecessor_denominator_tamper_is_rejected(self):
        old_raw, old, new_raw, new = self._sources()
        old = copy.deepcopy(old)
        old[self.module.PLAN_PATH]["summary"]["advertised_entries_without_entry_specific_capability_mapping"] = 486
        with self.assertRaisesRegex(self.module.ProofError, "predecessor missing exact mapping"):
            self.module.compile_proof(self.contract, old_raw, old, new_raw, new)

    def test_prohibited_git_command_is_rejected(self):
        with self.assertRaisesRegex(self.module.ProofError, "prohibited git command"):
            self.module._git("status")

    def test_compiler_subprocess_is_shell_free_and_read_only(self):
        tree = ast.parse(COMPILER_PATH.read_bytes(), filename=str(COMPILER_PATH))
        imports = set()
        run_calls = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".", 1)[0])
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "run":
                run_calls.append(node)
        self.assertTrue(imports.isdisjoint({"socket", "requests", "urllib", "docker", "boto3"}))
        self.assertEqual(len(run_calls), 1)
        keywords = {item.arg: item.value for item in run_calls[0].keywords}
        self.assertIsInstance(keywords["shell"], ast.Constant)
        self.assertFalse(keywords["shell"].value)
        source = COMPILER_PATH.read_text(encoding="utf-8")
        self.assertNotIn("write_text(", source)
        self.assertNotIn("write_bytes(", source)

    def test_duplicate_json_keys_are_rejected(self):
        with self.assertRaisesRegex(self.module.ProofError, "duplicate JSON"):
            self.module._strict_json_bytes(b'{"x":1,"x":2}', "duplicate")


if __name__ == "__main__":
    unittest.main()
