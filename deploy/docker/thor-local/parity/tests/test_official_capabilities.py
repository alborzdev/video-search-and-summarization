# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


PARITY_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PARITY_DIR))

import verify_official_capabilities as verifier  # noqa: E402


class OfficialCapabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ledger = json.loads(verifier.LEDGER.read_text(encoding="utf-8"))
        cls.manifest = json.loads(verifier.MANIFEST.read_text(encoding="utf-8"))
        cls.acceptance = json.loads(verifier.ACCEPTANCE.read_text(encoding="utf-8"))
        cls.oracles = json.loads(verifier.ORACLES.read_text(encoding="utf-8"))

    def _validate_runtime_evidence(
        self,
        mutate: object | None = None,
        *,
        raw_evidence: str | None = None,
        reference_path: str = "deploy/docker/thor-local/evidence.json",
        reference_digest: str | None = None,
    ) -> dict[str, int]:
        ledger = copy.deepcopy(self.ledger)
        capability = ledger["capabilities"][0]
        capability["runtime_state"] = "passed_current"
        evidence = {
            "schema_version": 1,
            "capability_id": capability["id"],
            "result": "passed_current",
            "target_commit": ledger["target"]["main_commit"],
            "captured_on": ledger["target"]["captured_on"],
            "scenario_ids": capability["scenario_ids"],
            "checks": [{"id": "semantic-oracle", "result": "pass"}],
        }
        if callable(mutate):
            mutate(evidence)
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            evidence_path = root / "deploy/docker/thor-local/evidence.json"
            evidence_path.parent.mkdir(parents=True)
            evidence_path.write_text(
                raw_evidence if raw_evidence is not None else json.dumps(evidence),
                encoding="utf-8",
            )
            for reviewed_capability in ledger["capabilities"]:
                manifest_path = reviewed_capability.get("contract", {}).get(
                    "expected_manifest"
                )
                if not manifest_path:
                    continue
                source = verifier.REPO_ROOT / manifest_path
                destination = root / manifest_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(source.read_bytes())
            digest = reference_digest or hashlib.sha256(evidence_path.read_bytes()).hexdigest()
            capability["runtime_evidence"] = [
                {"path": reference_path, "sha256": digest}
            ]
            return verifier.validate(
                ledger,
                copy.deepcopy(self.manifest),
                copy.deepcopy(self.acceptance),
                repo_root=root,
            )

    def _executor_ready_binding(
        self, capability_id: str | None = None
    ) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
        source_capability = (
            self.ledger["capabilities"][0]
            if capability_id is None
            else next(
                item
                for item in self.ledger["capabilities"]
                if item["id"] == capability_id
            )
        )
        capability = copy.deepcopy(source_capability)
        capability["runtime_state"] = "passed_current"
        oracle = copy.deepcopy(
            next(
                item
                for item in self.oracles["oracles"]
                if item["capability_id"] == capability["id"]
            )
        )
        oracle["ledger_binding"]["runtime_state"] = "passed_current"
        oracle["acceptance_readiness"] = {"classification": "executor_ready", "blockers": []}
        oracle["fixture"]["materialization"] = {
            "path": "deploy/docker/thor-local/qualification/fixtures/oracle.json",
            "generator": "deploy/docker/thor-local/qualification/generate-oracle-fixture.py",
            "sha256": "1" * 64,
        }
        oracle["execution_bounds"]["executor"] = "deploy/docker/thor-local/qualification/run-oracle.py"
        oracle["execution_bounds"]["collectors"] = [
            "deploy/docker/thor-local/qualification/collect-oracle.py"
        ]
        oracle["cleanup"]["executor"] = "deploy/docker/thor-local/qualification/cleanup-oracle.py"
        oracle["cleanup"]["postcondition_collectors"] = [
            "deploy/docker/thor-local/qualification/collect-cleanup.py"
        ]
        evidence = {
            "schema_version": 1,
            "capability_id": capability["id"],
            "oracle_id": oracle["oracle_id"],
            "oracle_sha256": verifier.oracle_contract.canonical_oracle_sha256(oracle),
            "result": "passed_current",
            "target": {
                "product_version": self.ledger["target"]["product_version"],
                "ga_commit": self.ledger["target"]["ga_commit"],
                "main_commit": self.ledger["target"]["main_commit"],
                "captured_on": self.ledger["target"]["captured_on"],
            },
            "scenario_ids": oracle["reviewed_scenario_ids"],
            "fixture": {
                "id": oracle["fixture"]["id"],
                "path": oracle["fixture"]["materialization"]["path"],
                "sha256": oracle["fixture"]["materialization"]["sha256"],
            },
            "observations": [
                {"id": item["id"], "result": "pass", "value": True}
                for item in oracle["expected_observations"]
            ],
            "assertions": [
                {
                    "id": item["id"],
                    "observation": item["observation"],
                    "operator": item["operator"],
                    "expected": copy.deepcopy(item["expected"]),
                    "observed": copy.deepcopy(item["expected"]),
                    "result": "pass",
                }
                for item in oracle["assertions"]
            ],
            "cleanup": {
                "result": "pass",
                "mutation": oracle["cleanup"]["mutation"],
                "targets": oracle["cleanup"]["targets"],
                "allowlist": oracle["cleanup"]["allowlist"],
                "pre_state_captured": True,
                "postconditions": [
                    {"description": item, "result": "pass"}
                    for item in oracle["cleanup"]["postconditions"]
                ],
            },
        }
        if "protocol_case_binding" in oracle:
            binding = oracle["protocol_case_binding"]
            evidence["protocol_case"] = {
                "path": binding["path"],
                "file_sha256": binding["file_sha256"],
                "contract_set_sha256": binding["contract_set_sha256"],
                "target_commit": binding["target_commit"],
                "case_id": binding["case_id"],
                "case_sha256": binding["case_sha256"],
                "positive_vector_id": binding["positive_vector_id"],
                "negative_vector_ids": copy.deepcopy(binding["negative_vector_ids"]),
                "source_hashes": copy.deepcopy(binding["source_hashes"]),
                "cleanup_result": "pass",
            }
        return capability, oracle, evidence

    def test_checked_in_contract_is_cross_linked(self) -> None:
        counts = verifier.validate(
            copy.deepcopy(self.ledger),
            copy.deepcopy(self.manifest),
            copy.deepcopy(self.acceptance),
        )
        self.assertEqual(counts["sources"], 33)
        self.assertEqual(counts["capabilities"], 131)
        self.assertEqual(counts["feature_families"], 18)
        self.assertEqual(counts["discrepancies"], 4)

    def test_every_source_must_back_a_precise_claim(self) -> None:
        ledger = copy.deepcopy(self.ledger)
        ledger["sources"].append(
            {
                "id": "unused-official-source",
                "kind": "versioned_official_docs",
                "uri": "https://docs.nvidia.com/vss/3.2.1/unused.html",
                "version": "3.2.1",
                "locator_policy": "Test-only unused source.",
                "claim_set_sha256": hashlib.sha256(b"[]").hexdigest(),
            }
        )
        with self.assertRaisesRegex(
            verifier.CapabilityContractError, "has no precise capability claim"
        ):
            verifier.validate(
                ledger,
                copy.deepcopy(self.manifest),
                copy.deepcopy(self.acceptance),
            )

    def test_core_operation_manifest_digest_is_fail_closed(self) -> None:
        ledger = copy.deepcopy(self.ledger)
        capability = next(
            item
            for item in ledger["capabilities"]
            if item["id"] == "api.core.rt-vlm-27"
        )
        capability["contract"]["expected_manifest_sha256"] = "0" * 64
        with self.assertRaisesRegex(
            verifier.CapabilityContractError, "operation manifest digest differs"
        ):
            verifier.validate(
                ledger,
                copy.deepcopy(self.manifest),
                copy.deepcopy(self.acceptance),
            )

    def test_lvs_mcp_discrepancy_remains_explicit(self) -> None:
        capability = next(
            item
            for item in self.ledger["capabilities"]
            if item["id"] == "api.core.lvs-mcp-doc-13-repo-9"
        )
        self.assertEqual(capability["contract"]["docs_tool_count"], 13)
        self.assertEqual(capability["contract"]["repository_tool_count"], 9)
        self.assertEqual(
            capability["contract"]["docs_only_tools"],
            ["add_file", "list_files", "get_file_info", "delete_file"],
        )
        self.assertEqual(capability["thor_state"], "blocked_upstream")

    def test_thor_support_boundary_does_not_claim_official_all_local(self) -> None:
        custom = next(
            item
            for item in self.ledger["capabilities"]
            if item["id"] == "boundary.thor.custom-all-local-extension"
        )
        future = next(
            item
            for item in self.ledger["capabilities"]
            if item["id"] == "boundary.thor.fully-local-future"
        )
        self.assertTrue(custom["contract"]["must_not_claim_official_support"])
        self.assertFalse(future["contract"]["official_3_2_1"])

    def test_unmapped_capability_fails_closed(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        feature = next(item for item in manifest["features"] if item.get("official_capability_ids"))
        feature["official_capability_ids"].pop()
        with self.assertRaisesRegex(verifier.CapabilityContractError, "cross-link drift"):
            verifier.validate(copy.deepcopy(self.ledger), manifest, copy.deepcopy(self.acceptance))

    def test_missing_acceptance_scenario_fails_closed(self) -> None:
        acceptance = copy.deepcopy(self.acceptance)
        acceptance["scenarios"] = [item for item in acceptance["scenarios"] if item["id"] != "official-capability-contracts"]
        with self.assertRaisesRegex(verifier.CapabilityContractError, "unknown acceptance scenario"):
            verifier.validate(copy.deepcopy(self.ledger), copy.deepcopy(self.manifest), acceptance)

    def test_passed_current_without_evidence_is_rejected(self) -> None:
        ledger = copy.deepcopy(self.ledger)
        ledger["capabilities"][0]["runtime_state"] = "passed_current"
        with self.assertRaises(verifier.CapabilityContractError):
            verifier.validate(ledger, copy.deepcopy(self.manifest), copy.deepcopy(self.acceptance))

    def test_arbitrary_generic_pass_check_cannot_advance(self) -> None:
        with self.assertRaisesRegex(
            verifier.CapabilityContractError, "planning_index_only"
        ):
            self._validate_runtime_evidence()

    def test_future_executor_ready_evidence_must_bind_exact_oracle(self) -> None:
        capability, oracle, evidence = self._executor_ready_binding()
        verifier._validate_bound_runtime_evidence(
            capability, oracle, evidence, self.ledger["target"]
        )

    def test_executor_evidence_oracle_hash_fixture_assertions_and_cleanup_fail_closed(self) -> None:
        mutations = {
            "oracle hash": lambda evidence: evidence.update(oracle_sha256="0" * 64),
            "fixture digest": lambda evidence: evidence["fixture"].update(sha256="0" * 64),
            "missing assertion": lambda evidence: evidence["assertions"].pop(),
            "changed expected value": lambda evidence: evidence["assertions"][0].update(expected="generic-pass"),
            "wrong observed value": lambda evidence: evidence["assertions"][0].update(observed="generic-pass"),
            "missing observation": lambda evidence: evidence["observations"].pop(),
            "cleanup failure": lambda evidence: evidence["cleanup"].update(result="fail"),
            "wrong release commit": lambda evidence: evidence["target"].update(ga_commit="0" * 40),
            "wrong oracle scenario": lambda evidence: evidence.update(scenario_ids=self.ledger["capabilities"][0]["scenario_ids"]),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                capability, oracle, evidence = self._executor_ready_binding()
                mutate(evidence)
                with self.assertRaises(verifier.CapabilityContractError):
                    verifier._validate_bound_runtime_evidence(
                        capability, oracle, evidence, self.ledger["target"]
                    )

    def test_protocol_executor_evidence_binds_case_hashes_vectors_sources_and_cleanup(self) -> None:
        capability_id = "protocol.agent.websocket"
        capability, oracle, evidence = self._executor_ready_binding(capability_id)
        verifier._validate_bound_runtime_evidence(
            capability, oracle, evidence, self.ledger["target"]
        )
        mutations = {
            "case id": lambda item: item["protocol_case"].update(case_id="wrong-case"),
            "whole file hash": lambda item: item["protocol_case"].update(file_sha256="0" * 64),
            "set hash": lambda item: item["protocol_case"].update(contract_set_sha256="0" * 64),
            "case hash": lambda item: item["protocol_case"].update(case_sha256="0" * 64),
            "positive vector": lambda item: item["protocol_case"].update(positive_vector_id="wrong-vector"),
            "negative vectors": lambda item: item["protocol_case"].update(negative_vector_ids=["wrong-vector"]),
            "source hashes": lambda item: item["protocol_case"]["source_hashes"][0].update(content_sha256="0" * 64),
            "cleanup result": lambda item: item["protocol_case"].update(cleanup_result="fail"),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                capability, oracle, evidence = self._executor_ready_binding(capability_id)
                mutate(evidence)
                with self.assertRaisesRegex(
                    verifier.CapabilityContractError, "protocol case evidence"
                ):
                    verifier._validate_bound_runtime_evidence(
                        capability, oracle, evidence, self.ledger["target"]
                    )

    def test_runtime_evidence_path_traversal_is_rejected(self) -> None:
        with self.assertRaisesRegex(verifier.CapabilityContractError, "unsafe runtime evidence path"):
            self._validate_runtime_evidence(
                reference_path="deploy/docker/thor-local/../../outside.json"
            )

    def test_runtime_evidence_parent_symlink_is_rejected(self) -> None:
        ledger = copy.deepcopy(self.ledger)
        capability = ledger["capabilities"][0]
        capability["runtime_state"] = "passed_current"
        evidence = {
            "schema_version": 1,
            "capability_id": capability["id"],
            "result": "passed_current",
            "target_commit": ledger["target"]["main_commit"],
            "captured_on": ledger["target"]["captured_on"],
            "scenario_ids": capability["scenario_ids"],
            "checks": [{"id": "semantic-oracle", "result": "pass"}],
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            real_directory = root / "real-evidence"
            real_directory.mkdir()
            evidence_path = real_directory / "evidence.json"
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
            link = root / "deploy/docker/thor-local"
            link.parent.mkdir(parents=True)
            link.symlink_to(real_directory, target_is_directory=True)
            capability["runtime_evidence"] = [
                {
                    "path": "deploy/docker/thor-local/evidence.json",
                    "sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
                }
            ]
            with self.assertRaisesRegex(verifier.CapabilityContractError, "contains a symlink"):
                verifier.validate(
                    ledger,
                    copy.deepcopy(self.manifest),
                    copy.deepcopy(self.acceptance),
                    repo_root=root,
                )

    def test_runtime_evidence_wrong_capability_is_rejected(self) -> None:
        with self.assertRaisesRegex(verifier.CapabilityContractError, "planning_index_only"):
            self._validate_runtime_evidence(
                lambda evidence: evidence.update(capability_id="different.capability")
            )

    def test_runtime_evidence_wrong_scenario_is_rejected(self) -> None:
        with self.assertRaisesRegex(verifier.CapabilityContractError, "planning_index_only"):
            self._validate_runtime_evidence(
                lambda evidence: evidence.update(scenario_ids=["different-scenario"])
            )

    def test_runtime_evidence_malformed_scenarios_are_rejected(self) -> None:
        with self.assertRaisesRegex(verifier.CapabilityContractError, "planning_index_only"):
            self._validate_runtime_evidence(
                lambda evidence: evidence.update(scenario_ids="official-capability-contracts")
            )

    def test_runtime_evidence_wrong_commit_is_rejected(self) -> None:
        with self.assertRaisesRegex(verifier.CapabilityContractError, "planning_index_only"):
            self._validate_runtime_evidence(
                lambda evidence: evidence.update(target_commit="0" * 40)
            )

    def test_runtime_evidence_duplicate_json_keys_are_rejected(self) -> None:
        duplicate = (
            '{"schema_version":1,"capability_id":"duplicate","capability_id":"duplicate",'
            '"result":"passed_current","target_commit":"duplicate","captured_on":"2026-07-31",'
            '"scenario_ids":["duplicate"],"checks":[{"id":"duplicate","result":"pass"}]}'
        )
        with self.assertRaisesRegex(verifier.CapabilityContractError, "duplicate JSON key"):
            self._validate_runtime_evidence(raw_evidence=duplicate)

    def test_runtime_evidence_failed_check_is_rejected(self) -> None:
        with self.assertRaisesRegex(verifier.CapabilityContractError, "planning_index_only"):
            self._validate_runtime_evidence(
                lambda evidence: evidence.update(
                    checks=[{"id": "semantic-oracle", "result": "fail"}]
                )
            )

    def test_runtime_evidence_check_without_id_is_rejected(self) -> None:
        with self.assertRaisesRegex(verifier.CapabilityContractError, "planning_index_only"):
            self._validate_runtime_evidence(
                lambda evidence: evidence.update(checks=[{"result": "pass"}])
            )

    def test_runtime_evidence_stale_hash_is_rejected(self) -> None:
        with self.assertRaisesRegex(verifier.CapabilityContractError, "digest differs"):
            self._validate_runtime_evidence(reference_digest="0" * 64)

    def test_runtime_evidence_stale_date_is_rejected(self) -> None:
        with self.assertRaisesRegex(verifier.CapabilityContractError, "planning_index_only"):
            self._validate_runtime_evidence(
                lambda evidence: evidence.update(captured_on="2026-07-30")
            )

    def test_runtime_evidence_boolean_schema_version_is_rejected(self) -> None:
        with self.assertRaisesRegex(verifier.CapabilityContractError, "planning_index_only"):
            self._validate_runtime_evidence(
                lambda evidence: evidence.update(schema_version=True)
            )

    def test_required_default_models_drive_family_acceptance(self) -> None:
        feature = next(
            item
            for item in self.manifest["features"]
            if item["id"] == "official-agent-models"
        )
        capabilities = [
            item
            for item in self.ledger["capabilities"]
            if item["feature_id"] == "official-agent-models"
        ]
        self.assertEqual(feature["acceptance_class"], "required_local")
        self.assertIn("required_local", {item["acceptance_class"] for item in capabilities})

    def test_source_claim_snapshot_drift_fails_closed(self) -> None:
        ledger = copy.deepcopy(self.ledger)
        ledger["capabilities"][0]["contract"]["unexpected"] = True
        with self.assertRaisesRegex(verifier.CapabilityContractError, "claim set drift"):
            verifier.validate(ledger, copy.deepcopy(self.manifest), copy.deepcopy(self.acceptance))

    def test_schema_violation_fails_closed(self) -> None:
        ledger = copy.deepcopy(self.ledger)
        ledger["unexpected"] = True
        with self.assertRaisesRegex(verifier.CapabilityContractError, "ledger schema violation"):
            verifier.validate(ledger, copy.deepcopy(self.manifest), copy.deepcopy(self.acceptance))

    def test_duplicate_json_keys_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            duplicate_json = Path(temporary_directory) / "duplicate.json"
            duplicate_json.write_text('{"schema_version": 1, "schema_version": 1}', encoding="utf-8")
            with self.assertRaisesRegex(verifier.CapabilityContractError, "duplicate JSON key"):
                verifier._load(duplicate_json)


if __name__ == "__main__":
    unittest.main()
