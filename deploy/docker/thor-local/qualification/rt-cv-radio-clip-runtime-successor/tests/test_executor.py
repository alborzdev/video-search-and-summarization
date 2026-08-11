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


class RtCvRadioClipRuntimeQualificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = json.loads((PACKAGE / "contract.json").read_text())
        cls.schema = json.loads((PACKAGE / "receipt.schema.json").read_text())
        cls.receipt = json.loads((PACKAGE / "runtime-receipt.json").read_text())

    def test_receipt_validates_strict_schema(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        Draft202012Validator(self.schema).validate(self.receipt)

    def test_contract_and_receipt_bind_exact_row(self) -> None:
        expected = ["manifest-entry.rt-cv-2d.02-radio-clip"]
        self.assertEqual(self.contract["official_indices"], [377])
        self.assertEqual(self.contract["capability_ids"], expected)
        self.assertEqual(self.receipt["official_indices"], [377])
        self.assertEqual(self.receipt["capability_ids"], expected)
        self.assertEqual(self.receipt["status"], "passed")
        self.assertEqual(self.receipt["contract_sha256"], sha(PACKAGE / "contract.json"))

    def test_ngc_identity_is_exact_and_signed(self) -> None:
        source = self.contract["ngc_source"]
        self.assertEqual(source["registry_model"], "nvidia/tao/radio-clip:deployable_v1.0")
        self.assertEqual(source["version_id"], "deployable_v1.0")
        self.assertTrue(source["signed"])
        self.assertEqual(source["status"], "UPLOAD_COMPLETE")
        self.assertEqual(source["total_file_count"], 8)
        self.assertEqual(source["total_size_in_bytes"], 5534521620)

    def test_every_source_model_and_tokenizer_lock_matches(self) -> None:
        for lock in self.contract["source_locks"]:
            path = REPO / lock["path"]
            self.assertTrue(path.is_file(), lock["path"])
            self.assertFalse(path.is_symlink(), lock["path"])
            self.assertEqual(sha(path), lock["sha256"], lock["path"])
        for asset in self.contract["assets"].values():
            path = REPO / asset["path"]
            self.assertTrue(path.is_file(), asset["path"])
            self.assertFalse(path.is_symlink(), asset["path"])
            self.assertEqual(path.stat().st_size, asset["bytes"], asset["path"])
            self.assertEqual(sha(path), asset["sha256"], asset["path"])
        tokenizer = REPO / self.contract["tokenizer"]["path"]
        expected_names = set(self.contract["tokenizer"]["files"])
        self.assertEqual({path.name for path in tokenizer.iterdir() if path.is_file()}, expected_names)
        for name, lock in self.contract["tokenizer"]["files"].items():
            path = tokenizer / name
            self.assertEqual(path.stat().st_size, lock["bytes"], name)
            self.assertEqual(sha(path), lock["sha256"], name)

    def test_object_correlated_radio_clip_evidence_is_substantive(self) -> None:
        identity = self.receipt["artifact_identity"]
        self.assertEqual(identity["model"], "radio-clip")
        self.assertEqual(identity["version"], "v1.0")
        self.assertEqual(identity["embedding_dimension"], 1536)
        proof = self.receipt["reidentification"]
        self.assertEqual(proof["embedding_dimensions"], [1536])
        self.assertTrue(proof["finite_embeddings"])
        self.assertEqual(proof["embedded_object_types"], ["Pallet", "Person"])
        self.assertGreaterEqual(proof["object_track_pairs_with_embeddings"], 2)
        self.assertTrue(proof["full_two_cycle_boundary_observed"])
        self.assertGreaterEqual(proof["known_scene_bbox_matches"], 30)
        self.assertTrue(proof["distinct_track_ids_reassociated"])
        self.assertGreaterEqual(proof["positive_cosine_min"], 0.99)
        self.assertGreaterEqual(proof["bbox_iou_min"], 0.8)

    def test_exact_configuration_and_adjacent_negatives(self) -> None:
        config = self.receipt["configuration"]
        self.assertTrue(config["exact_radio_clip_bundle_selected"])
        self.assertTrue(config["legacy_256d_tracker_embedding_excluded"])
        negative = self.receipt["negative_preflight"]
        self.assertTrue(negative["mismatched_tokenizer_rejected"])
        self.assertTrue(negative["rejected_before_container_launch"])
        self.assertEqual(negative["incompatible_dimension_configured"], 1024)
        self.assertEqual(negative["observed_dimension"], 1536)
        self.assertTrue(negative["incompatible_dimension_rejected"])
        self.assertTrue(negative["rejected_before_capability_acceptance"])

    def test_lifecycle_cleanup_and_policy_are_fail_closed(self) -> None:
        lifecycle = self.receipt["lifecycle"]
        self.assertEqual(lifecycle["add"]["http_status"], 200)
        self.assertEqual(lifecycle["remove"]["http_status"], 200)
        self.assertEqual(lifecycle["final_stream_count"], 0)
        self.assertTrue(lifecycle["active_metrics"]["fps_positive"])
        self.assertTrue(lifecycle["active_metrics"]["frame_number_positive"])
        self.assertTrue(lifecycle["active_metrics"]["latency_finite"])
        cleanup = self.receipt["cleanup"]
        self.assertEqual(cleanup["failures"], [])
        self.assertTrue(cleanup["owned_containers_absent"])
        self.assertTrue(cleanup["owned_topic_absent"])
        self.assertTrue(cleanup["main_rt_cv_preserved_exactly"])
        self.assertEqual(cleanup["main_rt_cv_stream_count"], 0)
        self.assertTrue(cleanup["paused_workloads_preserved_exactly"])
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
            timeout=30,
        )
        plan = json.loads(result.stdout)
        self.assertEqual(plan["status"], "ready")
        self.assertEqual(plan["official_indices"], [377])
        self.assertTrue(plan["exact_radio_clip_bundle_present"])
        self.assertFalse(plan["writes_or_lifecycle_actions"])


if __name__ == "__main__":
    unittest.main()
