from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SYSTEMS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SYSTEMS_DIR))

import validate_candidate as validator  # noqa: E402


class SystemsCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.package = validator.load_json(validator.CANDIDATE)

    def _validate(self, package: dict | None = None) -> dict:
        return validator.validate(
            copy.deepcopy(self.package if package is None else package)
        )

    def test_checked_in_candidate_has_exact_counts(self) -> None:
        report = self._validate()
        self.assertEqual(report["sources"], 23)
        self.assertEqual(report["proposed_capabilities"], 55)
        self.assertEqual(report["enrichments"], 19)
        self.assertEqual(report["discrepancies_and_boundaries"], 18)
        self.assertEqual(report["faq_duplicate_groups"], 4)
        self.assertEqual(report["faq_external_groups"], 5)
        self.assertEqual(report["performance_fixture_requirements"], 7)

    def test_duplicate_json_keys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "duplicate.json"
            path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
            with self.assertRaisesRegex(validator.CandidateError, "duplicate JSON key"):
                validator.load_json(path)

    def test_exact_capability_count_is_fail_closed(self) -> None:
        package = copy.deepcopy(self.package)
        package["proposed_capabilities"].pop()
        with self.assertRaisesRegex(validator.CandidateError, "schema validation failed"):
            self._validate(package)

    def test_exact_source_set_is_fail_closed(self) -> None:
        package = copy.deepcopy(self.package)
        package["sources"][0]["url"] = (
            "https://docs.nvidia.com/vss/3.2.1/not-the-reviewed-page.html"
        )
        with self.assertRaisesRegex(validator.CandidateError, "source set drifted"):
            self._validate(package)

    def test_unknown_source_reference_is_rejected(self) -> None:
        package = copy.deepcopy(self.package)
        package["proposed_capabilities"][0]["source"]["source_id"] = "doc.missing"
        with self.assertRaisesRegex(validator.CandidateError, "unknown source reference"):
            self._validate(package)

    def test_unknown_acceptance_scenario_is_rejected(self) -> None:
        package = copy.deepcopy(self.package)
        package["proposed_capabilities"][0]["acceptance"]["scenario_id"] = (
            "missing-scenario"
        )
        with self.assertRaisesRegex(validator.CandidateError, "unknown acceptance scenario"):
            self._validate(package)

    def test_proposal_cannot_claim_passed_current(self) -> None:
        package = copy.deepcopy(self.package)
        package["proposed_capabilities"][0]["acceptance"]["runtime_state"] = (
            "passed_current"
        )
        with self.assertRaisesRegex(validator.CandidateError, "schema validation failed"):
            self._validate(package)

    def test_performance_requirement_cannot_be_promoted(self) -> None:
        package = copy.deepcopy(self.package)
        package["performance_fixture_requirements"][0]["reference_only"] = False
        with self.assertRaisesRegex(validator.CandidateError, "schema validation failed"):
            self._validate(package)

    def test_thor_remeasurement_cannot_be_waived(self) -> None:
        package = copy.deepcopy(self.package)
        package["performance_fixture_requirements"][0][
            "thor_remeasurement_required"
        ] = False
        with self.assertRaisesRegex(validator.CandidateError, "schema validation failed"):
            self._validate(package)

    def test_performance_evidence_cannot_become_a_thor_result(self) -> None:
        original = validator._evidence_file

        def promoted(relative: str) -> dict:
            result = copy.deepcopy(original(relative))
            if relative == "evidence/performance-reference-contracts.json":
                result["thor_results"] = True
            return result

        with mock.patch.object(validator, "_evidence_file", side_effect=promoted):
            with self.assertRaisesRegex(validator.CandidateError, "promoted to a Thor result"):
                self._validate()

    def test_full_performance_transcription_remains_required(self) -> None:
        original = validator._evidence_file

        def incomplete(relative: str) -> dict:
            result = copy.deepcopy(original(relative))
            if relative == "evidence/performance-reference-contracts.json":
                result["fixtures"][0]["must_transcribe_all_source_rows"] = False
            return result

        with mock.patch.object(validator, "_evidence_file", side_effect=incomplete):
            with self.assertRaisesRegex(validator.CandidateError, "full source transcription"):
                self._validate()

    def test_broker_topic_asymmetry_is_fail_closed(self) -> None:
        original = validator._evidence_file

        def equivalent(relative: str) -> dict:
            result = copy.deepcopy(original(relative))
            if relative == "evidence/broker-topic-contracts.json":
                result["must_not_claim_equivalent_topic_sets"] = False
            return result

        with mock.patch.object(validator, "_evidence_file", side_effect=equivalent):
            with self.assertRaisesRegex(validator.CandidateError, "asymmetry boundary"):
                    self._validate()

    def test_auxiliary_evidence_content_is_digest_pinned(self) -> None:
        relative = "evidence/broker-topic-contracts.json"
        with mock.patch.dict(
            validator.EXPECTED_EVIDENCE_SHA256,
            {relative: "0" * 64},
        ):
            with self.assertRaisesRegex(
                validator.CandidateError, "evidence content digest drift"
            ):
                validator._evidence_file(relative)

    def test_external_faq_hardware_cannot_be_thor_evidence(self) -> None:
        package = copy.deepcopy(self.package)
        package["faq_groups"]["external_requirements"][0]["thor_result"] = True
        with self.assertRaisesRegex(validator.CandidateError, "schema validation failed"):
            self._validate(package)

    def test_faq_duplicate_must_point_to_canonical_claim(self) -> None:
        package = copy.deepcopy(self.package)
        package["faq_groups"]["duplicates"][0]["canonical_claim"] = "missing.claim"
        with self.assertRaisesRegex(validator.CandidateError, "missing canonical claim"):
            self._validate(package)

    def test_warehouse_sample_exclusion_is_fail_closed(self) -> None:
        package = copy.deepcopy(self.package)
        package["scope"]["warehouse_sample_bundle"] = "included"
        with self.assertRaisesRegex(validator.CandidateError, "schema validation failed"):
            self._validate(package)

    def test_all_invariants_are_fail_closed(self) -> None:
        package = copy.deepcopy(self.package)
        package["invariants"][
            "release_grouped_bullets_do_not_imply_one_to_one_capabilities"
        ] = False
        with self.assertRaisesRegex(validator.CandidateError, "schema validation failed"):
            self._validate(package)

    def test_unreviewed_contract_value_change_is_rejected(self) -> None:
        package = copy.deepcopy(self.package)
        capability = next(
            item
            for item in package["proposed_capabilities"]
            if item["id"] == "runtime.alerts.workflow-modes"
        )
        capability["contract"]["modes"] = ["invented"]
        with self.assertRaisesRegex(
            validator.CandidateError, "candidate content digest drift"
        ):
            self._validate(package)


if __name__ == "__main__":
    unittest.main()
