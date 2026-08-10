# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PARITY_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PARITY_DIR))

import capability_oracles as verifier  # noqa: E402


class CapabilityOracleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = json.loads(verifier.ORACLES.read_text(encoding="utf-8"))
        cls.ledger = json.loads(verifier.LEDGER.read_text(encoding="utf-8"))
        cls.protocol_cases = json.loads(
            verifier.PROTOCOL_CASES.read_text(encoding="utf-8")
        )

    def _copy_offline_mv3dt_inputs(self, root: Path) -> list[str]:
        contract = json.loads(
            (
                verifier.REPO_ROOT / verifier.OFFLINE_MV3DT_FILES["contract"]["path"]
            ).read_text(encoding="utf-8")
        )
        paths = {lock["path"] for lock in verifier.OFFLINE_MV3DT_FILES.values()} | {
            lock["path"] for lock in contract["source_locks"]
        }
        for relative in paths:
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(verifier.REPO_ROOT / relative, destination)
        return [lock["path"] for lock in contract["source_locks"]]

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
        executor_ready = (
            len(verifier.SYNTHETIC_RUNTIME_FIXTURES)
            + len(verifier.MV3DT_RUNTIME_FIXTURES)
            + len(verifier.SPATIAL_AI_IDS[:7])
            + 1  # current VIOS byte-identical full-file runtime receipt
            + 1  # current NvStreamer file/RTSP/WebRTC runtime receipt
            + 1  # current NvStreamer synchronized-playback runtime receipt
            + 1  # current NvStreamer complete-configuration runtime receipt
            + 1  # current VIOS native WebRTC replay runtime receipt
            + 1  # current VIOS native WebRTC live runtime receipt
            + 2  # current Video Analytics query and optional-Kafka receipts
            + 2  # current Kafka NvSchema and Redis event transport receipts
            + 1  # current Alert Bridge WebSocket runtime receipt
            + 6  # current RT-VLM model, SSE, limits, and endpoint receipt
            + 1  # current LVS five-format local summarization receipt
            + 1  # current LVS one-video-at-a-time runtime receipt
            + 1  # current LVS custom-model and custom-prompt runtime receipt
            + 2  # exact official Thor Nemotron and Cosmos3 model runtime receipt
        )
        self.assertEqual(
            counts["planning_index_only"], capability_count - executor_ready
        )
        self.assertEqual(counts["executor_ready"], executor_ready)
        self.assertEqual(counts["planning_executor_bindings"], 27)
        self.assertEqual(counts["offline_tool_observation_bindings"], 2)
        self.assertEqual(counts["static_subset_oracle_bindings"], 29)
        self.assertGreater(counts["profiles"], 0)

    def test_checked_in_plan_is_byte_exact_canonical_compiler_output(self) -> None:
        acceptance = json.loads(verifier.ACCEPTANCE.read_text(encoding="utf-8"))
        compiled = verifier.compile_plan(
            copy.deepcopy(self.ledger), acceptance_document=acceptance
        )
        rendered = (
            json.dumps(
                compiled,
                indent=2,
                ensure_ascii=True,
                sort_keys=True,
            )
            + "\n"
        )
        self.assertEqual(verifier.ORACLES.read_text(encoding="utf-8"), rendered)

    def test_vios_webrtc_replay_is_exact_executor_ready_row(self) -> None:
        oracle = next(
            item
            for item in self.plan["oracles"]
            if item["capability_id"] == verifier.VIOS_WEBRTC_REPLAY_CAPABILITY_ID
        )
        self.assertEqual(
            oracle["fixture"]["materialization"],
            {
                "path": verifier.VIOS_WEBRTC_REPLAY_FIXTURE["path"],
                "generator": verifier.VIOS_WEBRTC_REPLAY_EXECUTOR,
                "sha256": verifier.VIOS_WEBRTC_REPLAY_FIXTURE["sha256"],
            },
        )
        self.assertEqual(
            oracle["execution_bounds"]["workload"],
            verifier.VIOS_WEBRTC_REPLAY_WORKLOAD,
        )
        self.assertEqual(
            oracle["execution_bounds"]["max_actions"],
            verifier.VIOS_WEBRTC_REPLAY_MAX_ACTIONS,
        )
        self.assertEqual(
            oracle["execution_bounds"]["executor"],
            verifier.VIOS_WEBRTC_REPLAY_EXECUTOR,
        )
        self.assertEqual(
            oracle["cleanup"]["targets"], [verifier.VIOS_WEBRTC_REPLAY_NAMESPACE]
        )
        self.assertEqual(
            oracle["acceptance_readiness"],
            {"classification": "executor_ready", "blockers": []},
        )
        self.assertEqual(
            oracle["protocol_case_binding"]["negative_vector_ids"],
            ["vios-replay-bad-seek-action"],
        )
        self.assertEqual(oracle["evidence"], [])

    def test_vios_webrtc_live_is_exact_executor_ready_row(self) -> None:
        oracle = next(
            item
            for item in self.plan["oracles"]
            if item["capability_id"] == verifier.VIOS_WEBRTC_LIVE_CAPABILITY_ID
        )
        self.assertEqual(
            oracle["fixture"]["materialization"],
            {
                "path": verifier.VIOS_WEBRTC_LIVE_FIXTURE["path"],
                "generator": verifier.VIOS_WEBRTC_LIVE_EXECUTOR,
                "sha256": verifier.VIOS_WEBRTC_LIVE_FIXTURE["sha256"],
            },
        )
        self.assertEqual(
            oracle["execution_bounds"]["workload"],
            verifier.VIOS_WEBRTC_LIVE_WORKLOAD,
        )
        self.assertEqual(
            oracle["execution_bounds"]["max_actions"],
            verifier.VIOS_WEBRTC_LIVE_MAX_ACTIONS,
        )
        self.assertEqual(
            oracle["execution_bounds"]["executor"],
            verifier.VIOS_WEBRTC_LIVE_EXECUTOR,
        )
        self.assertEqual(
            oracle["cleanup"]["targets"], verifier.VIOS_WEBRTC_LIVE_NAMESPACES
        )
        self.assertEqual(
            oracle["acceptance_readiness"],
            {"classification": "executor_ready", "blockers": []},
        )
        self.assertEqual(
            oracle["protocol_case_binding"]["negative_vector_ids"],
            ["vios-live-missing-peer"],
        )
        self.assertEqual(oracle["evidence"], [])

    def test_video_analytics_runtime_oracles_are_exact_executor_ready_rows(
        self,
    ) -> None:
        by_id = {item["capability_id"]: item for item in self.plan["oracles"]}
        for capability_id in verifier.VIDEO_ANALYTICS_RUNTIME_CAPABILITY_IDS:
            oracle = by_id[capability_id]
            self.assertEqual(
                oracle["fixture"]["materialization"],
                {
                    "path": verifier.VIDEO_ANALYTICS_RUNTIME_FIXTURE["path"],
                    "generator": verifier.VIDEO_ANALYTICS_RUNTIME_EXECUTOR,
                    "sha256": verifier.VIDEO_ANALYTICS_RUNTIME_FIXTURE["sha256"],
                },
            )
            self.assertEqual(
                oracle["execution_bounds"]["workload"],
                verifier.VIDEO_ANALYTICS_RUNTIME_WORKLOAD,
            )
            self.assertEqual(
                oracle["execution_bounds"]["max_actions"],
                verifier.VIDEO_ANALYTICS_RUNTIME_MAX_ACTIONS,
            )
            self.assertEqual(
                oracle["execution_bounds"]["executor"],
                verifier.VIDEO_ANALYTICS_RUNTIME_EXECUTOR,
            )
            self.assertEqual(
                oracle["cleanup"]["targets"],
                [verifier.VIDEO_ANALYTICS_RUNTIME_NAMESPACE],
            )
            self.assertEqual(
                oracle["acceptance_readiness"],
                {"classification": "executor_ready", "blockers": []},
            )
            self.assertEqual(oracle["evidence"], [])

    def test_event_transport_oracles_are_exact_executor_ready_rows(self) -> None:
        by_id = {item["capability_id"]: item for item in self.plan["oracles"]}
        for capability_id in verifier.EVENT_TRANSPORT_RUNTIME_CAPABILITY_IDS:
            oracle = by_id[capability_id]
            self.assertEqual(
                oracle["fixture"]["materialization"],
                {
                    "path": verifier.EVENT_TRANSPORT_RUNTIME_FIXTURE["path"],
                    "generator": verifier.EVENT_TRANSPORT_RUNTIME_EXECUTOR,
                    "sha256": verifier.EVENT_TRANSPORT_RUNTIME_FIXTURE["sha256"],
                },
            )
            self.assertEqual(
                oracle["execution_bounds"]["workload"],
                verifier.EVENT_TRANSPORT_RUNTIME_WORKLOAD,
            )
            self.assertEqual(
                oracle["execution_bounds"]["max_actions"],
                verifier.EVENT_TRANSPORT_RUNTIME_MAX_ACTIONS,
            )
            self.assertEqual(
                oracle["execution_bounds"]["executor"],
                verifier.EVENT_TRANSPORT_RUNTIME_EXECUTOR,
            )
            self.assertEqual(
                oracle["cleanup"]["targets"],
                verifier.EVENT_TRANSPORT_RUNTIME_NAMESPACES[capability_id],
            )
            self.assertEqual(
                oracle["acceptance_readiness"],
                {"classification": "executor_ready", "blockers": []},
            )
            self.assertEqual(oracle["evidence"], [])

    def test_alert_websocket_oracle_is_exact_executor_ready_row(self) -> None:
        oracle = next(
            item
            for item in self.plan["oracles"]
            if item["capability_id"]
            == verifier.ALERT_WEBSOCKET_RUNTIME_CAPABILITY_ID
        )
        self.assertEqual(
            oracle["fixture"]["materialization"],
            {
                "path": verifier.ALERT_WEBSOCKET_RUNTIME_FIXTURE["path"],
                "generator": verifier.ALERT_WEBSOCKET_RUNTIME_EXECUTOR,
                "sha256": verifier.ALERT_WEBSOCKET_RUNTIME_FIXTURE["sha256"],
            },
        )
        self.assertEqual(
            oracle["execution_bounds"]["workload"],
            verifier.ALERT_WEBSOCKET_RUNTIME_WORKLOAD,
        )
        self.assertEqual(
            oracle["execution_bounds"]["max_actions"],
            verifier.ALERT_WEBSOCKET_RUNTIME_MAX_ACTIONS,
        )
        self.assertEqual(
            oracle["execution_bounds"]["executor"],
            verifier.ALERT_WEBSOCKET_RUNTIME_EXECUTOR,
        )
        self.assertEqual(
            oracle["cleanup"]["targets"],
            verifier.ALERT_WEBSOCKET_RUNTIME_NAMESPACES,
        )
        self.assertEqual(
            oracle["acceptance_readiness"],
            {"classification": "executor_ready", "blockers": []},
        )
        self.assertEqual(
            oracle["protocol_case_binding"]["negative_vector_ids"],
            ["alert-ws-non-json"],
        )
        self.assertEqual(oracle["evidence"], [])

    def test_rt_vlm_sse_runtime_oracles_are_exact_executor_ready_rows(self) -> None:
        by_id = {item["capability_id"]: item for item in self.plan["oracles"]}
        for capability_id in verifier.RT_VLM_SSE_RUNTIME_CAPABILITY_IDS:
            oracle = by_id[capability_id]
            self.assertEqual(
                oracle["fixture"]["materialization"],
                {
                    "path": verifier.RT_VLM_SSE_RUNTIME_FIXTURE["path"],
                    "generator": verifier.RT_VLM_SSE_RUNTIME_EXECUTOR,
                    "sha256": verifier.RT_VLM_SSE_RUNTIME_FIXTURE["sha256"],
                },
            )
            self.assertEqual(
                oracle["execution_bounds"]["workload"],
                verifier.RT_VLM_SSE_RUNTIME_WORKLOAD,
            )
            self.assertEqual(
                oracle["execution_bounds"]["max_actions"],
                verifier.RT_VLM_SSE_RUNTIME_MAX_ACTIONS,
            )
            self.assertEqual(
                oracle["execution_bounds"]["executor"],
                verifier.RT_VLM_SSE_RUNTIME_EXECUTOR,
            )
            self.assertEqual(
                oracle["cleanup"]["targets"],
                verifier.RT_VLM_SSE_RUNTIME_NAMESPACES,
            )
            self.assertEqual(
                oracle["acceptance_readiness"],
                {"classification": "executor_ready", "blockers": []},
            )
            self.assertEqual(oracle["evidence"], [])
        self.assertEqual(
            by_id["protocol.rt-vlm.sse"]["protocol_case_binding"][
                "negative_vector_ids"
            ],
            ["rt-vlm-sse-blank-prompt"],
        )

    def test_lvs_formats_runtime_oracle_is_exact_executor_ready_row(self) -> None:
        oracle = next(
            item
            for item in self.plan["oracles"]
            if item["capability_id"] == verifier.LVS_FORMATS_RUNTIME_CAPABILITY_ID
        )
        self.assertEqual(
            oracle["fixture"]["materialization"],
            {
                "path": verifier.LVS_FORMATS_RUNTIME_FIXTURE["path"],
                "generator": verifier.LVS_FORMATS_RUNTIME_EXECUTOR,
                "sha256": verifier.LVS_FORMATS_RUNTIME_FIXTURE["sha256"],
            },
        )
        self.assertEqual(
            oracle["execution_bounds"]["workload"],
            verifier.LVS_FORMATS_RUNTIME_WORKLOAD,
        )
        self.assertEqual(
            oracle["execution_bounds"]["max_actions"],
            verifier.LVS_FORMATS_RUNTIME_MAX_ACTIONS,
        )
        self.assertEqual(
            oracle["execution_bounds"]["executor"],
            verifier.LVS_FORMATS_RUNTIME_EXECUTOR,
        )
        self.assertEqual(
            oracle["cleanup"]["targets"],
            verifier.LVS_FORMATS_RUNTIME_NAMESPACES,
        )
        self.assertEqual(
            oracle["acceptance_readiness"],
            {"classification": "executor_ready", "blockers": []},
        )
        self.assertEqual(oracle["evidence"], [])

    def test_synthetic_data_oracles_are_exact_executor_ready_rows(self) -> None:
        by_id = {item["capability_id"]: item for item in self.plan["oracles"]}
        self.assertEqual(
            set(verifier.SYNTHETIC_RUNTIME_FIXTURES),
            {
                f"manifest-entry.synthetic-data-tools.{index:02d}-{suffix}"
                for index, suffix in enumerate(
                    (
                        "semantic-label-helpers",
                        "dataset-checks",
                        "rgb-depth-video-conversion",
                        "ground-truth-conversion",
                    )
                )
            },
        )
        for capability_id, (
            fixture_path,
            fixture_sha256,
        ) in verifier.SYNTHETIC_RUNTIME_FIXTURES.items():
            oracle = by_id[capability_id]
            self.assertEqual(
                oracle["fixture"]["materialization"],
                {
                    "path": fixture_path,
                    "generator": verifier.SYNTHETIC_RUNTIME_EXECUTOR,
                    "sha256": fixture_sha256,
                },
            )
            self.assertEqual(
                oracle["acceptance_readiness"],
                {"classification": "executor_ready", "blockers": []},
            )
            self.assertEqual(
                oracle["execution_bounds"]["executor"],
                verifier.SYNTHETIC_RUNTIME_EXECUTOR,
            )
            self.assertEqual(
                oracle["cleanup"]["executor"],
                verifier.SYNTHETIC_RUNTIME_EXECUTOR,
            )
            self.assertEqual(oracle["current_state"], "open_unexecuted")
            self.assertEqual(oracle["evidence"], [])

    def test_promoted_mv3dt_ledger_reproduces_exact_promoted_oracles(self) -> None:
        root = (
            verifier.REPO_ROOT / "deploy/docker/thor-local/qualification/"
            "metadata-500-current-mv3dt-config-utils-successor"
        )
        ledger = json.loads(
            (root / "post-state-root-official-capabilities.json").read_text(
                encoding="utf-8"
            )
        )
        acceptance = json.loads(verifier.ACCEPTANCE.read_text(encoding="utf-8"))
        compiled = verifier.compile_plan(ledger, acceptance_document=acceptance)
        historical_oracles = json.loads(
            (
                verifier.REPO_ROOT
                / "deploy/docker/thor-local/qualification/metadata-500-current-spatial-ai-utils-core-rebind-successor/post-state-capability-oracles.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(compiled["oracles"], historical_oracles["oracles"][:289])
        counts = verifier.validate(compiled, ledger)
        self.assertEqual(counts["executor_ready"], 9)
        by_id = {row["capability_id"]: row for row in compiled["oracles"]}
        for capability_id, fixture in verifier.MV3DT_RUNTIME_FIXTURES.items():
            oracle = by_id[capability_id]
            self.assertEqual(
                oracle["fixture"]["materialization"],
                {
                    "path": fixture["path"],
                    "generator": verifier.MV3DT_RUNTIME_EXECUTOR["path"],
                    "sha256": fixture["raw_sha256"],
                },
            )
            self.assertEqual(
                oracle["execution_bounds"]["workload"],
                verifier.MV3DT_RUNTIME_WORKLOAD,
            )
            self.assertEqual(
                (
                    oracle["execution_bounds"]["max_actions"],
                    oracle["execution_bounds"]["max_requests"],
                ),
                (fixture["max_actions"], fixture["max_requests"]),
            )
            self.assertEqual(oracle["cleanup"]["targets"], [fixture["namespace"]])
            self.assertEqual(
                oracle["acceptance_readiness"],
                {"classification": "executor_ready", "blockers": []},
            )
            self.assertEqual(oracle["evidence"], [])
            self.assertEqual(
                oracle["ledger_binding"]["contract"]["wave3_acceptance"][
                    "materialized"
                ],
                False,
            )
            self.assertEqual(
                oracle["ledger_binding"]["contract"]["wave3_acceptance"][
                    "executor_ready"
                ],
                False,
            )
            self.assertTrue(oracle["offline_tool_observation_bindings"])

    def test_mv3dt_runtime_locks_and_counts_fail_closed(self) -> None:
        root = (
            verifier.REPO_ROOT / "deploy/docker/thor-local/qualification/"
            "metadata-500-current-mv3dt-config-utils-successor"
        )
        ledger = json.loads(
            (root / "post-state-root-official-capabilities.json").read_text(
                encoding="utf-8"
            )
        )
        acceptance = json.loads(verifier.ACCEPTANCE.read_text(encoding="utf-8"))
        executor_lock = copy.deepcopy(verifier.MV3DT_RUNTIME_EXECUTOR)
        executor_lock["raw_sha256"] = "0" * 64
        with mock.patch.object(verifier, "MV3DT_RUNTIME_EXECUTOR", executor_lock):
            with self.assertRaisesRegex(
                verifier.OracleContractError, "runtime file lock drift"
            ):
                verifier.compile_plan(ledger, acceptance_document=acceptance)

        fixtures = copy.deepcopy(verifier.MV3DT_RUNTIME_FIXTURES)
        fixtures["tool.mv3dt.pub-sub-generator"]["max_actions"] = 7
        with mock.patch.object(verifier, "MV3DT_RUNTIME_FIXTURES", fixtures):
            with self.assertRaisesRegex(
                verifier.OracleContractError,
                "action/request/cleanup drift",
            ):
                verifier.compile_plan(ledger, acceptance_document=acceptance)

        workload = copy.deepcopy(verifier.MV3DT_RUNTIME_WORKLOAD)
        workload["calculated_max_requests"] = 10
        with mock.patch.object(verifier, "MV3DT_RUNTIME_WORKLOAD", workload):
            with self.assertRaisesRegex(
                verifier.OracleContractError, "runtime workload drift"
            ):
                verifier.compile_plan(ledger, acceptance_document=acceptance)

    def test_spatial_ai_core_oracles_are_exact_locked_projection(self) -> None:
        projection_root = (
            verifier.REPO_ROOT / "deploy/docker/thor-local/qualification/"
            "metadata-500-current-spatial-ai-utils-core-rebind-successor"
        )
        predecessor_root = (
            verifier.REPO_ROOT / "deploy/docker/thor-local/qualification/"
            "metadata-500-current-mv3dt-config-utils-successor"
        )
        projected = json.loads(
            (projection_root / "post-state-capability-oracles.json").read_text(
                encoding="utf-8"
            )
        )
        predecessor = json.loads(
            (predecessor_root / "post-state-root-capability-oracles.json").read_text(
                encoding="utf-8"
            )
        )
        before = {row["capability_id"]: row for row in predecessor["oracles"]}
        after = {row["capability_id"]: row for row in projected["oracles"][:289]}
        changed = {
            capability_id
            for capability_id in before
            if before[capability_id] != after[capability_id]
        }
        self.assertEqual(changed, set(verifier.SPATIAL_AI_CORE_IDS))
        for capability_id in verifier.SPATIAL_AI_CORE_IDS:
            oracle = after[capability_id]
            self.assertEqual(
                oracle["acceptance_readiness"],
                {"classification": "executor_ready", "blockers": []},
            )
            self.assertEqual(oracle["current_state"], "open_unexecuted")
            self.assertEqual(oracle["evidence"], [])
            self.assertEqual(oracle["execution_bounds"]["max_actions"], 7)
            self.assertEqual(oracle["execution_bounds"]["max_requests"], 7)
            self.assertEqual(
                oracle["execution_bounds"]["warehouse_sample_bundle"], "excluded"
            )
            self.assertEqual(
                oracle["ledger_binding"]["runtime_state"], "passed_current"
            )
            self.assertEqual(
                oracle["ledger_binding"]["gap"], verifier.SPATIAL_AI_CORE_GAP
            )

        entry07 = verifier.SPATIAL_AI_IDS[7]
        self.assertEqual(before[entry07], after[entry07])
        projected_ledger = json.loads(
            (projection_root / "post-state-official-capabilities.json").read_text(
                encoding="utf-8"
            )
        )
        ledger_by_id = {
            row["id"]: row for row in projected_ledger["capabilities"][:289]
        }
        predecessor_ledger = json.loads(
            (predecessor_root / "post-state-root-official-capabilities.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            projected_ledger["capabilities"][:289], predecessor_ledger["capabilities"]
        )
        for capability_id in verifier.SPATIAL_AI_IDS[:7]:
            self.assertEqual(
                ledger_by_id[capability_id]["runtime_state"], "not_qualified"
            )
        self.assertEqual(ledger_by_id[entry07]["runtime_state"], "not_applicable")

    def test_spatial_ai_core_interface_lock_fails_closed(self) -> None:
        acceptance = json.loads(verifier.ACCEPTANCE.read_text(encoding="utf-8"))
        historical_ledger = json.loads(
            (
                verifier.REPO_ROOT
                / "deploy/docker/thor-local/qualification/metadata-500-current-spatial-ai-utils-core-rebind-successor/post-state-official-capabilities.json"
            ).read_text(encoding="utf-8")
        )
        lock = copy.deepcopy(verifier.SPATIAL_AI_CORE_INTERFACE)
        lock["raw_sha256"] = "0" * 64
        with mock.patch.object(verifier, "SPATIAL_AI_CORE_INTERFACE", lock):
            with self.assertRaisesRegex(
                verifier.OracleContractError, "raw digest drift"
            ):
                verifier.compile_plan(historical_ledger, acceptance_document=acceptance)

    def test_partial_spatial_ai_stage1_reversion_fails_closed(self) -> None:
        ledger = copy.deepcopy(self.ledger)
        predecessor = json.loads(
            (
                verifier.REPO_ROOT
                / "deploy/docker/thor-local/qualification/metadata-500-current-mv3dt-config-utils-successor/post-state-root-official-capabilities.json"
            ).read_text(encoding="utf-8")
        )
        old = {row["id"]: row for row in predecessor["capabilities"]}
        for index, row in enumerate(ledger["capabilities"]):
            if row["id"] == verifier.SPATIAL_AI_IDS[0]:
                ledger["capabilities"][index] = old[row["id"]]
                break
        with self.assertRaisesRegex(
            verifier.OracleContractError, "partial SpatialAI runtime family promotion"
        ):
            verifier.compile_plan(ledger)

    def test_mv3dt_runtime_locks_use_confined_alternate_repository_root(self) -> None:
        projection = (
            verifier.REPO_ROOT / "deploy/docker/thor-local/qualification/"
            "metadata-500-current-mv3dt-config-utils-successor"
        )
        ledger = json.loads(
            (projection / "post-state-root-official-capabilities.json").read_text(
                encoding="utf-8"
            )
        )
        acceptance = json.loads(verifier.ACCEPTANCE.read_text(encoding="utf-8"))
        locks = [
            verifier.MV3DT_RUNTIME_EXECUTOR,
            *verifier.MV3DT_RUNTIME_FIXTURES.values(),
        ]
        spatial_bindings = verifier._spatial_ai_core_runtime_bindings(
            verifier.REPO_ROOT, ledger
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            alternate_root = Path(temporary_directory)
            for lock in locks:
                destination = alternate_root / lock["path"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(verifier.REPO_ROOT / lock["path"], destination)
            with mock.patch.object(
                verifier,
                "_spatial_ai_core_runtime_bindings",
                return_value=spatial_bindings,
            ):
                verifier.compile_plan(
                    ledger,
                    acceptance_document=acceptance,
                    repo_root=alternate_root,
                )
            package = (
                alternate_root / "deploy/docker/thor-local/qualification/"
                "mv3dt-config-utils-runtime-evidence-successor"
            )
            real_package = alternate_root / "real-mv3dt-runtime-package"
            package.rename(real_package)
            package.symlink_to(real_package, target_is_directory=True)
            with mock.patch.object(
                verifier,
                "_spatial_ai_core_runtime_bindings",
                return_value=spatial_bindings,
            ):
                with self.assertRaisesRegex(
                    verifier.OracleContractError, "path contains a symlink"
                ):
                    verifier.compile_plan(
                        ledger,
                        acceptance_document=acceptance,
                        repo_root=alternate_root,
                    )

    def test_static_planning_bindings_do_not_promote_full_oracles(self) -> None:
        bound = [
            item
            for item in self.plan["oracles"]
            if item.get("planning_executor_bindings")
        ]
        self.assertEqual(len(bound), 27)
        self.assertEqual(
            sum(len(item["planning_executor_bindings"]) for item in bound), 27
        )
        for item in bound:
            runtime_bound = {
                verifier.NVSTREAMER_FULL_CONFIG_CAPABILITY_ID: (
                    verifier.NVSTREAMER_FULL_CONFIG_EXECUTOR
                ),
                verifier.LVS_CUSTOM_MODEL_PROMPT_RUNTIME_CAPABILITY_ID: (
                    verifier.LVS_CUSTOM_MODEL_PROMPT_RUNTIME_EXECUTOR
                ),
            }
            if item["capability_id"] in runtime_bound:
                expected_executor = runtime_bound[item["capability_id"]]
                self.assertEqual(
                    item["acceptance_readiness"]["classification"],
                    "executor_ready",
                )
                self.assertEqual(
                    item["execution_bounds"]["executor"],
                    expected_executor,
                )
                self.assertEqual(
                    item["execution_bounds"]["collectors"],
                    [expected_executor],
                )
                self.assertEqual(
                    item["cleanup"]["executor"],
                    expected_executor,
                )
                self.assertEqual(
                    item["cleanup"]["postcondition_collectors"],
                    [expected_executor],
                )
            else:
                self.assertEqual(
                    item["acceptance_readiness"]["classification"],
                    "planning_index_only",
                )
                self.assertIsNone(item["execution_bounds"]["executor"])
                self.assertEqual(item["execution_bounds"]["collectors"], [])
                self.assertIsNone(item["cleanup"]["executor"])
                self.assertEqual(item["cleanup"]["postcondition_collectors"], [])
            self.assertEqual(item["evidence"], [])
            for binding in item["planning_executor_bindings"]:
                self.assertIs(binding["can_advance_capability"], False)
                self.assertIs(binding["can_mark_passed_current"], False)
                self.assertEqual(binding["runtime_evidence"], [])

    def test_offline_mv3dt_bindings_cover_only_the_observed_oracle_subset(self) -> None:
        expected_ids = {"tool.mv3dt.cam-info-generator", "tool.mv3dt.pub-sub-generator"}
        bound = {
            item["capability_id"]: item
            for item in self.plan["oracles"]
            if item.get("offline_tool_observation_bindings")
        }
        self.assertEqual(set(bound), expected_ids)
        for capability_id, item in bound.items():
            self.assertEqual(len(item["offline_tool_observation_bindings"]), 1)
            binding = item["offline_tool_observation_bindings"][0]
            self.assertEqual(
                binding["scope"], "bounded_static_tool_observation_subset_only"
            )
            self.assertIs(binding["can_advance_capability"], False)
            self.assertIs(binding["can_mark_passed_current"], False)
            self.assertEqual(binding["runtime_evidence"], [])
            self.assertEqual(
                binding["result"]["official_capability_effect"], "none_candidate_only"
            )
            coverage = binding["oracle_coverage"]
            self.assertEqual(
                set(coverage["covered_observation_ids"])
                | set(coverage["uncovered_observation_ids"]),
                {row["id"] for row in item["expected_observations"]},
            )
            self.assertEqual(
                set(coverage["covered_assertion_ids"])
                | set(coverage["uncovered_assertion_ids"]),
                {row["id"] for row in item["assertions"]},
            )
            self.assertEqual(
                coverage["uncovered_assertion_ids"],
                ["contract-05", "contract-06", "contract-07", "contract-08"],
                capability_id,
            )

    def test_offline_mv3dt_binding_is_derived_from_strict_execution_receipt(
        self,
    ) -> None:
        receipt_path = (
            verifier.REPO_ROOT
            / verifier.OFFLINE_MV3DT_FILES["execution_receipt"]["path"]
        )
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(
            hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            verifier.OFFLINE_MV3DT_FILES["execution_receipt"]["raw_sha256"],
        )
        bindings = verifier._offline_mv3dt_tool_bindings()
        first_run = receipt["deterministic_runs"][0]
        for capability_id, rows in bindings.items():
            binding = rows[0]
            self.assertEqual(binding["result"]["observation"], receipt["observation"])
            self.assertEqual(binding["result"]["run_count"], receipt["run_count"])
            self.assertEqual(
                binding["execution_receipt"]["raw_sha256"],
                hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            )
            dependency = binding["dependency_observation"]
            self.assertEqual(
                dependency["observed_versions_sha256"],
                "f8b538e36776da71af95af5a667426dbd5cbb3e3fa482c2c5850ba9306888e80",
            )
            self.assertIs(
                dependency["declared_versions_match_observed_distributions"], False
            )
            self.assertIs(dependency["normative_for_declared_requirements"], False)
            self.assertEqual(len(dependency["mismatches"]), 4)
            selected_key = (
                "cam_info"
                if capability_id.endswith("cam-info-generator")
                else "pub_sub"
            )
            self.assertEqual(
                binding["selected_semantic"],
                {selected_key: first_run["semantic"][selected_key]},
            )

    def test_offline_mv3dt_every_contract_source_lock_is_rehashed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_paths = self._copy_offline_mv3dt_inputs(root)
            self.assertEqual(len(source_paths), 4)
            current_inputs = [
                relative
                for relative in source_paths
                if relative != "deploy/docker/thor-local/parity/manifest.json"
            ]
            self.assertEqual(len(current_inputs), 3)
            for relative in current_inputs:
                with self.subTest(relative=relative):
                    path = root / relative
                    original = path.read_bytes()
                    path.write_bytes(original + b"\nsource-lock-tamper")
                    with self.assertRaisesRegex(
                        verifier.OracleContractError, "source lock differs"
                    ):
                        verifier._offline_mv3dt_tool_bindings(root)
                    path.write_bytes(original)

    def test_offline_mv3dt_historical_manifest_lock_is_preserved(self) -> None:
        bindings = verifier._offline_mv3dt_tool_bindings()
        expected = "6b041fbd169649b6dac5e68908e4a6dd219da9160cf72594219058885a9b9127"
        self.assertNotEqual(
            hashlib.sha256(
                (
                    verifier.REPO_ROOT / "deploy/docker/thor-local/parity/manifest.json"
                ).read_bytes()
            ).hexdigest(),
            expected,
        )
        for rows in bindings.values():
            manifest_lock = next(
                item
                for item in rows[0]["source_locks"]
                if item["path"] == "deploy/docker/thor-local/parity/manifest.json"
            )
            self.assertEqual(manifest_lock["sha256"], expected)

    def test_offline_mv3dt_receipt_raw_lock_and_schema_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._copy_offline_mv3dt_inputs(root)
            receipt_path = (
                root / verifier.OFFLINE_MV3DT_FILES["execution_receipt"]["path"]
            )
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["run_count"] = 3
            receipt_path.write_text(
                json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(
                verifier.OracleContractError, "execution_receipt raw digest differs"
            ):
                verifier._offline_mv3dt_tool_bindings(root)
            original_lock = verifier.OFFLINE_MV3DT_FILES["execution_receipt"][
                "raw_sha256"
            ]
            verifier.OFFLINE_MV3DT_FILES["execution_receipt"]["raw_sha256"] = (
                hashlib.sha256(receipt_path.read_bytes()).hexdigest()
            )
            try:
                with self.assertRaisesRegex(
                    verifier.OracleContractError, "execution receipt schema failed"
                ):
                    verifier._offline_mv3dt_tool_bindings(root)
            finally:
                verifier.OFFLINE_MV3DT_FILES["execution_receipt"]["raw_sha256"] = (
                    original_lock
                )

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
        with self.assertRaisesRegex(
            verifier.OracleContractError, "oracle contract drift"
        ):
            verifier.validate(plan, copy.deepcopy(self.ledger))

    def test_generic_action_reuse_fails_closed(self) -> None:
        plan = copy.deepcopy(self.plan)
        first, second = plan["oracles"][:2]
        second["fixture"] = copy.deepcopy(first["fixture"])
        second["expected_observations"] = copy.deepcopy(first["expected_observations"])
        second["assertions"] = copy.deepcopy(first["assertions"])
        with self.assertRaisesRegex(
            verifier.OracleContractError, "oracle contract drift"
        ):
            verifier.validate(plan, copy.deepcopy(self.ledger))

    def test_fabricated_pass_or_evidence_fails_closed(self) -> None:
        for field, value in (
            ("current_state", "passed_current"),
            ("evidence", [{"result": "pass"}]),
        ):
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
            self.assertEqual(
                item["reviewed_scenario_ids"][-1], f"oracle.{capability_id}"
            )

    def test_warehouse_sample_is_excluded_but_custom_fixtures_remain(self) -> None:
        self.assertTrue(
            all(
                not item["fixture"]["warehouse_sample_bundle"]
                for item in self.plan["oracles"]
            )
        )
        calibration = [
            item
            for item in self.plan["oracles"]
            if item["capability_id"].startswith("calibration.")
        ]
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
        local = [
            item
            for item in self.plan["oracles"]
            if item["current_state"] == "open_unexecuted"
        ]
        for item in local:
            cleanup = item["cleanup"]
            self.assertIn(
                cleanup["mutation"],
                {"read_only", "temporary_files_only", "namespaced_and_reversible"},
            )
            if cleanup["mutation"] == "read_only":
                expected_targets = (
                    verifier.OFFICIAL_EDGE_MODEL_RUNTIME_NAMESPACES
                    if item["capability_id"]
                    in verifier.OFFICIAL_EDGE_MODEL_RUNTIME_CAPABILITY_IDS
                    else []
                )
                self.assertEqual(cleanup["targets"], expected_targets)
                self.assertEqual(cleanup["allowlist"], expected_targets)
            else:
                expected_target_count = (
                    len(
                        verifier.EVENT_TRANSPORT_RUNTIME_NAMESPACES[
                            item["capability_id"]
                        ]
                    )
                    if item["capability_id"]
                    in verifier.EVENT_TRANSPORT_RUNTIME_CAPABILITY_IDS
                    else len(verifier.ALERT_WEBSOCKET_RUNTIME_NAMESPACES)
                    if item["capability_id"]
                    == verifier.ALERT_WEBSOCKET_RUNTIME_CAPABILITY_ID
                    else len(verifier.RT_VLM_SSE_RUNTIME_NAMESPACES)
                    if item["capability_id"]
                    in verifier.RT_VLM_SSE_RUNTIME_CAPABILITY_IDS
                    else len(verifier.LVS_FORMATS_RUNTIME_NAMESPACES)
                    if item["capability_id"]
                    == verifier.LVS_FORMATS_RUNTIME_CAPABILITY_ID
                    else len(verifier.LVS_SINGLE_REQUEST_RUNTIME_NAMESPACES)
                    if item["capability_id"]
                    == verifier.LVS_SINGLE_REQUEST_RUNTIME_CAPABILITY_ID
                    else len(verifier.LVS_CUSTOM_MODEL_PROMPT_RUNTIME_NAMESPACES)
                    if item["capability_id"]
                    == verifier.LVS_CUSTOM_MODEL_PROMPT_RUNTIME_CAPABILITY_ID
                    else len(verifier.VIOS_WEBRTC_LIVE_NAMESPACES)
                    if item["capability_id"]
                    == verifier.VIOS_WEBRTC_LIVE_CAPABILITY_ID
                    else 1
                )
                self.assertEqual(len(cleanup["targets"]), expected_target_count)
                if item["capability_id"] in verifier.SPATIAL_AI_IDS[:7]:
                    self.assertEqual(
                        cleanup["targets"], [item["fixture"]["input"]["namespace"]]
                    )
                    self.assertTrue(cleanup["targets"][0].startswith("spatial-ai-"))
                elif item["capability_id"] == verifier.VIOS_BYTE_DOWNLOAD_CAPABILITY_ID:
                    self.assertEqual(
                        cleanup["targets"], [verifier.VIOS_BYTE_DOWNLOAD_NAMESPACE]
                    )
                elif item["capability_id"] == verifier.NVSTREAMER_FILE_CAPABILITY_ID:
                    self.assertEqual(
                        cleanup["targets"], [verifier.NVSTREAMER_FILE_NAMESPACE]
                    )
                elif item["capability_id"] == verifier.NVSTREAMER_SYNC_CAPABILITY_ID:
                    self.assertEqual(
                        cleanup["targets"], [verifier.NVSTREAMER_SYNC_NAMESPACE]
                    )
                elif (
                    item["capability_id"]
                    == verifier.NVSTREAMER_FULL_CONFIG_CAPABILITY_ID
                ):
                    self.assertEqual(
                        cleanup["targets"],
                        [verifier.NVSTREAMER_FULL_CONFIG_NAMESPACE],
                    )
                elif (
                    item["capability_id"]
                    == verifier.VIOS_WEBRTC_REPLAY_CAPABILITY_ID
                ):
                    self.assertEqual(
                        cleanup["targets"],
                        [verifier.VIOS_WEBRTC_REPLAY_NAMESPACE],
                    )
                elif (
                    item["capability_id"]
                    == verifier.VIOS_WEBRTC_LIVE_CAPABILITY_ID
                ):
                    self.assertEqual(
                        cleanup["targets"], verifier.VIOS_WEBRTC_LIVE_NAMESPACES
                    )
                elif (
                    item["capability_id"]
                    in verifier.EVENT_TRANSPORT_RUNTIME_CAPABILITY_IDS
                ):
                    self.assertEqual(
                        cleanup["targets"],
                        verifier.EVENT_TRANSPORT_RUNTIME_NAMESPACES[
                            item["capability_id"]
                        ],
                    )
                elif (
                    item["capability_id"]
                    == verifier.ALERT_WEBSOCKET_RUNTIME_CAPABILITY_ID
                ):
                    self.assertEqual(
                        cleanup["targets"],
                        verifier.ALERT_WEBSOCKET_RUNTIME_NAMESPACES,
                    )
                elif (
                    item["capability_id"]
                    in verifier.RT_VLM_SSE_RUNTIME_CAPABILITY_IDS
                ):
                    self.assertEqual(
                        cleanup["targets"],
                        verifier.RT_VLM_SSE_RUNTIME_NAMESPACES,
                    )
                else:
                    self.assertTrue(cleanup["targets"][0].startswith("vss-oracle-"))
                self.assertEqual(cleanup["allowlist"], cleanup["targets"])
            self.assertTrue(cleanup["postconditions"])

    def test_external_boundaries_require_operator_opt_in(self) -> None:
        external = [
            item
            for item in self.plan["oracles"]
            if item["current_state"] == "external_boundary_unexecuted"
        ]
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
        with self.assertRaisesRegex(
            verifier.OracleContractError, "oracle contract drift"
        ):
            verifier.validate(copy.deepcopy(self.plan), ledger)

    def test_relevant_ledger_semantics_require_oracle_regeneration(self) -> None:
        mutations = {
            "source locator": lambda item: item["source_claims"][0].update(
                locator="different locator"
            ),
            "gap": lambda item: item.update(gap="different reviewed gap"),
            "thor state": lambda item: item.update(
                thor_state=("partial" if item.get("thor_state") == "wired" else "wired")
            ),
            "runtime state": lambda item: item.update(
                runtime_state=(
                    "not_qualified"
                    if item.get("runtime_state") == "static_only"
                    else "static_only"
                )
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                ledger = copy.deepcopy(self.ledger)
                mutate(ledger["capabilities"][0])
                with self.assertRaisesRegex(
                    verifier.OracleContractError, "oracle contract drift"
                ):
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
            self.assertEqual(
                by_id[capability_id]["fixture"]["kind"], "generated_custom_media"
            )

    def test_cpu_multimedia_oracle_requires_hardware_cpu_discrimination(self) -> None:
        oracle = next(
            item
            for item in self.plan["oracles"]
            if item["capability_id"] == verifier.CPU_MULTIMEDIA_CAPABILITY_ID
        )
        self.assertEqual(
            oracle["oracle_id"],
            f"oracle.{verifier.CPU_MULTIMEDIA_CAPABILITY_ID}",
        )
        self.assertEqual(
            oracle["profile"],
            "behavior-manifest-entry-vios-codecs-audio-05-cpu-multimedia-support",
        )
        self.assertEqual(oracle["mode"], "runtime")
        self.assertEqual(oracle["fixture"]["kind"], "generated_custom_media")
        action = oracle["fixture"]["input"]["action"]
        for token in (
            "hardware-default",
            "use_software_path=true",
            "m_useNvV4l2Dec",
            "m_useNvV4l2Enc",
            "nvv4l2",
            "CPU elements",
        ):
            self.assertIn(token, action)
        observation = next(
            item
            for item in oracle["expected_observations"]
            if item["id"] == "hardware_cpu_discrimination"
        )
        self.assertIn("false-default", observation["description"])
        self.assertIn("nvv4l2", observation["description"])
        self.assertIn("libav/x264/x265", observation["description"])
        self.assertEqual(oracle["execution_bounds"]["max_requests"], 2)
        self.assertEqual(oracle["execution_bounds"]["max_actions"], 2)
        self.assertEqual(
            oracle["acceptance_readiness"]["classification"],
            "planning_index_only",
        )
        self.assertEqual(oracle["current_state"], "open_unexecuted")
        self.assertEqual(oracle["evidence"], [])

    def test_request_bounds_are_arithmetically_exact(self) -> None:
        for item in self.plan["oracles"]:
            bounds = item["execution_bounds"]
            workload = bounds["workload"]
            expected = (
                workload["units"] * workload["requests_per_unit"]
                + workload["overhead_requests"]
            )
            self.assertEqual(workload["calculated_max_requests"], expected)
            self.assertEqual(bounds["max_requests"], expected)
            override = verifier.LOCAL_RUNTIME_WORKLOAD_OVERRIDES.get(
                item["capability_id"]
            )
            mv3dt_runtime = verifier.MV3DT_RUNTIME_FIXTURES.get(item["capability_id"])
            expected_actions = (
                mv3dt_runtime["max_actions"]
                if mv3dt_runtime is not None
                else verifier.NVSTREAMER_SYNC_MAX_ACTIONS
                if item["capability_id"] == verifier.NVSTREAMER_SYNC_CAPABILITY_ID
                else verifier.NVSTREAMER_FULL_CONFIG_MAX_ACTIONS
                if (
                    item["capability_id"]
                    == verifier.NVSTREAMER_FULL_CONFIG_CAPABILITY_ID
                )
                else verifier.VIOS_WEBRTC_REPLAY_MAX_ACTIONS
                if (
                    item["capability_id"]
                    == verifier.VIOS_WEBRTC_REPLAY_CAPABILITY_ID
                )
                else verifier.VIOS_WEBRTC_LIVE_MAX_ACTIONS
                if (
                    item["capability_id"]
                    == verifier.VIOS_WEBRTC_LIVE_CAPABILITY_ID
                )
                else verifier.VIDEO_ANALYTICS_RUNTIME_MAX_ACTIONS
                if (
                    item["capability_id"]
                    in verifier.VIDEO_ANALYTICS_RUNTIME_CAPABILITY_IDS
                )
                else verifier.EVENT_TRANSPORT_RUNTIME_MAX_ACTIONS
                if (
                    item["capability_id"]
                    in verifier.EVENT_TRANSPORT_RUNTIME_CAPABILITY_IDS
                )
                else verifier.ALERT_WEBSOCKET_RUNTIME_MAX_ACTIONS
                if (
                    item["capability_id"]
                    == verifier.ALERT_WEBSOCKET_RUNTIME_CAPABILITY_ID
                )
                else verifier.RT_VLM_SSE_RUNTIME_MAX_ACTIONS
                if item["capability_id"]
                in verifier.RT_VLM_SSE_RUNTIME_CAPABILITY_IDS
                else verifier.OFFICIAL_EDGE_MODEL_RUNTIME_MAX_ACTIONS
                if item["capability_id"]
                in verifier.OFFICIAL_EDGE_MODEL_RUNTIME_CAPABILITY_IDS
                else verifier.LVS_FORMATS_RUNTIME_MAX_ACTIONS
                if (
                    item["capability_id"]
                    == verifier.LVS_FORMATS_RUNTIME_CAPABILITY_ID
                )
                else verifier.LVS_SINGLE_REQUEST_RUNTIME_MAX_ACTIONS
                if (
                    item["capability_id"]
                    == verifier.LVS_SINGLE_REQUEST_RUNTIME_CAPABILITY_ID
                )
                else verifier.LVS_CUSTOM_MODEL_PROMPT_RUNTIME_MAX_ACTIONS
                if (
                    item["capability_id"]
                    == verifier.LVS_CUSTOM_MODEL_PROMPT_RUNTIME_CAPABILITY_ID
                )
                else override[2]
                if override is not None
                else expected
            )
            self.assertEqual(bounds["max_actions"], expected_actions)
        by_id = {item["capability_id"]: item for item in self.plan["oracles"]}
        self.assertEqual(
            by_id["behavior.rt-embed.kafka-queue-bound"]["execution_bounds"][
                "max_requests"
            ],
            1025,
        )
        self.assertEqual(
            by_id["api.core.video-analytics-56"]["execution_bounds"]["max_requests"],
            225,
        )
        self.assertEqual(
            by_id["api.core.video-analytics-56"]["execution_bounds"]["workload"][
                "phases"
            ],
            ["positive", "adjacent_negative", "readback", "cleanup"],
        )

    def test_exact_20_local_runtime_workload_overrides_are_capability_bound(
        self,
    ) -> None:
        self.assertEqual(len(verifier.LOCAL_RUNTIME_WORKLOAD_OVERRIDES), 20)
        self.assertEqual(
            sum(row[1] for row in verifier.LOCAL_RUNTIME_WORKLOAD_OVERRIDES.values()),
            202,
        )
        self.assertEqual(
            sum(row[2] for row in verifier.LOCAL_RUNTIME_WORKLOAD_OVERRIDES.values()),
            207,
        )
        by_id = {item["capability_id"]: item for item in self.plan["oracles"]}
        for capability_id, (
            planning_id,
            requests,
            actions,
        ) in verifier.LOCAL_RUNTIME_WORKLOAD_OVERRIDES.items():
            oracle = by_id[capability_id]
            self.assertEqual(oracle["execution_bounds"]["max_requests"], requests)
            self.assertEqual(oracle["execution_bounds"]["max_actions"], actions)
            self.assertEqual(
                oracle["execution_bounds"]["workload"]["phases"],
                verifier.LOCAL_RUNTIME_WORKLOAD_PHASES,
            )
            self.assertEqual(
                oracle["fixture"]["input"]["contract"]["wave3_acceptance"][
                    "planning_requirement_ids"
                ],
                [planning_id],
            )
            self.assertEqual(oracle["current_state"], "open_unexecuted")
            self.assertEqual(oracle["evidence"], [])
            self.assertIs(oracle["fixture"]["warehouse_sample_bundle"], False)

    def test_models_stage_before_runtime_not_inside_it(self) -> None:
        models = [
            item
            for item in self.plan["oracles"]
            if item["ledger_binding"]["kind"] == "model"
        ]
        self.assertTrue(models)
        for item in models:
            self.assertEqual(
                item["execution_bounds"]["model_staging"], "prerequisite_only"
            )
            self.assertIn(
                "model-artifact-staged",
                {gate["id"] for gate in item["admission_prerequisites"]},
            )

    def test_custom_thor_lane_is_bounded_per_profile_runtime(self) -> None:
        oracle = next(
            item
            for item in self.plan["oracles"]
            if item["capability_id"] == "boundary.thor.custom-all-local-extension"
        )
        profiles = oracle["ledger_binding"]["contract"]["profiles"]
        self.assertEqual(oracle["mode"], "runtime")
        self.assertEqual(oracle["execution_bounds"]["workload"]["units"], len(profiles))
        observation_ids = {item["id"] for item in oracle["expected_observations"]}
        self.assertTrue(
            {f"profile_{item.replace('-', '_')}" for item in profiles}
            <= observation_ids
        )
        self.assertIn("sample_exclusion", observation_ids)

    def test_orchestrator_separates_discovery_from_approved_lifecycle(self) -> None:
        oracle = next(
            item
            for item in self.plan["oracles"]
            if item["capability_id"] == "api.orchestrator-mcp.tools-9"
        )
        self.assertEqual(oracle["mode"], "runtime")
        self.assertIn(
            "orchestrator-lifecycle-approval",
            {gate["id"] for gate in oracle["admission_prerequisites"]},
        )
        observation_ids = [item["id"] for item in oracle["expected_observations"]]
        self.assertIn("discovery_phase", observation_ids)
        self.assertIn("approved_lifecycle_phase", observation_ids)
        self.assertIn(
            "only after explicit lifecycle approval",
            oracle["fixture"]["input"]["action"],
        )
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
        cases = {item["capability_id"]: item for item in self.protocol_cases["cases"]}
        for oracle in protocol_oracles:
            case = cases[oracle["capability_id"]]
            binding = oracle["protocol_case_binding"]
            self.assertEqual(binding["path"], verifier.PROTOCOL_CASES_PATH)
            self.assertEqual(
                binding["file_sha256"], verifier.PROTOCOL_CASES_FILE_SHA256
            )
            self.assertEqual(
                binding["contract_set_sha256"], verifier.PROTOCOL_CASES_SET_SHA256
            )
            self.assertEqual(
                binding["target_commit"], self.protocol_cases["target_commit"]
            )
            self.assertEqual(binding["case_id"], case["case_id"])
            self.assertEqual(
                binding["positive_vector_id"], case["positive_vector"]["id"]
            )
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
            "source hash": lambda binding: binding["source_hashes"][0].update(
                content_sha256="0" * 64
            ),
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

    def test_new_reviewed_claim_is_compiled_without_count_or_source_assumptions(
        self,
    ) -> None:
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
            next(
                item for item in ledger["capabilities"] if item["kind"] == "deployment"
            )
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
        self.assertEqual(
            oracle["execution_bounds"]["network_scope"], "loopback-or-compose-internal"
        )
        self.assertIn("local namespace", oracle["fixture"]["input"]["action"])
        self.assertEqual(oracle["expected_observations"][-1]["id"], "local_admission")

    def test_duplicate_json_keys_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "duplicate.json"
            path.write_text(
                '{"schema_version": 1, "schema_version": 1}', encoding="utf-8"
            )
            with self.assertRaisesRegex(
                verifier.OracleContractError, "duplicate JSON key"
            ):
                verifier._load(path)


if __name__ == "__main__":
    unittest.main()
