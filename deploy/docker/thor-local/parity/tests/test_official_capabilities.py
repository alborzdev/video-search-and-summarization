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
from unittest import mock


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
            digest = (
                reference_digest
                or hashlib.sha256(evidence_path.read_bytes()).hexdigest()
            )
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
        oracle["acceptance_readiness"] = {
            "classification": "executor_ready",
            "blockers": [],
        }
        oracle["fixture"]["materialization"] = {
            "path": "deploy/docker/thor-local/qualification/fixtures/oracle.json",
            "generator": "deploy/docker/thor-local/qualification/generate-oracle-fixture.py",
            "sha256": "1" * 64,
        }
        oracle["execution_bounds"]["executor"] = (
            "deploy/docker/thor-local/qualification/run-oracle.py"
        )
        oracle["execution_bounds"]["collectors"] = [
            "deploy/docker/thor-local/qualification/collect-oracle.py"
        ]
        oracle["cleanup"]["executor"] = (
            "deploy/docker/thor-local/qualification/cleanup-oracle.py"
        )
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

    def _mv3dt_aggregate_inputs(
        self,
    ) -> tuple[
        dict[str, object],
        dict[str, dict[str, object]],
        dict[str, dict[str, object]],
    ]:
        aggregate_path = (
            verifier.REPO_ROOT / "deploy/docker/thor-local/qualification/"
            "metadata-500-current-mv3dt-config-utils-successor/"
            "aggregate-runtime-receipt.json"
        )
        aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
        self.assertEqual(
            hashlib.sha256(aggregate_path.read_bytes()).hexdigest(),
            "7fb004dd62139c3d738e5c2b4bfcf7430ec0c1e3000efa664f4cfb12b1406cf2",
        )
        projected_oracles = json.loads(
            (
                verifier.REPO_ROOT / "deploy/docker/thor-local/qualification/"
                "metadata-500-current-mv3dt-config-utils-successor/"
                "post-state-capability-oracles.json"
            ).read_text(encoding="utf-8")
        )
        oracles_by_id = {
            row["capability_id"]: row for row in projected_oracles["oracles"]
        }
        capabilities_by_id = {
            row["id"]: copy.deepcopy(row) for row in self.ledger["capabilities"]
        }
        for capability_id in aggregate["promotion"]["eligible_capability_ids"]:
            capabilities_by_id[capability_id].update(
                copy.deepcopy(oracles_by_id[capability_id]["ledger_binding"])
            )
        return aggregate, capabilities_by_id, oracles_by_id

    def _mv3dt_root_projection(
        self,
    ) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
        root = (
            verifier.REPO_ROOT / "deploy/docker/thor-local/qualification/"
            "metadata-500-current-mv3dt-config-utils-successor"
        )
        ledger, manifest, oracles = tuple(
            json.loads((root / name).read_text(encoding="utf-8"))
            for name in (
                "post-state-root-official-capabilities.json",
                "post-state-root-manifest.json",
                "post-state-root-capability-oracles.json",
            )
        )
        # The projection exists to test the two historical MV3DT promotions.
        # Overlay the unrelated LVS row with its reviewed live contract because
        # the verifier intentionally checks operation manifests from this checkout.
        for key, identifier in (
            ("sources", "lvs-api-doc-3.2.1"),
            ("capabilities", "api.core.lvs-17"),
        ):
            projected = next(
                index
                for index, row in enumerate(ledger[key])
                if row["id"] == identifier
            )
            current = next(
                row for row in self.ledger[key] if row["id"] == identifier
            )
            ledger[key][projected] = copy.deepcopy(current)
        projected_oracle = next(
            index
            for index, row in enumerate(oracles["oracles"])
            if row["capability_id"] == "api.core.lvs-17"
        )
        current_oracle = next(
            row
            for row in self.oracles["oracles"]
            if row["capability_id"] == "api.core.lvs-17"
        )
        oracles["oracles"][projected_oracle] = copy.deepcopy(current_oracle)
        return ledger, manifest, oracles

    def _validate_mv3dt_aggregate(
        self,
        aggregate: dict[str, object],
        capabilities_by_id: dict[str, dict[str, object]],
        oracles_by_id: dict[str, dict[str, object]],
        *,
        capability_id: str = "tool.mv3dt.cam-info-generator",
        index: int = 0,
    ) -> None:
        reference = {
            "path": "deploy/docker/thor-local/qualification/"
            "metadata-500-current-mv3dt-config-utils-successor/"
            "aggregate-runtime-receipt.json",
            "sha256": "7fb004dd62139c3d738e5c2b4bfcf7430ec0c1e3000efa664f4cfb12b1406cf2",
            "capability_id": capability_id,
            "json_pointer": f"/capability_results/{index}",
        }
        verifier._validate_aggregate_runtime_evidence(
            aggregate,
            reference,
            capabilities_by_id[capability_id],
            capabilities_by_id,
            oracles_by_id,
            self.ledger["target"],
            verifier.REPO_ROOT,
        )

    @staticmethod
    def _recompute_outer_binding(aggregate: dict[str, object], index: int) -> None:
        row = aggregate["capability_results"][index]
        binding = row["runtime_evidence_binding"]
        payload = {
            key: value
            for key, value in row.items()
            if key not in {"official_receipt", "runtime_evidence_binding"}
        }
        binding.update(
            {
                "official_receipt_sha256": verifier._json_sha256(
                    row["official_receipt"]
                ),
                "bounded_capability_actions": row["bounded_capability_actions"],
                "target_case_actions": row["target_case_actions"],
                "supporting_cam_generation_actions": row[
                    "supporting_cam_generation_actions"
                ],
                "requests": row["requests"],
                "imported_helper_invocations": row["imported_helper_invocations"],
                "total_imported_source_function_invocations": row[
                    "total_imported_source_function_invocations"
                ],
                "run_output_sha256": row["run_output_sha256"],
                "positive_output_sha256": row["positive_observations"]["output_sha256"],
                "adjacent_negatives_sha256": verifier._json_sha256(
                    row["adjacent_negatives"]
                ),
                "capability_evidence_sha256": verifier._json_sha256(payload),
            }
        )

    def test_checked_in_contract_is_cross_linked(self) -> None:
        counts = verifier.validate(
            copy.deepcopy(self.ledger),
            copy.deepcopy(self.manifest),
            copy.deepcopy(self.acceptance),
        )
        self.assertEqual(counts["sources"], 126)
        self.assertEqual(counts["capabilities"], 289)
        self.assertEqual(counts["feature_families"], 42)
        self.assertEqual(counts["discrepancies"], 47)

    def test_injected_oracle_plan_is_schema_order_and_binding_checked(self) -> None:
        oracle_schema = json.loads(
            verifier.oracle_contract.SCHEMA.read_text(encoding="utf-8")
        )
        counts = verifier.validate(
            copy.deepcopy(self.ledger),
            copy.deepcopy(self.manifest),
            copy.deepcopy(self.acceptance),
            oracle_plan=copy.deepcopy(self.oracles),
            oracle_schema=oracle_schema,
        )
        self.assertEqual(counts["capabilities"], 289)

        swapped = copy.deepcopy(self.oracles)
        swapped["oracles"][0], swapped["oracles"][1] = (
            swapped["oracles"][1],
            swapped["oracles"][0],
        )
        with self.assertRaisesRegex(verifier.CapabilityContractError, "order differs"):
            verifier.validate(
                copy.deepcopy(self.ledger),
                copy.deepcopy(self.manifest),
                copy.deepcopy(self.acceptance),
                oracle_plan=swapped,
                oracle_schema=oracle_schema,
            )

        rebound = copy.deepcopy(self.oracles)
        rebound["oracles"][0]["ledger_binding"]["gap"] += " drift"
        with self.assertRaisesRegex(
            verifier.CapabilityContractError, "binding differs"
        ):
            verifier.validate(
                copy.deepcopy(self.ledger),
                copy.deepcopy(self.manifest),
                copy.deepcopy(self.acceptance),
                oracle_plan=rebound,
                oracle_schema=oracle_schema,
            )

    def test_injected_oracle_plan_requires_exact_schema(self) -> None:
        with self.assertRaisesRegex(
            verifier.CapabilityContractError, "requires its exact schema"
        ):
            verifier.validate(
                copy.deepcopy(self.ledger),
                copy.deepcopy(self.manifest),
                copy.deepcopy(self.acceptance),
                oracle_plan=copy.deepcopy(self.oracles),
            )

    def test_family_status_reducer_preserves_external_boundary(self) -> None:
        capabilities = [
            {
                "acceptance_class": "external_optional",
                "thor_state": "wired",
                "runtime_state": "not_applicable",
            },
            {
                "acceptance_class": "external_optional",
                "thor_state": "partial",
                "runtime_state": "not_applicable",
            },
        ]
        self.assertEqual(
            verifier._aggregate_family_status(capabilities),
            {
                "acceptance_class": "external_optional",
                "thor_state": "external_optional",
                "runtime_state": "not_applicable",
            },
        )
        capabilities[1]["thor_state"] = "wired"
        self.assertEqual(
            verifier._aggregate_family_status(capabilities)["thor_state"],
            "external_optional",
        )

    def test_family_status_reducer_retains_nonexternal_precedence(self) -> None:
        cases = [
            (
                [
                    {
                        "acceptance_class": "required_local",
                        "thor_state": "wired",
                        "runtime_state": "static_only",
                    },
                    {
                        "acceptance_class": "external_optional",
                        "thor_state": "external_optional",
                        "runtime_state": "not_applicable",
                    },
                ],
                {
                    "acceptance_class": "required_local",
                    "thor_state": "partial",
                    "runtime_state": "not_qualified",
                },
            ),
            (
                [
                    {
                        "acceptance_class": "alternate_local_lane",
                        "thor_state": "wired",
                        "runtime_state": "not_qualified",
                    },
                    {
                        "acceptance_class": "external_optional",
                        "thor_state": "wired",
                        "runtime_state": "not_qualified",
                    },
                ],
                {
                    "acceptance_class": "alternate_local_lane",
                    "thor_state": "wired",
                    "runtime_state": "not_qualified",
                },
            ),
            (
                [
                    {
                        "acceptance_class": "alternate_local_lane",
                        "thor_state": "partial",
                        "runtime_state": "blocked",
                    }
                ],
                {
                    "acceptance_class": "alternate_local_lane",
                    "thor_state": "partial",
                    "runtime_state": "blocked",
                },
            ),
        ]
        for capabilities, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(
                    verifier._aggregate_family_status(capabilities), expected
                )

    def test_family_status_reducer_rejects_empty_family(self) -> None:
        with self.assertRaisesRegex(
            verifier.CapabilityContractError, "empty capability family"
        ):
            verifier._aggregate_family_status([])

    def test_twelve_tooling_entries_have_exact_current_runtime_states(
        self,
    ) -> None:
        expected = {
            **{
                f"manifest-entry.spatial-ai-utils.{index:02d}-{suffix}": title
                for index, (suffix, title) in enumerate(
                    [
                        (
                            "calibration-and-camera-grouping",
                            "calibration and camera grouping",
                        ),
                        ("3d-2d-geometry", "3D/2D geometry"),
                        ("multiview-visualization", "multiview visualization"),
                        ("detection-map", "detection mAP"),
                        (
                            "tracking-hota-clear-identity-count",
                            "tracking HOTA/CLEAR/identity/count",
                        ),
                        ("nvschema-conversion", "NVSchema conversion"),
                        ("video-frame-tools", "video/frame tools"),
                        ("aws-gcs-validation", "AWS/GCS validation"),
                    ]
                )
            },
            **{
                f"manifest-entry.synthetic-data-tools.{index:02d}-{suffix}": title
                for index, (suffix, title) in enumerate(
                    [
                        ("semantic-label-helpers", "semantic label helpers"),
                        ("dataset-checks", "dataset checks"),
                        ("rgb-depth-video-conversion", "RGB/depth/video conversion"),
                        ("ground-truth-conversion", "ground-truth conversion"),
                    ]
                )
            },
        }
        capabilities = {
            item["id"]: item
            for item in self.ledger["capabilities"]
            if item["id"] in expected
        }
        synthetic_receipts = {
            "manifest-entry.synthetic-data-tools.00-semantic-label-helpers": (
                "00-semantic-label-helpers.json",
                "91afcd30bf85fdfe6cbc29ac0792707ee459912c900f2e2e6c6ade9dd66d9324",
            ),
            "manifest-entry.synthetic-data-tools.01-dataset-checks": (
                "01-dataset-checks.json",
                "dbf1a3a21ae063b4b4eeb19553482cf245e98cdcbb32b5c3221f46deb8cc5a20",
            ),
            "manifest-entry.synthetic-data-tools.02-rgb-depth-video-conversion": (
                "02-rgb-depth-video-conversion.json",
                "dac14785935ed85305b77d73cdd13f6ea953709bec8da83f07f272cd4d0e411b",
            ),
            "manifest-entry.synthetic-data-tools.03-ground-truth-conversion": (
                "03-ground-truth-conversion.json",
                "2611b2a01ac98e5c95a33980c3164811a1ded0c13e5ed0de94e0fa94e7141e7f",
            ),
        }
        self.assertEqual(set(capabilities), set(expected))
        for capability_id, title in expected.items():
            with self.subTest(capability_id=capability_id):
                capability = capabilities[capability_id]
                self.assertEqual(capability["title"], title)
                self.assertEqual(
                    capability["contract"]["warehouse_sample_bundle"], "excluded"
                )
                if capability_id in synthetic_receipts:
                    filename, digest = synthetic_receipts[capability_id]
                    self.assertEqual(capability["runtime_state"], "passed_current")
                    self.assertEqual(
                        capability["runtime_evidence"],
                        [
                            {
                                "path": (
                                    "deploy/docker/thor-local/qualification/"
                                    "metadata-500-current-synthetic-data-successor/"
                                    f"receipts/{filename}"
                                ),
                                "sha256": digest,
                            }
                        ],
                    )
                elif capability_id.endswith("aws-gcs-validation"):
                    self.assertNotIn("runtime_evidence", capability)
                    self.assertEqual(
                        capability["acceptance_class"], "external_optional"
                    )
                    self.assertEqual(capability["thor_state"], "external_optional")
                    self.assertEqual(capability["runtime_state"], "not_applicable")
                else:
                    self.assertEqual(
                        capability["acceptance_class"], "alternate_local_lane"
                    )
                    self.assertEqual(capability["thor_state"], "wired")
                    self.assertEqual(capability["runtime_state"], "passed_current")
                    index = int(capability_id.split(".")[2].split("-", 1)[0])
                    self.assertEqual(
                        capability["runtime_evidence"],
                        [
                            {
                                "path": (
                                    "deploy/docker/thor-local/qualification/"
                                    "metadata-500-current-spatial-ai-utils-successor/"
                                    "producer-runtime-receipt.json"
                                ),
                                "sha256": "9c0c9294b78bc5e01b8cc9500a70f050bb52d7b618399a13569b78064966d95a",
                                "capability_id": capability_id,
                                "json_pointer": f"/capability_results/{index}",
                            }
                        ],
                    )

    def test_cpu_multimedia_entry_is_exactly_wired_but_unqualified(self) -> None:
        capability = next(
            item
            for item in self.ledger["capabilities"]
            if item["id"] == verifier.CPU_MULTIMEDIA_CAPABILITY_ID
        )
        feature = next(
            item
            for item in self.manifest["features"]
            if item["id"] == "vios-codecs-audio"
        )
        self.assertEqual(
            feature["official_capability_ids"],
            [verifier.CPU_MULTIMEDIA_CAPABILITY_ID],
        )
        self.assertEqual(capability["kind"], "runtime_behavior")
        self.assertEqual(capability["thor_state"], "wired")
        self.assertEqual(capability["runtime_state"], "not_qualified")
        self.assertNotIn("runtime_evidence", capability)
        contract = capability["contract"]
        self.assertEqual(
            contract["selectors"],
            {
                "use_software_path": {
                    "json_pointer": "/data/use_software_path",
                    "checked_in_value": False,
                    "default": False,
                },
                "USE_SOFTWARE_PATH": {
                    "environment_override_for": "/data/use_software_path",
                    "accepted_values": ["true", "false"],
                },
                "use_software_encoder": {
                    "json_pointer": "/data/use_software_encoder",
                    "checked_in_key_present": False,
                    "default": False,
                },
            },
        )
        self.assertEqual(contract["branch_selection"]["decoder_gate"], "m_useNvV4l2Dec")
        self.assertEqual(contract["branch_selection"]["encoder_gate"], "m_useNvV4l2Enc")
        self.assertIs(
            contract["branch_selection"]["use_software_path_directly_selects_elements"],
            False,
        )
        self.assertEqual(
            contract["hardware_default_elements"],
            {
                "video_decoder": "nvv4l2decoder",
                "video_encoders": {
                    "h264": "nvv4l2h264enc",
                    "h265": "nvv4l2h265enc",
                },
            },
        )
        self.assertEqual(
            {item["path"]: item["sha256"] for item in contract["source_controls"]},
            verifier.CPU_MULTIMEDIA_SOURCE_CONTROLS,
        )

    def test_cpu_multimedia_selector_or_source_control_drift_fails_closed(self) -> None:
        for label, mutate in {
            "selector": lambda item: item["contract"]["selectors"][
                "use_software_path"
            ].update(default=True),
            "gate": lambda item: item["contract"]["branch_selection"].update(
                decoder_gate="use_software_path"
            ),
            "source": lambda item: item["contract"]["source_controls"][0].update(
                sha256="0" * 64
            ),
        }.items():
            with self.subTest(label=label):
                ledger = copy.deepcopy(self.ledger)
                capability = next(
                    item
                    for item in ledger["capabilities"]
                    if item["id"] == verifier.CPU_MULTIMEDIA_CAPABILITY_ID
                )
                mutate(capability)
                with self.assertRaises(verifier.CapabilityContractError):
                    verifier.validate(
                        ledger,
                        copy.deepcopy(self.manifest),
                        copy.deepcopy(self.acceptance),
                    )

    def test_executor_mismatch_semantic_resolutions_remain_exact(self) -> None:
        discrepancies = {
            item["id"]: item for item in self.ledger["source_discrepancies"]
        }
        proto = discrepancies[
            "systems.nvschema-incident-field-name-doc-repository-drift"
        ]
        warmup = discrepancies["thor.alert-warmup-default-override"]
        self.assertEqual(proto["record_semantics"], "single_source_record")
        self.assertEqual(proto["category"], "discrepancy")
        self.assertEqual(proto["source_ids"], ["doc.protobuf-schema"])
        self.assertIn("analyticsModule", proto["resolution"])
        self.assertIn("wire incompatibility", proto["must_not_claim"])
        self.assertEqual(warmup["record_semantics"], "single_source_record")
        self.assertEqual(warmup["category"], "scoped_default")
        self.assertEqual(warmup["source_ids"], ["doc.alerts"])
        self.assertIn("unqualified local override", warmup["resolution"])
        self.assertIn("service lacks warmup support", warmup["must_not_claim"])

    def test_executor_mismatch_resolution_cannot_be_weakened(self) -> None:
        ledger = copy.deepcopy(self.ledger)
        proto = next(
            item
            for item in ledger["source_discrepancies"]
            if item["id"] == "systems.nvschema-incident-field-name-doc-repository-drift"
        )
        proto["record_semantics"] = "cross_source_discrepancy"
        proto["candidate_observations"] = []
        with self.assertRaisesRegex(
            verifier.CapabilityContractError,
            "ledger schema violation|invalid discrepancy",
        ):
            verifier.validate(
                ledger,
                copy.deepcopy(self.manifest),
                copy.deepcopy(self.acceptance),
            )

    def test_single_source_discrepancy_retains_two_exact_sides(self) -> None:
        discrepancy = next(
            item
            for item in self.ledger["source_discrepancies"]
            if item["id"] == "rt-embed-scoped-model-defaults"
        )
        self.assertEqual(discrepancy["source_ids"], ["rt-embed-doc-3.2.1"])
        self.assertEqual(len(discrepancy["observations"]), 2)
        self.assertEqual(
            {item["locator"] for item in discrepancy["observations"]},
            {"Supported Models lines 197-202", "Supported Models lines 203-207"},
        )
        self.assertIn("Do not", discrepancy["must_not_claim"])

    def test_discrepancy_cannot_collapse_to_one_observation(self) -> None:
        ledger = copy.deepcopy(self.ledger)
        discrepancy = next(
            item
            for item in ledger["source_discrepancies"]
            if item["id"] == "warehouse-alert-vlm-model-prose-conflict"
        )
        discrepancy["observations"].pop()
        with self.assertRaisesRegex(
            verifier.CapabilityContractError,
            "observations.*too short|invalid discrepancy",
        ):
            verifier.validate(
                ledger,
                copy.deepcopy(self.manifest),
                copy.deepcopy(self.acceptance),
            )

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
        self.assertEqual(capability["contract"]["upstream_repository_tool_count"], 9)
        self.assertEqual(capability["contract"]["repository_tool_count"], 13)
        self.assertEqual(
            capability["contract"]["upstream_missing_tools"],
            ["add_file", "list_files", "get_file_info", "delete_file"],
        )
        self.assertEqual(
            capability["contract"]["thor_local_adapter_tools"],
            ["add_file", "list_files", "get_file_info", "delete_file"],
        )
        self.assertEqual(capability["thor_state"], "wired")
        self.assertEqual(capability["runtime_state"], "static_only")
        discrepancy = next(
            item
            for item in self.ledger["source_discrepancies"]
            if item["id"] == "lvs-mcp-doc-13-vs-repository-9"
        )
        self.assertIn("pinned upstream repository", discrepancy["resolution"])
        self.assertIn("passed a live file lifecycle", discrepancy["must_not_claim"])

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
        feature = next(
            item for item in manifest["features"] if item.get("official_capability_ids")
        )
        feature["official_capability_ids"].pop()
        with self.assertRaisesRegex(
            verifier.CapabilityContractError, "cross-link drift"
        ):
            verifier.validate(
                copy.deepcopy(self.ledger), manifest, copy.deepcopy(self.acceptance)
            )

    def test_missing_acceptance_scenario_fails_closed(self) -> None:
        acceptance = copy.deepcopy(self.acceptance)
        acceptance["scenarios"] = [
            item
            for item in acceptance["scenarios"]
            if item["id"] != "official-capability-contracts"
        ]
        with self.assertRaisesRegex(
            verifier.CapabilityContractError, "unknown acceptance scenario"
        ):
            verifier.validate(
                copy.deepcopy(self.ledger), copy.deepcopy(self.manifest), acceptance
            )

    def test_passed_current_without_evidence_is_rejected(self) -> None:
        ledger = copy.deepcopy(self.ledger)
        ledger["capabilities"][0]["runtime_state"] = "passed_current"
        with self.assertRaises(verifier.CapabilityContractError):
            verifier.validate(
                ledger, copy.deepcopy(self.manifest), copy.deepcopy(self.acceptance)
            )

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

    def test_mv3dt_aggregate_reference_selects_both_exact_capability_rows(
        self,
    ) -> None:
        aggregate, capabilities_by_id, oracles_by_id = self._mv3dt_aggregate_inputs()
        self._validate_mv3dt_aggregate(aggregate, capabilities_by_id, oracles_by_id)
        self._validate_mv3dt_aggregate(
            aggregate,
            capabilities_by_id,
            oracles_by_id,
            capability_id="tool.mv3dt.pub-sub-generator",
            index=1,
        )

    def test_mv3dt_aggregate_references_pass_full_canonical_projection(self) -> None:
        ledger, manifest, oracles = self._mv3dt_root_projection()
        counts = verifier.validate(
            ledger,
            manifest,
            copy.deepcopy(self.acceptance),
            oracles,
            json.loads(verifier.oracle_contract.SCHEMA.read_text(encoding="utf-8")),
            repo_root=verifier.REPO_ROOT,
        )
        self.assertEqual(counts["capabilities"], 289)
        mv3dt = [
            row
            for row in ledger["capabilities"]
            if row["id"]
            in {
                "tool.mv3dt.cam-info-generator",
                "tool.mv3dt.pub-sub-generator",
            }
        ]
        self.assertEqual(
            [row["runtime_evidence"][0]["json_pointer"] for row in mv3dt],
            ["/capability_results/0", "/capability_results/1"],
        )

    def test_mv3dt_aggregate_full_digest_is_checked_before_selection(self) -> None:
        ledger, manifest, oracles = self._mv3dt_root_projection()
        capability = next(
            row
            for row in ledger["capabilities"]
            if row["id"] == "tool.mv3dt.cam-info-generator"
        )
        capability["runtime_evidence"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(
            verifier.CapabilityContractError, "runtime evidence digest differs"
        ):
            verifier.validate(
                ledger,
                manifest,
                copy.deepcopy(self.acceptance),
                oracles,
                json.loads(verifier.oracle_contract.SCHEMA.read_text(encoding="utf-8")),
                repo_root=verifier.REPO_ROOT,
            )

    def test_mv3dt_aggregate_selector_cannot_cross_or_escape_rows(self) -> None:
        aggregate, capabilities_by_id, oracles_by_id = self._mv3dt_aggregate_inputs()
        with self.assertRaisesRegex(
            verifier.CapabilityContractError, "selector does not match"
        ):
            self._validate_mv3dt_aggregate(
                aggregate,
                capabilities_by_id,
                oracles_by_id,
                capability_id="tool.mv3dt.cam-info-generator",
                index=1,
            )
        reference = {
            "path": "deploy/docker/thor-local/evidence.json",
            "sha256": "0" * 64,
            "capability_id": "tool.mv3dt.cam-info-generator",
            "json_pointer": "/capability_results/00",
        }
        with self.assertRaisesRegex(
            verifier.CapabilityContractError, "exact capability-results JSON pointer"
        ):
            verifier._select_aggregate_capability(aggregate, reference)

    def test_mv3dt_aggregate_deep_shape_promotion_and_provenance_fail_closed(
        self,
    ) -> None:
        cases = {
            "top-level injection": lambda value: value.update(extra=True),
            "dirty checkout": lambda value: value["bindings"].update(
                checkout_clean=False
            ),
            "non-empty checkout": lambda value: value["bindings"].update(
                checkout_status_porcelain_sha256="0" * 64
            ),
            "development receipt": lambda value: value["promotion"].update(
                development_smoke_only=True
            ),
            "non-promotable receipt": lambda value: value["promotion"].update(
                aggregate_is_promotable=False
            ),
            "family mismatch": lambda value: value["promotion"].update(
                family_id="other"
            ),
            "captured tree drift": lambda value: value["bindings"].update(
                checkout_tree="0" * 40
            ),
            "executor blob drift": lambda value: value["bindings"].update(
                executor_sha256="0" * 64
            ),
            "oracle blob drift": lambda value: value["bindings"].update(
                execution_oracle_document_sha256="0" * 64
            ),
            "row injection": lambda value: value["capability_results"][0].update(
                extra=True
            ),
            "outer binding drift": lambda value: value["capability_results"][0][
                "runtime_evidence_binding"
            ].update(capability_evidence_sha256="0" * 64),
        }
        for label, mutate in cases.items():
            with self.subTest(label=label):
                aggregate, capabilities_by_id, oracles_by_id = (
                    self._mv3dt_aggregate_inputs()
                )
                mutate(aggregate)
                with self.assertRaises(verifier.CapabilityContractError):
                    self._validate_mv3dt_aggregate(
                        aggregate, capabilities_by_id, oracles_by_id
                    )

    def test_mv3dt_fabricated_nested_receipts_fail_even_with_recomputed_wrapper(
        self,
    ) -> None:
        mutations = {
            "shallow-only official receipt": lambda row: row.update(
                official_receipt={}
            ),
            "nested result drift": lambda row: row["official_receipt"].update(
                result="passed_prior"
            ),
            "nested assertion drift": lambda row: row["official_receipt"]["assertions"][
                0
            ].update(observed="fabricated"),
            "bounded action drift": lambda row: row.update(
                bounded_capability_actions=6
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                aggregate, capabilities_by_id, oracles_by_id = (
                    self._mv3dt_aggregate_inputs()
                )
                mutate(aggregate["capability_results"][0])
                self._recompute_outer_binding(aggregate, 0)
                with self.assertRaises(verifier.CapabilityContractError):
                    self._validate_mv3dt_aggregate(
                        aggregate, capabilities_by_id, oracles_by_id
                    )

    def test_mv3dt_aggregate_source_controls_are_historical_blobs(self) -> None:
        aggregate, capabilities_by_id, oracles_by_id = self._mv3dt_aggregate_inputs()
        original = verifier._git_blob

        def tamper_source(repo_root: Path, commit: str, path: str) -> bytes:
            if path == "tools/rtvi-cv-mv3dt-utils/requirements.txt":
                return b"fabricated\n"
            return original(repo_root, commit, path)

        with mock.patch.object(verifier, "_git_blob", side_effect=tamper_source):
            with self.assertRaisesRegex(
                verifier.CapabilityContractError, "source-control blob"
            ):
                self._validate_mv3dt_aggregate(
                    aggregate, capabilities_by_id, oracles_by_id
                )

    def test_executor_evidence_oracle_hash_fixture_assertions_and_cleanup_fail_closed(
        self,
    ) -> None:
        mutations = {
            "oracle hash": lambda evidence: evidence.update(oracle_sha256="0" * 64),
            "fixture digest": lambda evidence: evidence["fixture"].update(
                sha256="0" * 64
            ),
            "missing assertion": lambda evidence: evidence["assertions"].pop(),
            "changed expected value": lambda evidence: evidence["assertions"][0].update(
                expected="generic-pass"
            ),
            "wrong observed value": lambda evidence: evidence["assertions"][0].update(
                observed="generic-pass"
            ),
            "missing observation": lambda evidence: evidence["observations"].pop(),
            "cleanup failure": lambda evidence: evidence["cleanup"].update(
                result="fail"
            ),
            "wrong release commit": lambda evidence: evidence["target"].update(
                ga_commit="0" * 40
            ),
            "wrong oracle scenario": lambda evidence: evidence.update(
                scenario_ids=self.ledger["capabilities"][0]["scenario_ids"]
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                capability, oracle, evidence = self._executor_ready_binding()
                mutate(evidence)
                with self.assertRaises(verifier.CapabilityContractError):
                    verifier._validate_bound_runtime_evidence(
                        capability, oracle, evidence, self.ledger["target"]
                    )

    def test_protocol_executor_evidence_binds_case_hashes_vectors_sources_and_cleanup(
        self,
    ) -> None:
        capability_id = "protocol.agent.websocket"
        capability, oracle, evidence = self._executor_ready_binding(capability_id)
        verifier._validate_bound_runtime_evidence(
            capability, oracle, evidence, self.ledger["target"]
        )
        mutations = {
            "case id": lambda item: item["protocol_case"].update(case_id="wrong-case"),
            "whole file hash": lambda item: item["protocol_case"].update(
                file_sha256="0" * 64
            ),
            "set hash": lambda item: item["protocol_case"].update(
                contract_set_sha256="0" * 64
            ),
            "case hash": lambda item: item["protocol_case"].update(
                case_sha256="0" * 64
            ),
            "positive vector": lambda item: item["protocol_case"].update(
                positive_vector_id="wrong-vector"
            ),
            "negative vectors": lambda item: item["protocol_case"].update(
                negative_vector_ids=["wrong-vector"]
            ),
            "source hashes": lambda item: item["protocol_case"]["source_hashes"][
                0
            ].update(content_sha256="0" * 64),
            "cleanup result": lambda item: item["protocol_case"].update(
                cleanup_result="fail"
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                capability, oracle, evidence = self._executor_ready_binding(
                    capability_id
                )
                mutate(evidence)
                with self.assertRaisesRegex(
                    verifier.CapabilityContractError, "protocol case evidence"
                ):
                    verifier._validate_bound_runtime_evidence(
                        capability, oracle, evidence, self.ledger["target"]
                    )

    def test_runtime_evidence_path_traversal_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            verifier.CapabilityContractError, "unsafe runtime evidence path"
        ):
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
            with self.assertRaisesRegex(
                verifier.CapabilityContractError, "contains a symlink"
            ):
                verifier.validate(
                    ledger,
                    copy.deepcopy(self.manifest),
                    copy.deepcopy(self.acceptance),
                    repo_root=root,
                )

    def test_runtime_evidence_wrong_capability_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            verifier.CapabilityContractError, "planning_index_only"
        ):
            self._validate_runtime_evidence(
                lambda evidence: evidence.update(capability_id="different.capability")
            )

    def test_runtime_evidence_wrong_scenario_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            verifier.CapabilityContractError, "planning_index_only"
        ):
            self._validate_runtime_evidence(
                lambda evidence: evidence.update(scenario_ids=["different-scenario"])
            )

    def test_runtime_evidence_malformed_scenarios_are_rejected(self) -> None:
        with self.assertRaisesRegex(
            verifier.CapabilityContractError, "planning_index_only"
        ):
            self._validate_runtime_evidence(
                lambda evidence: evidence.update(
                    scenario_ids="official-capability-contracts"
                )
            )

    def test_runtime_evidence_wrong_commit_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            verifier.CapabilityContractError, "planning_index_only"
        ):
            self._validate_runtime_evidence(
                lambda evidence: evidence.update(target_commit="0" * 40)
            )

    def test_runtime_evidence_duplicate_json_keys_are_rejected(self) -> None:
        duplicate = (
            '{"schema_version":1,"capability_id":"duplicate","capability_id":"duplicate",'
            '"result":"passed_current","target_commit":"duplicate","captured_on":"2026-07-31",'
            '"scenario_ids":["duplicate"],"checks":[{"id":"duplicate","result":"pass"}]}'
        )
        with self.assertRaisesRegex(
            verifier.CapabilityContractError, "duplicate JSON key"
        ):
            self._validate_runtime_evidence(raw_evidence=duplicate)

    def test_runtime_evidence_failed_check_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            verifier.CapabilityContractError, "planning_index_only"
        ):
            self._validate_runtime_evidence(
                lambda evidence: evidence.update(
                    checks=[{"id": "semantic-oracle", "result": "fail"}]
                )
            )

    def test_runtime_evidence_check_without_id_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            verifier.CapabilityContractError, "planning_index_only"
        ):
            self._validate_runtime_evidence(
                lambda evidence: evidence.update(checks=[{"result": "pass"}])
            )

    def test_runtime_evidence_stale_hash_is_rejected(self) -> None:
        with self.assertRaisesRegex(verifier.CapabilityContractError, "digest differs"):
            self._validate_runtime_evidence(reference_digest="0" * 64)

    def test_runtime_evidence_stale_date_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            verifier.CapabilityContractError, "planning_index_only"
        ):
            self._validate_runtime_evidence(
                lambda evidence: evidence.update(captured_on="2026-07-30")
            )

    def test_runtime_evidence_boolean_schema_version_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            verifier.CapabilityContractError, "planning_index_only"
        ):
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
        self.assertIn(
            "required_local", {item["acceptance_class"] for item in capabilities}
        )

    def test_source_claim_snapshot_drift_fails_closed(self) -> None:
        ledger = copy.deepcopy(self.ledger)
        ledger["capabilities"][0]["contract"]["unexpected"] = True
        with self.assertRaisesRegex(
            verifier.CapabilityContractError, "claim set drift"
        ):
            verifier.validate(
                ledger, copy.deepcopy(self.manifest), copy.deepcopy(self.acceptance)
            )

    def test_schema_violation_fails_closed(self) -> None:
        ledger = copy.deepcopy(self.ledger)
        ledger["unexpected"] = True
        with self.assertRaisesRegex(
            verifier.CapabilityContractError, "ledger schema violation"
        ):
            verifier.validate(
                ledger, copy.deepcopy(self.manifest), copy.deepcopy(self.acceptance)
            )

    def test_duplicate_json_keys_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            duplicate_json = Path(temporary_directory) / "duplicate.json"
            duplicate_json.write_text(
                '{"schema_version": 1, "schema_version": 1}', encoding="utf-8"
            )
            with self.assertRaisesRegex(
                verifier.CapabilityContractError, "duplicate JSON key"
            ):
                verifier._load(duplicate_json)


if __name__ == "__main__":
    unittest.main()
