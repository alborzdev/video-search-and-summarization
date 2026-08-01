#!/usr/bin/env python3
"""Adversarial tests for the isolated extended API surface contract."""

from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


PACKAGE = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE.parents[4]
SPEC = importlib.util.spec_from_file_location(
    "extended_api_surface_validator", PACKAGE / "validate.py"
)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)
CONTRACT_PATH = PACKAGE / "contract.json"
SCHEMA_PATH = PACKAGE / "contract.schema.json"


class ExtendedApiSurfaceContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = VALIDATOR.load_json(CONTRACT_PATH)

    def _rehash(self, document: dict) -> None:
        document["contract_set_sha256"] = VALIDATOR.canonical_contract_hash(document)

    def _assert_rejected(self, document: dict, message: str) -> None:
        with self.assertRaisesRegex(VALIDATOR.ContractError, message):
            VALIDATOR.validate(document, SCHEMA_PATH, REPO_ROOT)

    def test_reviewed_contract_passes(self) -> None:
        VALIDATOR.validate(self.document, SCHEMA_PATH, REPO_ROOT)

    def test_canonical_hash_is_stable(self) -> None:
        self.assertEqual(
            self.document["contract_set_sha256"],
            "d1aaf222278eb0b0ce73a98de54eb2d2139a717696743f2b3df5f99088850ad2",
        )
        self.assertEqual(
            VALIDATOR.canonical_contract_hash(self.document),
            self.document["contract_set_sha256"],
        )

    def test_duplicate_json_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "duplicate.json"
            path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
            with self.assertRaisesRegex(VALIDATOR.ContractError, "duplicate JSON key"):
                VALIDATOR.load_json(path)

    def test_unknown_field_is_rejected_by_schema(self) -> None:
        mutated = copy.deepcopy(self.document)
        mutated["unexpected"] = True
        self._rehash(mutated)
        self._assert_rejected(mutated, "schema validation failed")

    def test_hash_mismatch_is_rejected(self) -> None:
        mutated = copy.deepcopy(self.document)
        mutated["scope"]["minimum_declared_rest_operations"] = 422
        self._assert_rejected(
            mutated, "schema validation failed|contract_set_sha256 mismatch"
        )

    def test_exact_operation_removal_fails_even_after_rehash(self) -> None:
        mutated = copy.deepcopy(self.document)
        surface = next(
            item for item in mutated["surfaces"] if item["id"] == "sdrc-router"
        )
        surface["operations"].pop()
        surface["operation_count"] -= 1
        surface["minimum_operation_count"] -= 1
        self._rehash(mutated)
        self._assert_rejected(mutated, "exact operation descriptor drift")

    def test_exact_operation_substitution_fails_even_after_rehash(self) -> None:
        mutated = copy.deepcopy(self.document)
        surface = next(
            item
            for item in mutated["surfaces"]
            if item["id"] == "vss-configurator-sensor"
        )
        surface["operations"][0]["path"] = "/invented"
        self._rehash(mutated)
        self._assert_rejected(mutated, "exact operation descriptor drift")

    def test_legacy_total_cannot_be_invented(self) -> None:
        mutated = copy.deepcopy(self.document)
        legacy = next(
            item for item in mutated["surfaces"] if item["id"] == "legacy-calibration"
        )
        legacy["contract_state"] = "exact_descriptor"
        legacy["operation_count"] = 14
        self._rehash(mutated)
        self._assert_rejected(
            mutated, "legacy contract must remain authoritative_unknown"
        )

    def test_legacy_lower_bound_cannot_be_shrunk(self) -> None:
        mutated = copy.deepcopy(self.document)
        legacy = next(
            item for item in mutated["surfaces"] if item["id"] == "legacy-calibration"
        )
        legacy["operations"].pop()
        legacy["minimum_operation_count"] = 13
        self._rehash(mutated)
        self._assert_rejected(mutated, "exact operation descriptor drift")

    def test_complete_product_claim_is_rejected(self) -> None:
        mutated = copy.deepcopy(self.document)
        mutated["scope"]["complete_product_api"] = True
        self._rehash(mutated)
        self._assert_rejected(mutated, "schema validation failed")

    def test_image_digest_drift_fails_without_docker(self) -> None:
        mutated = copy.deepcopy(self.document)
        provenance = next(
            item
            for item in mutated["extraction_provenance"]
            if item["id"] == "vss-configurator-image"
        )
        fake = "sha256:" + "0" * 64
        provenance["image_digest"] = fake
        provenance["image_id"] = fake
        provenance["image_reference"] = (
            provenance["image_reference"].split("@")[0] + "@" + fake
        )
        self._rehash(mutated)
        self._assert_rejected(mutated, "image digest drift")

    def test_checked_in_source_digest_drift_is_rejected(self) -> None:
        mutated = copy.deepcopy(self.document)
        provenance = next(
            item
            for item in mutated["extraction_provenance"]
            if item["id"] == "auto-calibration-checkout"
        )
        provenance["files"][0]["content_sha256"] = "0" * 64
        self._rehash(mutated)
        self._assert_rejected(mutated, "source SHA-256 drift")

    def test_legacy_registry_child_digest_is_locked(self) -> None:
        mutated = copy.deepcopy(self.document)
        provenance = next(
            item
            for item in mutated["extraction_provenance"]
            if item["id"] == "legacy-calibration-registry"
        )
        fake = "sha256:" + "0" * 64
        provenance["child_manifest_digest"] = fake
        provenance["pinned_child_reference"] = (
            provenance["pinned_child_reference"].split("@")[0] + "@" + fake
        )
        self._rehash(mutated)
        self._assert_rejected(mutated, "legacy registry child digest drift")

    def test_legacy_registry_cannot_invent_arm64_support(self) -> None:
        mutated = copy.deepcopy(self.document)
        provenance = next(
            item
            for item in mutated["extraction_provenance"]
            if item["id"] == "legacy-calibration-registry"
        )
        provenance["arm64_variant_present"] = True
        self._rehash(mutated)
        self._assert_rejected(mutated, "schema validation failed")

    def test_legacy_registry_unresolved_sizes_cannot_be_invented(self) -> None:
        mutated = copy.deepcopy(self.document)
        provenance = next(
            item
            for item in mutated["extraction_provenance"]
            if item["id"] == "legacy-calibration-registry"
        )
        provenance["tag_index_digest"] = "sha256:" + "1" * 64
        provenance["unpacked_size_bytes"] = 1
        self._rehash(mutated)
        self._assert_rejected(mutated, "schema validation failed")

    def test_legacy_registry_cannot_claim_local_presence(self) -> None:
        mutated = copy.deepcopy(self.document)
        provenance = next(
            item
            for item in mutated["extraction_provenance"]
            if item["id"] == "legacy-calibration-registry"
        )
        provenance["local_presence_observed"] = True
        provenance["runtime_state"] = "not_qualified"
        self._rehash(mutated)
        self._assert_rejected(mutated, "schema validation failed")

    def test_legacy_registry_pull_boundary_is_locked(self) -> None:
        mutated = copy.deepcopy(self.document)
        provenance = next(
            item
            for item in mutated["extraction_provenance"]
            if item["id"] == "legacy-calibration-registry"
        )
        provenance["approval_boundaries"]["pull_command_after_approval"] = (
            "docker pull nvcr.io/nvidia/vss-core/calibration:3.2.1"
        )
        self._rehash(mutated)
        self._assert_rejected(mutated, "legacy registry approval boundary drift")

    def test_legacy_surface_must_link_registry_provenance(self) -> None:
        mutated = copy.deepcopy(self.document)
        legacy = next(
            item for item in mutated["surfaces"] if item["id"] == "legacy-calibration"
        )
        legacy["provenance_id"] = "legacy-calibration-checkout"
        self._rehash(mutated)
        self._assert_rejected(mutated, "legacy registry provenance link drift")

    def test_get_reset_remains_classified_as_mutating(self) -> None:
        mutated = copy.deepcopy(self.document)
        surface = next(
            item
            for item in mutated["surfaces"]
            if item["id"] == "sdrc-workload-coordinator"
        )
        reset = next(item for item in surface["operations"] if item["path"] == "/reset")
        reset["mutation"] = "read_only"
        self._rehash(mutated)
        self._assert_rejected(mutated, "GET /reset mutation guard drift")

    def test_sdrc_six_route_schema_discrepancy_is_locked(self) -> None:
        surface = next(
            item
            for item in self.document["surfaces"]
            if item["id"] == "sdrc-workload-coordinator"
        )
        implementation_only = {
            (item["method"], item["path"])
            for item in surface["operations"]
            if item["evidence"] == "implementation_only"
        }
        self.assertEqual(len(implementation_only), 6)
        self.assertIn(("POST", "/remove_stream"), implementation_only)

    def test_amc_descriptor_matches_checked_in_catalog(self) -> None:
        catalog = VALIDATOR._extract_amc_catalog(
            REPO_ROOT / "deploy/docker/thor-local/auto-calibration/tool.py"
        )
        self.assertEqual(catalog, VALIDATOR.EXPECTED_OPERATIONS["auto-calibration"])

    def test_validator_does_not_import_docker_client_or_subprocess(self) -> None:
        source = (PACKAGE / "validate.py").read_text(encoding="utf-8")
        self.assertNotIn("import docker", source)
        self.assertNotIn("import subprocess", source)
        self.assertNotIn("docker image inspect", source)

    def test_machine_readable_result_preserves_unresolved_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            copied = Path(temp_dir) / "contract.json"
            copied.write_text(json.dumps(self.document), encoding="utf-8")
            self.assertEqual(
                VALIDATOR.run(copied, SCHEMA_PATH, REPO_ROOT, json_output=True), 0
            )


if __name__ == "__main__":
    unittest.main()
