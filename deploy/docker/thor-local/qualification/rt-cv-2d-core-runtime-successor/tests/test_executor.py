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
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RtCv2dCoreRuntimeQualificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = json.loads((PACKAGE / "contract.json").read_text())
        cls.schema = json.loads((PACKAGE / "receipt.schema.json").read_text())
        cls.receipt = json.loads((PACKAGE / "runtime-receipt.json").read_text())

    def test_receipt_validates_strict_schema(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        Draft202012Validator(self.schema).validate(self.receipt)

    def test_contract_and_receipt_bind_exact_rows(self) -> None:
        expected_ids = [
            "manifest-entry.rt-cv-2d.00-file-and-stream-detection-tracking",
            "manifest-entry.rt-cv-2d.05-dynamic-stream-lifecycle",
            "manifest-entry.rt-cv-2d.06-health-and-metrics",
            "manifest-entry.rt-cv-2d.07-thor-vpi-tracker-tuning",
        ]
        self.assertEqual(self.contract["official_indices"], [375, 380, 381, 382])
        self.assertEqual(self.contract["capability_ids"], expected_ids)
        self.assertEqual(self.receipt["official_indices"], [375, 380, 381, 382])
        self.assertEqual(self.receipt["capability_ids"], expected_ids)
        self.assertEqual(self.receipt["status"], "passed")
        self.assertEqual(
            self.receipt["contract_sha256"], sha(PACKAGE / "contract.json")
        )

    def test_every_source_lock_matches(self) -> None:
        for lock in self.contract["source_locks"]:
            path = REPO / lock["path"]
            self.assertTrue(path.is_file(), lock["path"])
            self.assertFalse(path.is_symlink(), lock["path"])
            self.assertEqual(sha(path), lock["sha256"], lock["path"])

    def test_thor_tuning_is_dynamic_and_compose_wires_profile(self) -> None:
        start = (REPO / "deploy/docker/services/rtvi/rtvi-cv/ds-start.sh").read_text()
        compose = (REPO / "deploy/docker/thor-local/compose.yml").read_text()
        self.assertIn("apply_thor_tracker_tuning", start)
        self.assertIn("max_targets_per_stream=$((512 / max_sources))", start)
        self.assertIn("max_targets_per_stream > 50", start)
        self.assertIn("visualTrackerType: 2", start)
        self.assertIn("vpiBackend4DcfTracker: 2", start)
        self.assertIn("THOR_LOCAL_RT_CV_HARDWARE_PROFILE:-AGX-THOR", compose)

    def test_runtime_evidence_is_substantive(self) -> None:
        for lane in ("file_detection_tracking", "rtsp_detection_tracking"):
            evidence = self.receipt[lane]["detection_tracking"]
            self.assertEqual(evidence["frames"], 8)
            self.assertGreater(evidence["objects"], 0)
            self.assertGreater(evidence["repeated_track_ids"], 0)
            self.assertEqual(evidence["embedding_dimensions"], [1152])
            self.assertTrue({"Person", "Pallet"}.issubset(evidence["types"]))
            self.assertTrue(evidence["finite_bboxes"])
            self.assertTrue(evidence["finite_confidences"])
            self.assertTrue(evidence["finite_embeddings"])
        self.assertEqual(self.receipt["configuration"]["capacity_product"], 512)
        self.assertEqual(
            self.receipt["thor_vpi_tracker"]["vpi_error_count_after_clean_start"],
            0,
        )

    def test_policy_and_cleanup_are_fail_closed(self) -> None:
        self.assertEqual(self.receipt["cleanup"]["failures"], [])
        for key, value in self.receipt["cleanup"].items():
            if key != "failures":
                self.assertTrue(value, key)
        policy = self.receipt["policy"]
        self.assertEqual(policy["agent_generate_calls"], 0)
        self.assertEqual(policy["main_rt_cv_stream_mutations"], 0)
        self.assertEqual(policy["main_vios_stream_mutations"], 0)
        self.assertEqual(policy["network_downloads"], 0)
        self.assertEqual(policy["warehouse_sample_bundle"], "excluded")
        for key in (
            "raw_camera_ids_retained",
            "raw_stream_urls_retained",
            "raw_embeddings_retained",
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
            timeout=20,
        )
        plan = json.loads(result.stdout)
        self.assertEqual(plan["status"], "ready")
        self.assertEqual(plan["official_indices"], [375, 380, 381, 382])
        self.assertEqual(plan["network_downloads"], 0)
        self.assertEqual(plan["main_rt_cv_stream_mutations"], 0)
        self.assertEqual(plan["main_vios_stream_mutations"], 0)


if __name__ == "__main__":
    unittest.main()
