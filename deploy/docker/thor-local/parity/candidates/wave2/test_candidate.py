# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

import validate_candidate as validator


class Wave2CandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.package = validator.load_json(validator.CANDIDATE)
        cls.live_ledger = validator.load_json(validator.LIVE_LEDGER)
        cls.live_manifest = validator.load_json(validator.LIVE_MANIFEST)
        cls.live_acceptance = validator.load_json(validator.LIVE_ACCEPTANCE)

    def _validate(self, package: dict | None = None) -> dict[str, int]:
        return validator.validate(
            copy.deepcopy(self.package if package is None else package),
            live_ledger=copy.deepcopy(self.live_ledger),
            live_manifest=copy.deepcopy(self.live_manifest),
            live_acceptance=copy.deepcopy(self.live_acceptance),
        )

    def test_checked_in_candidate_has_exact_counts(self) -> None:
        counts = self._validate()
        self.assertEqual(
            counts,
            {
                "sources": 26,
                "new_capabilities": 30,
                "enrichments": 9,
                "discrepancies_and_boundaries": 14,
            },
        )

    def test_duplicate_json_keys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "duplicate.json"
            path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
            with self.assertRaisesRegex(
                validator.CandidateContractError,
                "duplicate JSON key",
            ):
                validator.load_json(path)

    def test_new_capability_cannot_overlap_live_ledger(self) -> None:
        package = copy.deepcopy(self.package)
        package["new_capabilities"][0]["id"] = "evaluation.agent.report"
        with self.assertRaisesRegex(
            validator.CandidateContractError,
            "already exists in live ledger",
        ):
            self._validate(package)

    def test_enrichment_target_must_exist(self) -> None:
        package = copy.deepcopy(self.package)
        package["enrichments"][0]["target_id"] = "missing.target"
        with self.assertRaisesRegex(
            validator.CandidateContractError,
            "enrichment target missing",
        ):
            self._validate(package)

    def test_source_claim_hash_drift_is_rejected(self) -> None:
        package = copy.deepcopy(self.package)
        package["new_capabilities"][0]["contract"]["drift"] = True
        with self.assertRaisesRegex(
            validator.CandidateContractError,
            "source claim hash drift",
        ):
            self._validate(package)

    def test_exact_count_drift_is_rejected(self) -> None:
        package = copy.deepcopy(self.package)
        package["new_capabilities"].pop()
        with self.assertRaisesRegex(
            validator.CandidateContractError,
            "schema violation",
        ):
            self._validate(package)

    def test_expected_manifest_never_claims_semantic_coverage(self) -> None:
        package = copy.deepcopy(self.package)
        package["new_capabilities"][0]["expected_manifest_binding"][
            "semantic_coverage"
        ] = True
        with self.assertRaisesRegex(
            validator.CandidateContractError,
            "schema violation",
        ):
            self._validate(package)

    def test_extraction_cannot_claim_passed_current(self) -> None:
        package = copy.deepcopy(self.package)
        package["new_capabilities"][0]["status"]["runtime_state"] = "passed_current"
        with self.assertRaisesRegex(
            validator.CandidateContractError,
            "cannot claim passed_current",
        ):
            self._validate(package)

    def test_autocal_thor_support_boundary_is_fail_closed(self) -> None:
        package = copy.deepcopy(self.package)
        boundary = next(
            item
            for item in package["new_capabilities"]
            if item["id"] == "boundary.auto-calibration.thor-extension"
        )
        boundary["contract"]["must_not_claim_official_thor_support"] = False
        with self.assertRaisesRegex(
            validator.CandidateContractError,
            "Auto Calibration Thor support boundary drift",
        ):
            self._validate(package)

    def test_security_limitations_cannot_be_marked_remediated(self) -> None:
        package = copy.deepcopy(self.package)
        boundary = next(
            item
            for item in package["new_capabilities"]
            if item["id"] == "security.known-unmitigated-limitations"
        )
        boundary["contract"]["must_not_claim_remediated"] = False
        with self.assertRaisesRegex(
            validator.CandidateContractError,
            "security limitation boundary drift",
        ):
            self._validate(package)

    def test_warehouse_sample_exclusion_is_fail_closed(self) -> None:
        package = copy.deepcopy(self.package)
        package["scope"]["warehouse_sample_bundle"] = "included"
        with self.assertRaisesRegex(
            validator.CandidateContractError,
            "schema violation",
        ):
            self._validate(package)

    def test_all_sources_have_exact_claim_hashes(self) -> None:
        computed = validator.source_claim_hashes(self.package)
        recorded = {
            item["id"]: item["claim_set_sha256"] for item in self.package["sources"]
        }
        self.assertEqual(recorded, computed)

    def test_payload_has_no_duplicate_ids(self) -> None:
        new_ids = [item["id"] for item in self.package["new_capabilities"]]
        enrichment_ids = [item["target_id"] for item in self.package["enrichments"]]
        discrepancy_ids = [
            item["id"] for item in self.package["discrepancies_and_boundaries"]
        ]
        self.assertEqual(len(new_ids), len(set(new_ids)))
        self.assertEqual(len(enrichment_ids), len(set(enrichment_ids)))
        self.assertEqual(len(discrepancy_ids), len(set(discrepancy_ids)))


if __name__ == "__main__":
    unittest.main()
