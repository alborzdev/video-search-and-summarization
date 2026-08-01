#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Mutation tests for the fail-closed Wave 3 bundle contract."""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

import validate_bundle as bundle


class BundleValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = bundle.load_json(bundle.PLAN)
        cls.documents = {
            input_id: bundle.load_json(bundle.REPO_ROOT / path)
            for input_id, path in bundle.EXPECTED_INPUT_PATHS.items()
        }

    def assert_invalid(
        self,
        *,
        plan: dict | None = None,
        documents: dict | None = None,
        check_plan_digest: bool = False,
        use_disk_inputs: bool = False,
    ) -> None:
        with self.assertRaises(bundle.BundleContractError):
            bundle.validate(
                copy.deepcopy(self.plan if plan is None else plan),
                documents=(
                    None
                    if use_disk_inputs
                    else copy.deepcopy(self.documents if documents is None else documents)
                ),
                check_plan_digest=check_plan_digest,
            )

    def test_baseline_bundle_is_valid(self) -> None:
        counts = bundle.validate()
        self.assertEqual(counts, bundle.EXPECTED_COUNTS)

    def test_duplicate_json_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "duplicate.json"
            path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
            with self.assertRaises(bundle.BundleContractError):
                bundle.load_json(path)

    def test_non_finite_number_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "nan.json"
            path.write_text('{"value":NaN}', encoding="utf-8")
            with self.assertRaises(bundle.BundleContractError):
                bundle.load_json(path)

    def test_arbitrary_plan_mutation_breaks_canonical_digest(self) -> None:
        plan = copy.deepcopy(self.plan)
        plan["inputs"][0]["sha256"] = "0" * 64
        self.assert_invalid(plan=plan, check_plan_digest=True)

    def test_bound_input_raw_hash_drift_is_rejected(self) -> None:
        plan = copy.deepcopy(self.plan)
        plan["inputs"][0]["sha256"] = "0" * 64
        self.assert_invalid(plan=plan, use_disk_inputs=True)

    def test_systems_auxiliary_evidence_hash_drift_is_rejected(self) -> None:
        plan = copy.deepcopy(self.plan)
        binding = next(
            item for item in plan["inputs"] if item["id"] == "systems-broker-evidence"
        )
        binding["sha256"] = "0" * 64
        self.assert_invalid(plan=plan, use_disk_inputs=True)

    def test_input_path_substitution_is_rejected(self) -> None:
        plan = copy.deepcopy(self.plan)
        plan["inputs"][0]["path"] = plan["inputs"][1]["path"]
        self.assert_invalid(plan=plan, use_disk_inputs=True)

    def test_target_identity_drift_is_rejected(self) -> None:
        documents = copy.deepcopy(self.documents)
        documents["systems"]["target"]["main_commit"] = "0" * 40
        self.assert_invalid(documents=documents)

    def test_candidate_source_outside_recursive_lock_is_rejected(self) -> None:
        documents = copy.deepcopy(self.documents)
        documents["agent-smartcity"]["sources"][0]["uri"] = (
            "https://docs.nvidia.com/vss/3.2.1/not-in-fixed-point.html"
        )
        self.assert_invalid(documents=documents)

    def test_failed_source_lock_record_is_rejected(self) -> None:
        documents = copy.deepcopy(self.documents)
        documents["source-lock"]["records"][0]["outcome"] = "failure"
        self.assert_invalid(documents=documents)

    def test_recursive_and_locked_url_sets_must_match(self) -> None:
        documents = copy.deepcopy(self.documents)
        documents["recursive-targets"]["targets"][0] = (
            "https://docs.nvidia.com/vss/3.2.1/substituted.html"
        )
        self.assert_invalid(documents=documents)

    def test_same_uri_resolution_mutation_is_rejected(self) -> None:
        plan = copy.deepcopy(self.plan)
        plan["source_merge"]["duplicate_uri_resolutions"][0][
            "canonical_source_id"
        ] = "doc.release-notes"
        self.assert_invalid(plan=plan)

    def test_release_notes_claim_remap_count_is_enforced(self) -> None:
        documents = copy.deepcopy(self.documents)
        source = {"source_id": "doc.release-notes"}
        documents["systems"]["discrepancies_and_boundaries"][0]["sources"].append(
            source
        )
        self.assert_invalid(documents=documents)

    def test_same_id_distinct_uri_rename_is_required(self) -> None:
        plan = copy.deepcopy(self.plan)
        plan["source_merge"]["source_id_renames"] = []
        self.assert_invalid(plan=plan)

    def test_every_renamed_agent_claim_is_accounted_for(self) -> None:
        documents = copy.deepcopy(self.documents)
        documents["agent-smartcity"]["enrichments"][1]["source_claims_add"].append(
            {
                "source_id": "video-analytics-mcp-doc-3.2.1",
                "locator": "mutation",
            }
        )
        self.assert_invalid(documents=documents)

    def test_unresolved_same_id_distinct_uri_collision_is_rejected(self) -> None:
        documents = copy.deepcopy(self.documents)
        documents["agent-smartcity"]["sources"][0]["id"] = "release-notes-3.2.1"
        self.assert_invalid(documents=documents)

    def test_unknown_candidate_source_claim_is_rejected(self) -> None:
        documents = copy.deepcopy(self.documents)
        documents["agent-smartcity"]["enrichments"][0]["source_claims_add"][0][
            "source_id"
        ] = "missing-source-id"
        self.assert_invalid(documents=documents)

    def test_live_capability_collision_is_rejected(self) -> None:
        documents = copy.deepcopy(self.documents)
        documents["agent-smartcity"]["new_capabilities"][0]["id"] = documents[
            "live-ledger"
        ]["capabilities"][0]["id"]
        self.assert_invalid(documents=documents)

    def test_cross_package_capability_collision_is_rejected(self) -> None:
        documents = copy.deepcopy(self.documents)
        documents["calibration-warehouse"]["new_capabilities"][0]["id"] = documents[
            "agent-smartcity"
        ]["new_capabilities"][0]["id"]
        self.assert_invalid(documents=documents)

    def test_unapproved_enrichment_collision_is_rejected(self) -> None:
        documents = copy.deepcopy(self.documents)
        documents["calibration-warehouse"]["enrichments"][0]["target_id"] = (
            "api.core.video-analytics-56"
        )
        self.assert_invalid(documents=documents)

    def test_video_analytics_smart_city_contract_is_preserved(self) -> None:
        documents = copy.deepcopy(self.documents)
        enrichment = next(
            item
            for item in documents["agent-smartcity"]["enrichments"]
            if item["target_id"] == "api.core.video-analytics-56"
        )
        enrichment["contract_merge"] = {"query_families": []}
        self.assert_invalid(documents=documents)

    def test_video_analytics_systems_contract_is_preserved(self) -> None:
        documents = copy.deepcopy(self.documents)
        enrichment = next(
            item
            for item in documents["systems"]["enrichments"]
            if item["target_id"] == "api.core.video-analytics-56"
        )
        enrichment["contract_merge"] = {"smart_city_uploads": {}}
        self.assert_invalid(documents=documents)

    def test_calibration_output_union_mutation_is_rejected(self) -> None:
        plan = copy.deepcopy(self.plan)
        collision = next(
            item
            for item in plan["capability_merge"]["approved_enrichment_collisions"]
            if item["target_id"] == "calibration.sdg.workflow"
        )
        collision["output_union"].pop()
        self.assert_invalid(plan=plan)

    def test_calibration_contributor_mutation_is_rejected(self) -> None:
        plan = copy.deepcopy(self.plan)
        collision = next(
            item
            for item in plan["capability_merge"]["approved_enrichment_collisions"]
            if item["target_id"] == "calibration.sdg.workflow"
        )
        collision["contributors"].reverse()
        self.assert_invalid(plan=plan)

    def test_calibration_external_status_correction_is_required(self) -> None:
        documents = copy.deepcopy(self.documents)
        enrichment = next(
            item
            for item in documents["calibration-warehouse"]["enrichments"]
            if item["target_id"] == "calibration.sdg.workflow"
        )
        enrichment["contract_merge"]["acceptance_class_correction"] = (
            "alternate_local_lane"
        )
        self.assert_invalid(documents=documents)

    def test_smart_city_sdg_must_remain_external_optional(self) -> None:
        documents = copy.deepcopy(self.documents)
        capability = next(
            item
            for item in documents["agent-smartcity"]["new_capabilities"]
            if item["id"] == "tooling.smart-city.synthetic-data-pipeline"
        )
        capability["status"]["acceptance_class"] = "alternate_local_lane"
        self.assert_invalid(documents=documents)

    def test_smart_city_training_must_remain_external_optional(self) -> None:
        documents = copy.deepcopy(self.documents)
        capability = next(
            item
            for item in documents["agent-smartcity"]["new_capabilities"]
            if item["id"] == "customization.smart-city.trafficcamnet-rtdetr"
        )
        capability["status"]["thor_state"] = "source_only"
        self.assert_invalid(documents=documents)

    def test_status_normalization_plan_mutation_is_rejected(self) -> None:
        plan = copy.deepcopy(self.plan)
        plan["status_normalizations"][0]["resolved_status"]["thor_state"] = (
            "external_optional"
        )
        self.assert_invalid(plan=plan)

    def test_fixture_collision_is_rejected(self) -> None:
        documents = copy.deepcopy(self.documents)
        agent_fixture = documents["agent-smartcity"]["new_capabilities"][0][
            "qualification"
        ]["fixtures"][0]["id"]
        documents["calibration-warehouse"]["acceptance_vectors"][0]["id"] = (
            agent_fixture
        )
        self.assert_invalid(documents=documents)

    def test_systems_acceptance_fixture_collision_is_rejected(self) -> None:
        documents = copy.deepcopy(self.documents)
        agent_fixture = documents["agent-smartcity"]["new_capabilities"][0][
            "qualification"
        ]["fixtures"][0]["id"]
        documents["systems"]["proposed_capabilities"][0]["acceptance"][
            "fixture_id"
        ] = agent_fixture
        self.assert_invalid(documents=documents)

    def test_discrepancy_id_collision_is_rejected(self) -> None:
        documents = copy.deepcopy(self.documents)
        documents["agent-smartcity"]["discrepancies"][0]["id"] = documents[
            "live-ledger"
        ]["source_discrepancies"][0]["id"]
        self.assert_invalid(documents=documents)

    def test_guardrail_id_collision_is_rejected(self) -> None:
        documents = copy.deepcopy(self.documents)
        documents["calibration-warehouse"]["guardrails"][0]["id"] = documents[
            "agent-smartcity"
        ]["guardrails"][0]["id"]
        self.assert_invalid(documents=documents)

    def test_fixture_collision_cannot_be_approved_ad_hoc(self) -> None:
        plan = copy.deepcopy(self.plan)
        plan["fixture_merge"]["approved_collisions"] = ["mutation"]
        self.assert_invalid(plan=plan)

    def test_published_count_mutation_is_rejected(self) -> None:
        plan = copy.deepcopy(self.plan)
        plan["counts"]["proposed_capabilities"] = 277
        self.assert_invalid(plan=plan)


if __name__ == "__main__":
    unittest.main()
