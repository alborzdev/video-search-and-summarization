from __future__ import annotations

import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PACKAGE_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = PACKAGE_DIR / "validate_coverage.py"
SPEC = importlib.util.spec_from_file_location("wave3_validate_coverage", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
validator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = validator
SPEC.loader.exec_module(validator)


class CoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.coverage = validator.load_json(validator.COVERAGE)
        cls.targets = validator.load_json(validator.TARGETS)

    def validate_coverage_copy(self, document: dict) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "coverage.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with mock.patch.object(validator, "COVERAGE", path):
                validator.validate()

    def validate_targets_copy(self, document: dict) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "targets.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            coverage = copy.deepcopy(self.coverage)
            coverage["docs_index_binding"]["target_file_sha256"] = (
                validator.sha256_file(path)
            )
            coverage_path = Path(directory) / "coverage.json"
            coverage_path.write_text(json.dumps(coverage), encoding="utf-8")
            with (
                mock.patch.object(validator, "TARGETS", path),
                mock.patch.object(validator, "COVERAGE", coverage_path),
            ):
                validator.validate()

    def test_checked_in_package_passes(self) -> None:
        result = validator.validate()
        self.assertEqual(result["targets"], 152)
        self.assertEqual(result["rest_operations"], 326)
        self.assertEqual(result["schema_hashed"], 75)
        self.assertEqual(result["schema_null"], 251)

    def test_duplicate_json_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.json"
            path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
            with self.assertRaisesRegex(validator.CoverageError, "duplicate JSON key"):
                validator.load_json(path)

    def test_exact_semantic_and_navigation_sets_are_pinned(self) -> None:
        document = copy.deepcopy(self.coverage)
        semantic = next(
            item for item in document["pages"] if item["category"] == "semantic_omission"
        )
        navigation = next(
            item
            for item in document["pages"]
            if item["category"] == "navigation_duplicate_reference"
        )
        semantic["category"], navigation["category"] = (
            navigation["category"],
            semantic["category"],
        )
        with self.assertRaisesRegex(validator.CoverageError, "59-page"):
            self.validate_coverage_copy(document)

    def test_every_index_url_must_appear_exactly_once(self) -> None:
        document = copy.deepcopy(self.coverage)
        document["pages"][1]["url"] = document["pages"][0]["url"]
        with self.assertRaisesRegex(validator.CoverageError, "every exact index target"):
            self.validate_coverage_copy(document)

    def test_target_set_hash_is_independent_of_coverage(self) -> None:
        document = copy.deepcopy(self.targets)
        document["targets"][0] = (
            "https://docs.nvidia.com/vss/3.2.1/not-an-index-target.html"
        )
        document["targets"].sort()
        with self.assertRaisesRegex(validator.CoverageError, "canonical URL-set hash"):
            self.validate_targets_copy(document)

    def test_live_binding_hash_drift_is_rejected(self) -> None:
        document = copy.deepcopy(self.coverage)
        document["live_input_bindings"]["api_inventory"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(validator.CoverageError, "bound input hash drift"):
            self.validate_coverage_copy(document)

    def test_byte_lock_cannot_be_semantic_proof(self) -> None:
        document = copy.deepcopy(self.coverage)
        document["pages"][0]["semantic_proof_from_byte_lock"] = True
        with self.assertRaisesRegex(validator.CoverageError, "schema validation failed"):
            self.validate_coverage_copy(document)

    def test_route_hash_cannot_be_semantic_proof(self) -> None:
        document = copy.deepcopy(self.coverage)
        document["api_semantic_audit"][
            "route_or_schema_hash_is_semantic_test"
        ] = True
        with self.assertRaisesRegex(validator.CoverageError, "schema validation failed"):
            self.validate_coverage_copy(document)

    def test_release_note_arithmetic_is_fail_closed(self) -> None:
        document = copy.deepcopy(self.coverage)
        document["release_note_audit"]["v3_2_0_agent_workflow_top_level_bullets"] = 64
        with self.assertRaisesRegex(validator.CoverageError, "schema validation failed"):
            self.validate_coverage_copy(document)

    def test_unknown_fields_are_rejected(self) -> None:
        document = copy.deepcopy(self.coverage)
        document["unreviewed"] = True
        with self.assertRaisesRegex(validator.CoverageError, "schema validation failed"):
            self.validate_coverage_copy(document)


if __name__ == "__main__":
    unittest.main()
