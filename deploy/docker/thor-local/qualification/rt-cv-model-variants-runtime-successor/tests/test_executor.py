from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parent
REPO = HERE.parents[5]


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


class RtCvModelVariantsRuntimeQualificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = json.loads((PACKAGE / "contract.json").read_text())
        cls.schema = json.loads((PACKAGE / "receipt.schema.json").read_text())
        cls.receipt = json.loads((PACKAGE / "runtime-receipt.json").read_text())

    def test_receipt_validates_strict_schema(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        Draft202012Validator(self.schema).validate(self.receipt)

    def test_contract_and_receipt_bind_exact_row(self) -> None:
        expected = [
            "manifest-entry.rt-cv-2d.01-warehouse-and-smart-city-rt-detr-gdino"
        ]
        self.assertEqual(self.contract["official_indices"], [376])
        self.assertEqual(self.contract["capability_ids"], expected)
        self.assertEqual(self.receipt["official_indices"], [376])
        self.assertEqual(self.receipt["capability_ids"], expected)
        self.assertEqual(self.receipt["status"], "passed")
        self.assertEqual(
            self.receipt["contract_sha256"], sha(PACKAGE / "contract.json")
        )

    def test_every_source_model_and_fixture_lock_matches(self) -> None:
        for lock in self.contract["source_locks"]:
            path = REPO / lock["path"]
            self.assertTrue(path.is_file(), lock["path"])
            self.assertFalse(path.is_symlink(), lock["path"])
            self.assertEqual(sha(path), lock["sha256"], lock["path"])
        for asset in self.contract["assets"].values():
            path = REPO / asset["path"]
            self.assertEqual(path.stat().st_size, asset["bytes"], asset["path"])
            self.assertEqual(sha(path), asset["sha256"], asset["path"])

    def test_three_detector_identities_are_not_conflated(self) -> None:
        warehouse = self.receipt["warehouse_rtdetr"]
        self.assertEqual(warehouse["source_package_id"], "rt-cv-2d-core-runtime-successor")
        self.assertTrue(warehouse["class_map_person_and_pallet"])
        self.assertGreater(warehouse["file_objects"], 0)
        self.assertGreater(warehouse["rtsp_objects"], 0)

        rtdetr = self.receipt["smart_city_rtdetr"]["configuration"]
        self.assertEqual(rtdetr["variant"], "smart_city_rtdetr")
        self.assertEqual(rtdetr["detector_backend"], "nvinfer")
        self.assertEqual(rtdetr["declared_class_count"], 5)
        self.assertTrue(rtdetr["declared_person_class"])
        self.assertEqual(rtdetr["streammux_extract_sei_sim_time"], 0)
        self.assertEqual(rtdetr["streammux_drop_backward_sei"], 0)

        gdino = self.receipt["smart_city_gdino"]["configuration"]
        self.assertEqual(gdino["variant"], "smart_city_gdino")
        self.assertEqual(gdino["detector_backend"], "triton")
        self.assertEqual(gdino["prompt_class"], "person")
        self.assertEqual(gdino["prompt_threshold"], 0.5)
        self.assertEqual(gdino["streammux_extract_sei_sim_time"], 0)
        self.assertEqual(gdino["streammux_drop_backward_sei"], 0)
        for value in self.receipt["model_family_separation"].values():
            self.assertTrue(value)

    def test_both_smart_city_lanes_prove_detection_and_tracking(self) -> None:
        for lane_name in ("smart_city_rtdetr", "smart_city_gdino"):
            lane = self.receipt[lane_name]
            proof = lane["detection_tracking"]
            self.assertEqual(proof["frames"], 8)
            self.assertGreater(proof["objects"], 0)
            self.assertTrue(proof["person_class_correlated"])
            self.assertGreater(proof["repeated_track_ids"], 0)
            self.assertTrue(proof["finite_bboxes"])
            self.assertTrue(proof["finite_confidences"])
            self.assertEqual(lane["active_metrics"]["stream_count"], 1)
            self.assertTrue(lane["active_metrics"]["fps_positive"])
            self.assertEqual(lane["final_stream_count"], 0)
            self.assertFalse(lane["oom_killed"])
            self.assertEqual(lane["restart_count"], 0)
            self.assertGreater(lane["engine"]["byte_count"], 50_000_000)
            self.assertTrue(lane["engine"]["retained_for_local_reuse"])
        self.assertGreater(
            self.receipt["smart_city_gdino"]["engine"]["byte_count"],
            300_000_000,
        )

    def test_rtdetr_first_build_replacement_is_explicit_when_used(self) -> None:
        lane = self.receipt["smart_city_rtdetr"]
        if lane["build_trigger_add"] is None:
            self.assertFalse(lane["first_build_container_replaced"])
            self.assertIsNone(lane["first_build_runtime_log_sha256"])
            self.assertEqual(lane["container_launch_count"], 1)
            self.assertEqual(lane["add_attempt_count"], 1)
        else:
            self.assertEqual(lane["build_trigger_add"]["http_status"], 200)
            self.assertTrue(lane["first_build_container_replaced"])
            self.assertRegex(lane["first_build_runtime_log_sha256"], "^[0-9a-f]{64}$")
            self.assertEqual(lane["container_launch_count"], 2)
            self.assertEqual(lane["add_attempt_count"], 2)

    def test_policy_cleanup_and_fixture_are_fail_closed(self) -> None:
        cleanup = self.receipt["cleanup"]
        self.assertEqual(cleanup["failures"], [])
        for key, value in cleanup.items():
            if key not in ("failures", "main_rt_cv_stream_count"):
                self.assertTrue(value, key)
        self.assertEqual(cleanup["main_rt_cv_stream_count"], 0)
        self.assertEqual(self.receipt["fixture"]["warehouse_sample_bundle"], "excluded")
        self.assertTrue(self.receipt["fixture"]["codec_h264"])
        self.assertEqual(self.receipt["fixture"]["duration_seconds"], 60)
        self.assertTrue(self.receipt["fixture"]["loopback_dynamic_source_host_network"])
        self.assertTrue(self.receipt["fixture"]["loopback_dynamic_source_udp_rtp_listener"])
        self.assertTrue(self.receipt["fixture"]["loopback_dynamic_source_udp_rtcp_listener"])
        self.assertTrue(self.receipt["fixture"]["loopback_dynamic_source_server_ports_exact"])
        policy = self.receipt["policy"]
        self.assertEqual(policy["agent_generate_calls"], 0)
        self.assertEqual(policy["main_rt_cv_stream_mutations"], 0)
        self.assertEqual(policy["main_vios_stream_mutations"], 0)
        self.assertEqual(policy["network_downloads"], 0)
        self.assertEqual(policy["warehouse_sample_bundle"], "excluded")
        for key in (
            "raw_camera_ids_retained",
            "raw_stream_urls_retained",
            "raw_broker_messages_retained",
            "credentials_retained",
        ):
            self.assertFalse(policy[key], key)

    def test_plan_is_read_only_and_ready(self) -> None:
        result = subprocess.run(
            [sys.executable, str(PACKAGE / "executor.py"), "plan"],
            cwd=REPO,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        plan = json.loads(result.stdout)
        self.assertEqual(plan["status"], "ready")
        self.assertEqual(plan["official_indices"], [376])
        self.assertTrue(plan["cached_source_models_exact"])
        self.assertFalse(plan["writes_or_lifecycle_actions"])


if __name__ == "__main__":
    unittest.main()
