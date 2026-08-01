# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


PARITY_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PARITY_DIR))

import capability_oracles as verifier  # noqa: E402


class CapabilityOracleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = json.loads(verifier.ORACLES.read_text(encoding="utf-8"))
        cls.ledger = json.loads(verifier.LEDGER.read_text(encoding="utf-8"))
        cls.protocol_cases = json.loads(verifier.PROTOCOL_CASES.read_text(encoding="utf-8"))

    def test_checked_in_plan_has_one_oracle_per_capability(self) -> None:
        counts = verifier.validate(copy.deepcopy(self.plan), copy.deepcopy(self.ledger))
        capability_count = len(self.ledger["capabilities"])
        external_count = sum(
            item["acceptance_class"] == "external_optional"
            for item in self.ledger["capabilities"]
        )
        self.assertEqual(counts["capabilities"], capability_count)
        self.assertEqual(counts["oracles"], capability_count)
        self.assertEqual(counts["open_runtime"], capability_count - external_count)
        self.assertEqual(counts["external_boundaries"], external_count)
        self.assertEqual(counts["planning_index_only"], capability_count)
        self.assertEqual(counts["executor_ready"], 0)
        self.assertGreater(counts["profiles"], 0)

    def test_every_execution_mode_is_covered(self) -> None:
        self.assertEqual(
            {item["mode"] for item in self.plan["oracles"]},
            {"static", "config", "runtime", "api", "protocol", "model", "deploy"},
        )

    def test_missing_capability_oracle_fails_closed(self) -> None:
        plan = copy.deepcopy(self.plan)
        plan["oracles"].pop()
        with self.assertRaisesRegex(verifier.OracleContractError, "coverage drift"):
            verifier.validate(plan, copy.deepcopy(self.ledger))

    def test_contract_assertion_drift_fails_closed(self) -> None:
        plan = copy.deepcopy(self.plan)
        plan["oracles"][0]["assertions"][0]["expected"] = "wrong-model"
        with self.assertRaisesRegex(verifier.OracleContractError, "oracle contract drift"):
            verifier.validate(plan, copy.deepcopy(self.ledger))

    def test_generic_action_reuse_fails_closed(self) -> None:
        plan = copy.deepcopy(self.plan)
        first, second = plan["oracles"][:2]
        second["fixture"] = copy.deepcopy(first["fixture"])
        second["expected_observations"] = copy.deepcopy(first["expected_observations"])
        second["assertions"] = copy.deepcopy(first["assertions"])
        with self.assertRaisesRegex(verifier.OracleContractError, "oracle contract drift"):
            verifier.validate(plan, copy.deepcopy(self.ledger))

    def test_fabricated_pass_or_evidence_fails_closed(self) -> None:
        for field, value in (("current_state", "passed_current"), ("evidence", [{"result": "pass"}])):
            with self.subTest(field=field):
                plan = copy.deepcopy(self.plan)
                plan["oracles"][0][field] = value
                with self.assertRaises(verifier.OracleContractError):
                    verifier.validate(plan, copy.deepcopy(self.ledger))

    def test_every_oracle_has_unique_capability_bound_identities(self) -> None:
        triples = [
            (
                item["oracle_id"],
                item["fixture"]["id"],
                item["reviewed_scenario_ids"][-1],
            )
            for item in self.plan["oracles"]
        ]
        self.assertEqual(len(triples), len(set(triples)))
        for item in self.plan["oracles"]:
            capability_id = item["capability_id"]
            self.assertEqual(item["oracle_id"], f"oracle.{capability_id}")
            self.assertEqual(item["fixture"]["input"]["capability_id"], capability_id)
            self.assertEqual(item["reviewed_scenario_ids"][-1], f"oracle.{capability_id}")

    def test_warehouse_sample_is_excluded_but_custom_fixtures_remain(self) -> None:
        self.assertTrue(all(not item["fixture"]["warehouse_sample_bundle"] for item in self.plan["oracles"]))
        calibration = [item for item in self.plan["oracles"] if item["capability_id"].startswith("calibration.")]
        self.assertTrue(calibration)
        expected = {
            item["capability_id"]: (
                "operator_external_contract"
                if item["capability_id"] == "calibration.sdg.workflow"
                else "generated_custom_media"
            )
            for item in calibration
        }
        self.assertEqual(
            {item["capability_id"]: item["fixture"]["kind"] for item in calibration},
            expected,
        )

    def test_cleanup_intent_is_namespaced_and_planning_only(self) -> None:
        local = [item for item in self.plan["oracles"] if item["current_state"] == "open_unexecuted"]
        for item in local:
            cleanup = item["cleanup"]
            self.assertIn(cleanup["mutation"], {"read_only", "temporary_files_only", "namespaced_and_reversible"})
            if cleanup["mutation"] == "read_only":
                self.assertEqual(cleanup["targets"], [])
            else:
                self.assertEqual(len(cleanup["targets"]), 1)
                self.assertTrue(cleanup["targets"][0].startswith("vss-oracle-"))
                self.assertEqual(cleanup["allowlist"], cleanup["targets"])
            self.assertTrue(cleanup["postconditions"])

    def test_external_boundaries_require_operator_opt_in(self) -> None:
        external = [item for item in self.plan["oracles"] if item["current_state"] == "external_boundary_unexecuted"]
        expected = sum(
            item["acceptance_class"] == "external_optional"
            for item in self.ledger["capabilities"]
        )
        self.assertEqual(len(external), expected)
        for item in external:
            gate_ids = {gate["id"] for gate in item["admission_prerequisites"]}
            self.assertIn("external-opt-in", gate_ids)
            self.assertEqual(item["cleanup"]["mutation"], "none_by_default")

    def test_ledger_contract_change_requires_oracle_regeneration(self) -> None:
        ledger = copy.deepcopy(self.ledger)
        ledger["capabilities"][0]["contract"]["new_contract_field"] = "new-value"
        with self.assertRaisesRegex(verifier.OracleContractError, "oracle contract drift"):
            verifier.validate(copy.deepcopy(self.plan), ledger)

    def test_relevant_ledger_semantics_require_oracle_regeneration(self) -> None:
        mutations = {
            "source locator": lambda item: item["source_claims"][0].update(locator="different locator"),
            "gap": lambda item: item.update(gap="different reviewed gap"),
            "thor state": lambda item: item.update(thor_state="wired"),
            "runtime state": lambda item: item.update(runtime_state="static_only"),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                ledger = copy.deepcopy(self.ledger)
                mutate(ledger["capabilities"][0])
                with self.assertRaisesRegex(verifier.OracleContractError, "oracle contract drift"):
                    verifier.validate(copy.deepcopy(self.plan), ledger)

    def test_media_requiring_capabilities_use_custom_media_fixtures(self) -> None:
        required = {
            "customization.siglip2",
            "customization.cosmos-embed1",
            "performance.search",
            "performance.rt-embed",
            "api.core.rt-embed-24",
        }
        by_id = {item["capability_id"]: item for item in self.plan["oracles"]}
        self.assertTrue(required <= set(by_id))
        for capability_id in required:
            self.assertEqual(by_id[capability_id]["fixture"]["kind"], "generated_custom_media")

    def test_request_bounds_are_arithmetically_exact(self) -> None:
        for item in self.plan["oracles"]:
            bounds = item["execution_bounds"]
            workload = bounds["workload"]
            expected = workload["units"] * workload["requests_per_unit"] + workload["overhead_requests"]
            self.assertEqual(workload["calculated_max_requests"], expected)
            self.assertEqual(bounds["max_requests"], expected)
        by_id = {item["capability_id"]: item for item in self.plan["oracles"]}
        self.assertEqual(by_id["behavior.rt-embed.kafka-queue-bound"]["execution_bounds"]["max_requests"], 1025)
        self.assertEqual(by_id["api.core.video-analytics-56"]["execution_bounds"]["max_requests"], 225)
        self.assertEqual(
            by_id["api.core.video-analytics-56"]["execution_bounds"]["workload"]["phases"],
            ["positive", "adjacent_negative", "readback", "cleanup"],
        )

    def test_models_stage_before_runtime_not_inside_it(self) -> None:
        models = [item for item in self.plan["oracles"] if item["ledger_binding"]["kind"] == "model"]
        self.assertTrue(models)
        for item in models:
            self.assertEqual(item["execution_bounds"]["model_staging"], "prerequisite_only")
            self.assertIn("model-artifact-staged", {gate["id"] for gate in item["admission_prerequisites"]})

    def test_custom_thor_lane_is_bounded_per_profile_runtime(self) -> None:
        oracle = next(item for item in self.plan["oracles"] if item["capability_id"] == "boundary.thor.custom-all-local-extension")
        profiles = oracle["ledger_binding"]["contract"]["profiles"]
        self.assertEqual(oracle["mode"], "runtime")
        self.assertEqual(oracle["execution_bounds"]["workload"]["units"], len(profiles))
        observation_ids = {item["id"] for item in oracle["expected_observations"]}
        self.assertTrue({f"profile_{item.replace('-', '_')}" for item in profiles} <= observation_ids)
        self.assertIn("sample_exclusion", observation_ids)

    def test_orchestrator_separates_discovery_from_approved_lifecycle(self) -> None:
        oracle = next(item for item in self.plan["oracles"] if item["capability_id"] == "api.orchestrator-mcp.tools-9")
        self.assertEqual(oracle["mode"], "runtime")
        self.assertIn("orchestrator-lifecycle-approval", {gate["id"] for gate in oracle["admission_prerequisites"]})
        observation_ids = [item["id"] for item in oracle["expected_observations"]]
        self.assertIn("discovery_phase", observation_ids)
        self.assertIn("approved_lifecycle_phase", observation_ids)
        self.assertIn("only after explicit lifecycle approval", oracle["fixture"]["input"]["action"])
        self.assertEqual(
            oracle["execution_bounds"]["workload"]["phases"],
            ["schema_discovery", "approved_lifecycle", "state_readback", "cleanup"],
        )

    def test_seven_protocol_oracles_bind_exact_case_contracts(self) -> None:
        protocol_oracles = [
            item
            for item in self.plan["oracles"]
            if item["ledger_binding"]["kind"] == "protocol"
        ]
        self.assertEqual(len(protocol_oracles), 7)
        cases = {
            item["capability_id"]: item
            for item in self.protocol_cases["cases"]
        }
        for oracle in protocol_oracles:
            case = cases[oracle["capability_id"]]
            binding = oracle["protocol_case_binding"]
            self.assertEqual(binding["path"], verifier.PROTOCOL_CASES_PATH)
            self.assertEqual(binding["file_sha256"], verifier.PROTOCOL_CASES_FILE_SHA256)
            self.assertEqual(binding["contract_set_sha256"], verifier.PROTOCOL_CASES_SET_SHA256)
            self.assertEqual(binding["target_commit"], self.protocol_cases["target_commit"])
            self.assertEqual(binding["case_id"], case["case_id"])
            self.assertEqual(binding["positive_vector_id"], case["positive_vector"]["id"])
            self.assertEqual(
                binding["negative_vector_ids"],
                [item["id"] for item in case["adjacent_negative_vectors"]],
            )
            self.assertEqual(
                binding["source_hashes"],
                [
                    {
                        "path": source["path"],
                        "git_blob_oid": source["git_blob_oid"],
                        "content_sha256": source["content_sha256"],
                    }
                    for source in case["sources"]
                ],
            )

    def test_protocol_binding_hash_and_case_mismatch_fail_closed(self) -> None:
        for label, mutate in {
            "whole hash": lambda binding: binding.update(file_sha256="0" * 64),
            "set hash": lambda binding: binding.update(contract_set_sha256="0" * 64),
            "case id": lambda binding: binding.update(case_id="wrong-case"),
            "source hash": lambda binding: binding["source_hashes"][0].update(content_sha256="0" * 64),
        }.items():
            with self.subTest(label=label):
                plan = copy.deepcopy(self.plan)
                oracle = next(
                    item
                    for item in plan["oracles"]
                    if item["capability_id"] == "protocol.agent.websocket"
                )
                mutate(oracle["protocol_case_binding"])
                with self.assertRaises(verifier.OracleContractError):
                    verifier.validate(plan, copy.deepcopy(self.ledger))

    def test_unknown_capability_kind_has_no_generic_fallback(self) -> None:
        ledger = copy.deepcopy(self.ledger)
        ledger["capabilities"][0]["kind"] = "unknown"
        with self.assertRaisesRegex(verifier.OracleContractError, "no oracle profile"):
            verifier.compile_plan(ledger)

    def test_new_reviewed_claim_is_compiled_without_count_or_source_assumptions(self) -> None:
        ledger = copy.deepcopy(self.ledger)
        capability = copy.deepcopy(
            next(item for item in ledger["capabilities"] if item["kind"] == "api")
        )
        capability.update(
            id="api.future.reviewed-surface",
            title="Future reviewed API surface",
            contract={"method": "GET", "path": "/v1/future"},
        )
        ledger["capabilities"].append(capability)
        compiled = verifier.compile_plan(ledger)
        oracle = compiled["oracles"][-1]
        self.assertEqual(len(compiled["oracles"]), len(self.plan["oracles"]) + 1)
        self.assertEqual(oracle["capability_id"], capability["id"])
        self.assertIn(capability["title"], oracle["fixture"]["input"]["action"])
        self.assertEqual(oracle["fixture"]["input"]["contract"], capability["contract"])

    def test_new_required_local_deployment_is_not_misclassified_external(self) -> None:
        ledger = copy.deepcopy(self.ledger)
        capability = copy.deepcopy(
            next(item for item in ledger["capabilities"] if item["kind"] == "deployment")
        )
        capability.update(
            id="deployment.future.local-profile",
            title="Future required local deployment profile",
            acceptance_class="required_local",
            thor_state="source_only",
            runtime_state="not_qualified",
            contract={"platform": "thor", "profile": "future-local"},
        )
        ledger["capabilities"].append(capability)
        oracle = verifier.compile_plan(ledger)["oracles"][-1]
        self.assertTrue(oracle["profile"].startswith("local-deployment-"))
        self.assertEqual(oracle["current_state"], "open_unexecuted")
        self.assertEqual(oracle["execution_bounds"]["network_scope"], "loopback-or-compose-internal")
        self.assertIn("local namespace", oracle["fixture"]["input"]["action"])
        self.assertEqual(oracle["expected_observations"][-1]["id"], "local_admission")

    def test_duplicate_json_keys_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "duplicate.json"
            path.write_text('{"schema_version": 1, "schema_version": 1}', encoding="utf-8")
            with self.assertRaisesRegex(verifier.OracleContractError, "duplicate JSON key"):
                verifier._load(path)


if __name__ == "__main__":
    unittest.main()
