from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from jsonschema import Draft202012Validator


PACKAGE_DIR = Path(__file__).resolve().parents[1]
EXECUTOR_PATH = PACKAGE_DIR / "executor.py"
CONTRACT_PATH = PACKAGE_DIR / "contract.json"


def _load_executor():
    spec = importlib.util.spec_from_file_location("spatial_ai_static_contract", EXECUTOR_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class SpatialAiStaticContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_executor()
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    def _execute_mutated(self, value):
        with tempfile.TemporaryDirectory(prefix="spatial-ai-static-test-") as temp_dir:
            path = Path(temp_dir) / "contract.json"
            raw = json.dumps(value, indent=2, ensure_ascii=True).encode("utf-8") + b"\n"
            path.write_bytes(raw)
            return self.module.execute(path, hashlib.sha256(raw).hexdigest())

    def test_baseline_result_is_exactly_non_advancing(self):
        result = self.module.execute()
        self.assertEqual(result["summary"]["entry_count"], 8)
        self.assertEqual(result["summary"]["unique_source_lock_count"], 34)
        self.assertEqual(result["summary"]["runtime_evidence_count"], 0)
        self.assertFalse(result["can_mark_passed_current"])
        self.assertEqual(result["runtime_evidence"], [])
        self.assertTrue(all(row["runtime_evidence"] == [] for row in result["entries"]))

    def test_output_is_deterministic(self):
        first = self.module._canonical_bytes(self.module.execute())
        second = self.module._canonical_bytes(self.module.execute())
        self.assertEqual(first, second)

    def test_exact_entry_identity_and_state_partition(self):
        result = self.module.execute()
        local = result["entries"][:7]
        external = result["entries"][7]
        self.assertTrue(
            all(
                row["acceptance_class"] == "alternate_local_lane"
                and row["thor_state"] == "wired"
                and row["runtime_state"] == "not_qualified"
                and row["oracle_current_state"] == "open_unexecuted"
                for row in local
            )
        )
        self.assertEqual(
            (
                external["acceptance_class"],
                external["thor_state"],
                external["runtime_state"],
                external["oracle_current_state"],
            ),
            (
                "external_optional",
                "external_optional",
                "not_applicable",
                "external_boundary_unexecuted",
            ),
        )
        self.assertEqual(
            [row["oracle_id"] for row in result["entries"]],
            [f'oracle.{row["capability_id"]}' for row in result["entries"]],
        )

    def test_contract_schema_rejects_unknown_field(self):
        schema = json.loads(
            (PACKAGE_DIR / "contract.schema.json").read_text(encoding="utf-8")
        )
        value = copy.deepcopy(self.contract)
        value["entries"][0]["promoted"] = True
        self.assertTrue(list(Draft202012Validator(schema).iter_errors(value)))

    def test_result_schema_rejects_runtime_evidence_and_promotion(self):
        value = self.module.execute()
        value["runtime_evidence"] = [{"claim": "fake"}]
        value["can_mark_passed_current"] = True
        with self.assertRaisesRegex(self.module.QualificationError, "result schema"):
            self.module._validate_schema(
                value, PACKAGE_DIR / "result.schema.json", "result"
            )

    def test_raw_contract_drift_fails_before_review(self):
        with tempfile.TemporaryDirectory(prefix="spatial-ai-static-test-") as temp_dir:
            path = Path(temp_dir) / "contract.json"
            path.write_bytes(CONTRACT_PATH.read_bytes() + b" ")
            with self.assertRaisesRegex(
                self.module.QualificationError, "contract raw digest mismatch"
            ):
                self.module.execute(path)

    def test_policy_relaxation_is_rejected(self):
        value = copy.deepcopy(self.contract)
        value["policy"]["network_allowed"] = True
        with self.assertRaises(self.module.QualificationError):
            self._execute_mutated(value)

    def test_reordered_entries_are_rejected(self):
        value = copy.deepcopy(self.contract)
        value["entries"][0], value["entries"][1] = (
            value["entries"][1],
            value["entries"][0],
        )
        with self.assertRaises(self.module.QualificationError):
            self._execute_mutated(value)

    def test_source_digest_tamper_is_rejected(self):
        value = copy.deepcopy(self.contract)
        value["entries"][0]["source_reviews"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(
            self.module.QualificationError, "source digest mismatch"
        ):
            self._execute_mutated(value)

    def test_missing_ast_symbol_is_rejected(self):
        value = copy.deepcopy(self.contract)
        value["entries"][1]["source_reviews"][0]["ast_symbols"].append(
            "not_a_real_symbol"
        )
        with self.assertRaisesRegex(
            self.module.QualificationError, "missing reviewed AST symbols"
        ):
            self._execute_mutated(value)

    def test_missing_text_fragment_is_rejected(self):
        value = copy.deepcopy(self.contract)
        value["entries"][2]["source_reviews"][0]["text_fragments"].append(
            "not a real reviewed fragment"
        )
        with self.assertRaisesRegex(
            self.module.QualificationError, "missing reviewed text fragments"
        ):
            self._execute_mutated(value)

    def test_manifest_literal_drift_is_rejected(self):
        original = self.module._read_repo_bytes

        def drift(relative: str, *, required_prefix: str):
            raw = original(relative, required_prefix=required_prefix)
            if relative != "deploy/docker/thor-local/parity/manifest.json":
                return raw
            manifest = json.loads(raw)
            manifest["features"][29]["advertised"][3] = "different metric"
            return self.module._canonical_bytes(manifest)

        with mock.patch.object(self.module, "_read_repo_bytes", side_effect=drift):
            with self.assertRaisesRegex(
                self.module.QualificationError,
                "advertised literal/order drift",
            ):
                self.module.execute()

    def test_duplicate_json_keys_are_rejected(self):
        with self.assertRaisesRegex(self.module.QualificationError, "duplicate JSON"):
            self.module._strict_json_bytes(b'{"x": 1, "x": 2}', "duplicate")

    def test_unsafe_source_path_is_rejected(self):
        with self.assertRaisesRegex(self.module.QualificationError, "unsafe repository"):
            self.module._repo_file(
                "libs/analytics/spatialai-data-utils/../../secret",
                required_prefix="libs/analytics/spatialai-data-utils/",
            )

    def test_executor_has_no_prohibited_runtime_imports_or_calls(self):
        tree = ast.parse(EXECUTOR_PATH.read_bytes(), filename=str(EXECUTOR_PATH))
        imported = set()
        calls = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".", 1)[0])
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    calls.add(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    calls.add(node.func.attr)
        self.assertTrue(
            imported.isdisjoint(
                {"subprocess", "socket", "requests", "urllib", "boto3", "docker"}
            )
        )
        self.assertTrue(calls.isdisjoint({"system", "popen", "run", "Popen"}))
        self.assertNotIn("write_text", calls)
        self.assertNotIn("write_bytes", calls)


if __name__ == "__main__":
    unittest.main()
