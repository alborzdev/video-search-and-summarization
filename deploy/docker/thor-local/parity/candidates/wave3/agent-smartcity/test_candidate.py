# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

import validate_candidate as validator


class AgentSmartCityWave3CandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.package = validator.load_json(validator.CANDIDATE)
        cls.live_ledger = validator.load_json(validator.LIVE_LEDGER)
        cls.live_manifest = validator.load_json(validator.LIVE_MANIFEST)
        cls.live_acceptance = validator.load_json(validator.LIVE_ACCEPTANCE)

    def _validate(
        self,
        package: dict | None = None,
        *,
        live_ledger: dict | None = None,
        check_live_hashes: bool = False,
    ) -> dict[str, int]:
        return validator.validate(
            copy.deepcopy(self.package if package is None else package),
            live_ledger=copy.deepcopy(self.live_ledger if live_ledger is None else live_ledger),
            live_manifest=copy.deepcopy(self.live_manifest),
            live_acceptance=copy.deepcopy(self.live_acceptance),
            check_live_hashes=check_live_hashes,
        )

    def test_checked_in_candidate_has_exact_counts(self) -> None:
        self.assertEqual(
            self._validate(check_live_hashes=True),
            {
                "reviewed_pages": 40,
                "claim_bearing_sources": 24,
                "new_capabilities": 34,
                "enrichments": 7,
                "discrepancies": 5,
                "guardrails": 4,
            },
        )

    def test_source_classification_counts_are_exact(self) -> None:
        counts: dict[str, int] = {}
        for source in self.package["sources"]:
            classification = source["classification"]
            counts[classification] = counts.get(classification, 0) + 1
        self.assertEqual(counts, validator.EXPECTED_SOURCE_CLASSES)

    def test_every_source_is_in_fixed_point_graph(self) -> None:
        graph = validator.load_json(validator.FIXED_POINT_GRAPH)
        targets = set(graph["targets"])
        self.assertTrue({item["uri"] for item in self.package["sources"]} <= targets)

    def test_stale_smartcity_license_url_is_rejected(self) -> None:
        package = copy.deepcopy(self.package)
        source = next(item for item in package["sources"] if item["id"] == "smartcity-license-doc-3.2.1")
        source["uri"] = "https://docs.nvidia.com/vss/3.2.1/smartcity-docs/License.html"
        with self.assertRaisesRegex(validator.CandidateContractError, "stale non-reachable source URL"):
            self._validate(package)

    def test_stale_smartcity_troubleshooting_url_is_rejected(self) -> None:
        package = copy.deepcopy(self.package)
        source = next(
            item
            for item in package["sources"]
            if item["id"] == "smartcity-troubleshooting-doc-3.2.1"
        )
        source["uri"] = "https://docs.nvidia.com/vss/3.2.1/smartcity-docs/Troubleshooting.html"
        with self.assertRaisesRegex(validator.CandidateContractError, "stale non-reachable source URL"):
            self._validate(package)

    def test_url_outside_fixed_point_graph_is_rejected(self) -> None:
        package = copy.deepcopy(self.package)
        package["sources"][0]["uri"] = "https://docs.nvidia.com/vss/3.2.1/not-in-index.html"
        with self.assertRaisesRegex(validator.CandidateContractError, "outside fixed-point URL graph"):
            self._validate(package)

    def test_reachable_source_substitution_is_rejected(self) -> None:
        package = copy.deepcopy(self.package)
        package["sources"][0]["uri"] = (
            "https://docs.nvidia.com/vss/3.2.1/edge-deployment.html"
        )
        with self.assertRaisesRegex(
            validator.CandidateContractError, "candidate content digest drift"
        ):
            self._validate(package)

    def test_unreviewed_contract_value_change_is_rejected(self) -> None:
        package = copy.deepcopy(self.package)
        capability = next(
            item
            for item in package["new_capabilities"]
            if item["id"] == "configuration.smart-city.behavior-rules"
        )
        capability["contract"]["speed_violation_mph"] = 999
        with self.assertRaisesRegex(
            validator.CandidateContractError, "candidate content digest drift"
        ):
            self._validate(package)

    def test_duplicate_json_keys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "duplicate.json"
            path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
            with self.assertRaisesRegex(validator.CandidateContractError, "duplicate JSON key"):
                validator.load_json(path)

    def test_new_capability_overlap_is_rejected(self) -> None:
        live_ledger = copy.deepcopy(self.live_ledger)
        proposed = copy.deepcopy(self.package["new_capabilities"][0])
        proposed["source_claims"] = []
        proposed.pop("status")
        proposed.pop("qualification")
        live_ledger["capabilities"].append(proposed)
        with self.assertRaisesRegex(validator.CandidateContractError, "already exists live"):
            self._validate(live_ledger=live_ledger)

    def test_missing_enrichment_target_is_rejected(self) -> None:
        package = copy.deepcopy(self.package)
        package["enrichments"][0]["target_id"] = "missing.target"
        with self.assertRaisesRegex(validator.CandidateContractError, "enrichment target missing"):
            self._validate(package)

    def test_unknown_scenario_is_rejected(self) -> None:
        package = copy.deepcopy(self.package)
        package["new_capabilities"][0]["qualification"]["scenario_ids"] = ["missing-scenario"]
        with self.assertRaisesRegex(validator.CandidateContractError, "unknown scenario"):
            self._validate(package)

    def test_non_claim_page_cannot_support_a_claim(self) -> None:
        package = copy.deepcopy(self.package)
        package["new_capabilities"][0]["source_claims"][0]["source_id"] = "agent-workflows-doc-3.2.1"
        with self.assertRaisesRegex(validator.CandidateContractError, "non-claim-bearing page"):
            self._validate(package)

    def test_extraction_cannot_claim_runtime_pass(self) -> None:
        for state in ("passed_current", "passed_prior"):
            with self.subTest(state=state):
                package = copy.deepcopy(self.package)
                package["new_capabilities"][0]["status"]["runtime_state"] = state
                with self.assertRaisesRegex(validator.CandidateContractError, "cannot claim runtime pass"):
                    self._validate(package)

    def test_warehouse_sample_exclusion_is_fail_closed(self) -> None:
        package = copy.deepcopy(self.package)
        package["scope"]["warehouse_sample_bundle"] = "included"
        with self.assertRaisesRegex(validator.CandidateContractError, "schema violation"):
            self._validate(package)

    def test_operator_custom_data_scope_is_fail_closed(self) -> None:
        package = copy.deepcopy(self.package)
        package["scope"]["operator_custom_data"] = "excluded"
        with self.assertRaisesRegex(validator.CandidateContractError, "schema violation"):
            self._validate(package)

    def test_smartcity_sample_cannot_become_required(self) -> None:
        package = copy.deepcopy(self.package)
        capability = next(
            item
            for item in package["new_capabilities"]
            if item["id"] == "configuration.smart-city.custom-location"
        )
        capability["contract"]["bundled_sample_required"] = True
        with self.assertRaisesRegex(validator.CandidateContractError, "bundled sample became required"):
            self._validate(package)

    def test_sdg_cannot_become_runtime_dependency(self) -> None:
        package = copy.deepcopy(self.package)
        capability = next(
            item
            for item in package["new_capabilities"]
            if item["id"] == "tooling.smart-city.synthetic-data-pipeline"
        )
        capability["contract"]["runtime_dependency"] = True
        with self.assertRaisesRegex(validator.CandidateContractError, "SDG became a runtime dependency"):
            self._validate(package)

    def test_smartcity_development_tools_remain_external_optional(self) -> None:
        for capability_id in (
            "tooling.smart-city.synthetic-data-pipeline",
            "customization.smart-city.trafficcamnet-rtdetr",
        ):
            with self.subTest(capability_id=capability_id):
                package = copy.deepcopy(self.package)
                capability = next(
                    item
                    for item in package["new_capabilities"]
                    if item["id"] == capability_id
                )
                capability["status"] = {
                    "acceptance_class": "alternate_local_lane",
                    "thor_state": "source_only",
                    "runtime_state": "not_qualified",
                }
                with self.assertRaisesRegex(
                    validator.CandidateContractError,
                    "external development boundary drift",
                ):
                    self._validate(package)

    def test_official_thor_support_claim_is_rejected(self) -> None:
        package = copy.deepcopy(self.package)
        capability = next(
            item
            for item in package["new_capabilities"]
            if item["id"] == "prereq.smart-city.reference-platform"
        )
        capability["contract"]["official_thor_support"] = True
        with self.assertRaisesRegex(validator.CandidateContractError, "official Smart City Thor support"):
            self._validate(package)

    def test_google_maps_alternate_cannot_claim_identical_parity(self) -> None:
        package = copy.deepcopy(self.package)
        capability = next(
            item
            for item in package["new_capabilities"]
            if item["id"] == "boundary.smart-city.google-maps-dependency"
        )
        capability["contract"]["alternate_is_not_official_google_map_parity"] = False
        with self.assertRaisesRegex(validator.CandidateContractError, "Google Maps/local alternate"):
            self._validate(package)

    def test_vlm_fine_tuning_must_remain_forthcoming(self) -> None:
        package = copy.deepcopy(self.package)
        capability = next(
            item
            for item in package["new_capabilities"]
            if item["id"] == "customization.smart-city.trafficcamnet-rtdetr"
        )
        capability["contract"]["vlm_fine_tuning"] = "available"
        with self.assertRaisesRegex(validator.CandidateContractError, "forthcoming VLM"):
            self._validate(package)

    def test_nemoclaw_deep_clean_remains_operator_gated(self) -> None:
        package = copy.deepcopy(self.package)
        capability = next(
            item
            for item in package["new_capabilities"]
            if item["id"] == "behavior.nemoclaw.recovery-and-destructive-boundaries"
        )
        capability["contract"]["deep_clean_requires_explicit_authorization"] = False
        with self.assertRaisesRegex(validator.CandidateContractError, "destructive authorization"):
            self._validate(package)

    def test_documented_limitations_cannot_be_marked_remediated(self) -> None:
        package = copy.deepcopy(self.package)
        capability = next(
            item
            for item in package["new_capabilities"]
            if item["id"] == "behavior.smart-city.known-limitations"
        )
        capability["contract"]["must_not_claim_remediated"] = False
        with self.assertRaisesRegex(validator.CandidateContractError, "limitations boundary"):
            self._validate(package)


if __name__ == "__main__":
    unittest.main()
