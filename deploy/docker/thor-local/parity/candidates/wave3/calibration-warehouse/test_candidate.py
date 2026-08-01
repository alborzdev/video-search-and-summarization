# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

import validate_candidate as validator


class CalibrationWarehouseWave3CandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.package = validator.load_json(validator.CANDIDATE)
        cls.live_ledger = validator.load_json(validator.LIVE_LEDGER)
        cls.live_manifest = validator.load_json(validator.LIVE_MANIFEST)
        cls.live_acceptance = validator.load_json(validator.LIVE_ACCEPTANCE)
        cls.recursive_targets = validator.load_json(validator.RECURSIVE_TARGETS)
        cls.agent_candidate = validator.load_json(validator.AGENT_CANDIDATE)
        cls.systems_candidate = validator.load_json(validator.SYSTEMS_CANDIDATE)

    def _validate(
        self,
        package: dict | None = None,
        *,
        live_ledger: dict | None = None,
        agent_candidate: dict | None = None,
        systems_candidate: dict | None = None,
        check_live_hashes: bool = False,
    ) -> dict[str, int]:
        return validator.validate(
            copy.deepcopy(self.package if package is None else package),
            live_ledger=copy.deepcopy(self.live_ledger if live_ledger is None else live_ledger),
            live_manifest=copy.deepcopy(self.live_manifest),
            live_acceptance=copy.deepcopy(self.live_acceptance),
            recursive_targets=copy.deepcopy(self.recursive_targets),
            agent_candidate=copy.deepcopy(
                self.agent_candidate if agent_candidate is None else agent_candidate
            ),
            systems_candidate=copy.deepcopy(
                self.systems_candidate if systems_candidate is None else systems_candidate
            ),
            check_live_hashes=check_live_hashes,
        )

    def test_checked_in_candidate_has_exact_counts_and_hashes(self) -> None:
        self.assertEqual(
            self._validate(check_live_hashes=True),
            {
                "reviewed_sources": 33,
                "claim_bearing_sources": 27,
                "navigation_duplicate_sources": 6,
                "new_capabilities": 26,
                "enrichments": 20,
                "discrepancies": 4,
                "guardrails": 6,
                "acceptance_vectors": 7,
            },
        )

    def test_all_sources_bind_to_recursive_coverage(self) -> None:
        targets = set(self.recursive_targets["targets"])
        self.assertEqual(
            {item["uri"] for item in self.package["sources"]} - targets,
            set(),
        )

    def test_duplicate_json_keys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "duplicate.json"
            path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
            with self.assertRaisesRegex(validator.CandidateContractError, "duplicate JSON key"):
                validator.load_json(path)

    def test_recursive_uri_substitution_is_rejected(self) -> None:
        package = copy.deepcopy(self.package)
        package["sources"][0]["recursive_target_uri"] = package["sources"][1]["uri"]
        with self.assertRaisesRegex(validator.CandidateContractError, "recursive source binding mismatch"):
            self._validate(package)

    def test_source_outside_recursive_graph_is_rejected(self) -> None:
        package = copy.deepcopy(self.package)
        source = package["sources"][0]
        source["uri"] = source["recursive_target_uri"] = (
            "https://docs.nvidia.com/vss/3.2.1/not-in-fixed-point.html"
        )
        with self.assertRaisesRegex(validator.CandidateContractError, "outside recursive coverage"):
            self._validate(package)

    def test_non_claim_page_cannot_support_claim(self) -> None:
        package = copy.deepcopy(self.package)
        package["new_capabilities"][0]["source_claims"][0]["source_id"] = (
            "warehouse-accuracy-doc-3.2.1"
        )
        with self.assertRaisesRegex(validator.CandidateContractError, "non-claim-bearing source"):
            self._validate(package)

    def test_every_claim_bearing_source_must_have_claim(self) -> None:
        package = copy.deepcopy(self.package)
        source_id = "warehouse-sdg-scene-saving-doc-3.2.1"
        for capability in package["new_capabilities"]:
            capability["source_claims"] = [
                claim for claim in capability["source_claims"] if claim["source_id"] != source_id
            ]
        with self.assertRaisesRegex(
            validator.CandidateContractError,
            "claim-bearing source lacks claim|schema violation",
        ):
            self._validate(package)

    def test_new_capability_live_overlap_is_rejected(self) -> None:
        live = copy.deepcopy(self.live_ledger)
        live["capabilities"].append({"id": self.package["new_capabilities"][0]["id"]})
        with self.assertRaisesRegex(validator.CandidateContractError, "already exists live"):
            self._validate(live_ledger=live)

    def test_unknown_acceptance_vector_is_rejected(self) -> None:
        package = copy.deepcopy(self.package)
        package["new_capabilities"][0]["qualification"]["acceptance_vector_ids"] = [
            "missing-vector"
        ]
        with self.assertRaisesRegex(validator.CandidateContractError, "unknown acceptance vector"):
            self._validate(package)

    def test_simulation_external_vector_is_present_and_inert(self) -> None:
        vector = next(
            item
            for item in self.package["acceptance_vectors"]
            if item["id"] == "simulation-external-boundary"
        )
        self.assertEqual(vector["type"], "static")
        self.assertTrue(vector["assertions"]["inert"])
        self.assertFalse(vector["assertions"]["thor_runtime_dependency"])

    def test_cross_package_target_must_exist(self) -> None:
        package = copy.deepcopy(self.package)
        enrichment = next(
            item for item in package["enrichments"] if item["target_id"] == "calibration.sdg.workflow"
        )
        enrichment["merge_targets"][1]["id"] = "missing.cross.package.target"
        with self.assertRaisesRegex(validator.CandidateContractError, "cross-package merge target missing"):
            self._validate(package)

    def test_calibration_sdg_multi_merge_policy_is_exact(self) -> None:
        enrichment = next(
            item
            for item in self.package["enrichments"]
            if item["target_id"] == "calibration.sdg.workflow"
        )
        self.assertEqual(
            {(item["package"], item["id"]) for item in enrichment["merge_targets"]},
            {
                ("live_ledger", "calibration.sdg.workflow"),
                ("wave3/agent-smartcity", "calibration.sdg.workflow"),
            },
        )
        self.assertEqual(
            enrichment["contract_merge"]["acceptance_class_correction"],
            "external_optional",
        )

    def test_agent_cross_package_digest_drift_is_rejected(self) -> None:
        candidate = copy.deepcopy(self.agent_candidate)
        candidate["scope"]["operator_custom_data"] = "mutated"
        with self.assertRaisesRegex(validator.CandidateContractError, "Agent/SmartCity.*digest drift"):
            self._validate(agent_candidate=candidate)

    def test_systems_cross_package_digest_drift_is_rejected(self) -> None:
        candidate = copy.deepcopy(self.systems_candidate)
        candidate["scope"]["live_files_untouched"] = False
        with self.assertRaisesRegex(validator.CandidateContractError, "Systems.*digest drift"):
            self._validate(systems_candidate=candidate)

    def test_candidate_canonical_digest_rejects_contract_substitution(self) -> None:
        package = copy.deepcopy(self.package)
        package["new_capabilities"][0]["title"] = "Substituted but schema-valid title"
        with self.assertRaisesRegex(validator.CandidateContractError, "canonical candidate digest drift"):
            self._validate(package)

    def test_runtime_pass_states_are_rejected(self) -> None:
        for state in ("passed_current", "passed_prior"):
            with self.subTest(state=state):
                package = copy.deepcopy(self.package)
                package["new_capabilities"][0]["status"]["runtime_state"] = state
                with self.assertRaisesRegex(validator.CandidateContractError, "cannot claim runtime pass"):
                    self._validate(package)

    def test_sample_bundle_scope_is_fail_closed(self) -> None:
        package = copy.deepcopy(self.package)
        package["scope"]["warehouse_sample_bundle"] = "required"
        with self.assertRaisesRegex(validator.CandidateContractError, "schema violation"):
            self._validate(package)

    def test_acceptance_vector_cannot_require_sample_bundle(self) -> None:
        package = copy.deepcopy(self.package)
        package["acceptance_vectors"][0]["sample_bundle_required"] = True
        with self.assertRaisesRegex(validator.CandidateContractError, "schema violation"):
            self._validate(package)

    def test_custom_input_capability_cannot_require_sample_bundle(self) -> None:
        package = copy.deepcopy(self.package)
        capability = next(
            item
            for item in package["new_capabilities"]
            if item["id"] == "configuration.warehouse.custom-inputs"
        )
        capability["contract"]["sample_bundle_required"] = True
        with self.assertRaisesRegex(validator.CandidateContractError, "sample bundle became required"):
            self._validate(package)

    def test_agx_igx_platform_overclaim_is_rejected(self) -> None:
        mutations = {
            "official_platform": "AGX-Thor",
            "official_bsp": "38.4",
            "host_bsp": "38.5",
            "official_host_match": True,
            "must_not_claim_official_support": False,
        }
        for key, value in mutations.items():
            with self.subTest(key=key):
                package = copy.deepcopy(self.package)
                capability = next(
                    item
                    for item in package["new_capabilities"]
                    if item["id"] == "prereq.warehouse.thor-platform"
                )
                capability["contract"][key] = value
                with self.assertRaisesRegex(
                    validator.CandidateContractError,
                    "AGX/IGX or 38.4/38.5 support boundary drift",
                ):
                    self._validate(package)

    def test_amc_on_thor_overclaim_is_rejected(self) -> None:
        package = copy.deepcopy(self.package)
        discrepancy = next(
            item
            for item in package["discrepancies"]
            if item["id"] == "warehouse-autocalibration-platform-surface"
        )
        discrepancy["must_not_claim"] = "AMC works officially on Thor."
        with self.assertRaisesRegex(validator.CandidateContractError, "AMC-on-Thor support boundary"):
            self._validate(package)

    def test_single_gpu_agent_vlm_overclaim_is_rejected(self) -> None:
        package = copy.deepcopy(self.package)
        capability = next(
            item
            for item in package["new_capabilities"]
            if item["id"] == "configuration.warehouse.profile-hardware-matrix"
        )
        capability["contract"]["single_gpu_agent_vlm_officially_supported"] = True
        with self.assertRaisesRegex(validator.CandidateContractError, "single-GPU.*overclaim"):
            self._validate(package)

    def test_destructive_faq_commands_remain_operator_gated(self) -> None:
        for key in ("automatic_execution_forbidden", "explicit_operator_authorization_required"):
            package = copy.deepcopy(self.package)
            capability = next(
                item
                for item in package["new_capabilities"]
                if item["id"] == "behavior.warehouse.destructive-troubleshooting-boundaries"
            )
            capability["contract"][key] = False
            with self.assertRaisesRegex(validator.CandidateContractError, "destructive FAQ command"):
                self._validate(package)

    def test_stale_sdg_path_record_cannot_be_erased(self) -> None:
        package = copy.deepcopy(self.package)
        discrepancy = next(
            item
            for item in package["discrepancies"]
            if item["id"] == "warehouse-sdg-stale-repository-paths"
        )
        discrepancy["observations"] = ["old path", "new path"]
        with self.assertRaisesRegex(validator.CandidateContractError, "stale SDG path boundary"):
            self._validate(package)

    def test_reference_benchmarks_cannot_become_thor_results(self) -> None:
        for key in ("reference_only", "must_not_claim_as_thor_result"):
            package = copy.deepcopy(self.package)
            capability = next(
                item
                for item in package["new_capabilities"]
                if item["id"] == "performance.warehouse.profile-latency"
            )
            capability["contract"][key] = False
            with self.assertRaisesRegex(validator.CandidateContractError, "benchmark numbers became"):
                self._validate(package)

    def test_simulation_cannot_become_thor_runtime_dependency(self) -> None:
        package = copy.deepcopy(self.package)
        capability = next(
            item
            for item in package["new_capabilities"]
            if item["id"] == "boundary.warehouse.sdg-toolchain"
        )
        capability["contract"]["runtime_dependency"] = True
        with self.assertRaisesRegex(validator.CandidateContractError, "simulation or training became"):
            self._validate(package)


if __name__ == "__main__":
    unittest.main()
