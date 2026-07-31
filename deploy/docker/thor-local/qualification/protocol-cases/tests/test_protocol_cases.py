#!/usr/bin/env python3
"""Mutation tests for the fail-closed non-REST protocol case ledger."""

from __future__ import annotations

import copy
import importlib.util
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
LANE = HERE.parent
REPO_ROOT = HERE.parents[5]
SPEC = importlib.util.spec_from_file_location(
    "validate_protocol_cases", LANE / "validate_protocol_cases.py"
)
assert SPEC and SPEC.loader
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


class ProtocolCaseContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = validator.load_json(LANE / "protocol-cases.json")

    def _resign(self, document: dict) -> dict:
        document["contract_set_sha256"] = validator.canonical_contract_hash(document)
        return document

    def _assert_rejected(self, document: dict, pattern: str) -> None:
        with self.assertRaisesRegex(validator.ContractError, pattern):
            validator.validate(document, REPO_ROOT)

    def test_current_contract_passes(self) -> None:
        validator.validate(self.document, REPO_ROOT)

    def test_duplicate_json_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "duplicate.json"
            path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
            with self.assertRaisesRegex(validator.ContractError, "duplicate JSON key"):
                validator.load_json(path)

    def test_contract_hash_detects_unreviewed_mutation(self) -> None:
        mutated = copy.deepcopy(self.document)
        mutated["cases"][0]["runtime_state"] = "passed_current"
        self._assert_rejected(mutated, "contract_set_sha256 mismatch")

    def test_resigned_runtime_spoof_is_rejected(self) -> None:
        mutated = copy.deepcopy(self.document)
        mutated["cases"][0]["runtime_state"] = "passed_current"
        self._resign(mutated)
        self._assert_rejected(mutated, "cannot claim runtime execution")

    def test_capability_denominator_drift_is_rejected(self) -> None:
        mutated = copy.deepcopy(self.document)
        mutated["cases"].pop()
        self._resign(mutated)
        self._assert_rejected(mutated, "exactly seven")

    def test_source_content_hash_drift_is_rejected(self) -> None:
        mutated = copy.deepcopy(self.document)
        mutated["cases"][0]["sources"][0]["content_sha256"] = "0" * 64
        self._resign(mutated)
        self._assert_rejected(mutated, "source SHA-256 drift")

    def test_source_git_blob_drift_is_rejected(self) -> None:
        mutated = copy.deepcopy(self.document)
        mutated["cases"][0]["sources"][0]["git_blob_oid"] = "0" * 40
        self._resign(mutated)
        self._assert_rejected(mutated, "Git blob drift")

    def test_source_path_escape_is_rejected(self) -> None:
        mutated = copy.deepcopy(self.document)
        mutated["cases"][0]["sources"][0]["path"] = "../outside"
        self._resign(mutated)
        self._assert_rejected(mutated, "source escapes repository")

    def test_unbounded_positive_vector_is_rejected(self) -> None:
        mutated = copy.deepcopy(self.document)
        mutated["cases"][2]["positive_vector"]["deadline_seconds"] = 600
        self._resign(mutated)
        self._assert_rejected(mutated, "unsafe deadline")

    def test_non_adjacent_negative_vector_is_rejected(self) -> None:
        mutated = copy.deepcopy(self.document)
        del mutated["cases"][4]["adjacent_negative_vectors"][0]["adjacent_mutation"]
        self._resign(mutated)
        self._assert_rejected(mutated, "vector keys")

    def test_sequence_reordering_is_rejected(self) -> None:
        mutated = copy.deepcopy(self.document)
        mutated["cases"][5]["sequence"][1]["order"] = 3
        self._resign(mutated)
        self._assert_rejected(mutated, "sequence order")

    def test_unnamespaced_mutation_ownership_is_rejected(self) -> None:
        mutated = copy.deepcopy(self.document)
        mutated["cases"][3]["mutation"]["ownership"] = "own the default topic"
        self._resign(mutated)
        self._assert_rejected(mutated, "ownership lacks protocol-case namespace")

    def test_duplicate_wire_field_is_rejected(self) -> None:
        mutated = copy.deepcopy(self.document)
        field = copy.deepcopy(mutated["cases"][1]["request_schema"]["fields"][0])
        mutated["cases"][1]["request_schema"]["fields"].append(field)
        self._resign(mutated)
        self._assert_rejected(mutated, "duplicate field path")

    def test_schema_document_and_contract_parse_without_duplicate_keys(self) -> None:
        schema = validator.load_json(LANE / "protocol-cases.schema.json")
        self.assertEqual(
            schema["$schema"], "https://json-schema.org/draft/2020-12/schema"
        )
        self.assertEqual(schema["properties"]["cases"]["minItems"], 7)


if __name__ == "__main__":
    unittest.main()
