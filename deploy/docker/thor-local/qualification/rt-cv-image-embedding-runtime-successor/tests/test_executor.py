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


class RtCvImageEmbeddingRuntimeQualificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = json.loads((PACKAGE / "contract.json").read_text())
        cls.schema = json.loads((PACKAGE / "receipt.schema.json").read_text())
        cls.receipt = json.loads((PACKAGE / "runtime-receipt.json").read_text())

    def test_receipt_validates_strict_schema(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        Draft202012Validator(self.schema).validate(self.receipt)

    def test_contract_and_receipt_bind_exact_row(self) -> None:
        expected = ["manifest-entry.rt-cv-2d.04-on-demand-image-embedding"]
        self.assertEqual(self.contract["official_indices"], [379])
        self.assertEqual(self.contract["capability_ids"], expected)
        self.assertEqual(self.receipt["official_indices"], [379])
        self.assertEqual(self.receipt["capability_ids"], expected)
        self.assertEqual(self.receipt["status"], "passed")
        self.assertEqual(self.receipt["contract_sha256"], sha(PACKAGE / "contract.json"))

    def test_every_source_and_model_lock_matches(self) -> None:
        for lock in self.contract["source_locks"]:
            path = REPO / lock["path"]
            self.assertTrue(path.is_file(), lock["path"])
            self.assertFalse(path.is_symlink(), lock["path"])
            self.assertEqual(sha(path), lock["sha256"], lock["path"])
        for asset in self.contract["assets"].values():
            path = REPO / asset["path"]
            self.assertEqual(path.stat().st_size, asset["bytes"], asset["path"])
            self.assertEqual(sha(path), asset["sha256"], asset["path"])

    def test_runtime_evidence_is_substantive_and_independent(self) -> None:
        evidence = self.receipt["on_demand_image_embedding"]
        self.assertEqual(evidence["active_streams_before"], 0)
        self.assertEqual(evidence["active_streams_after"], 0)
        self.assertTrue(evidence["independent_of_continuous_streaming"])
        self.assertTrue(evidence["same_image_vector_exact"])
        self.assertTrue(evidence["different_image_vector_distinct"])
        self.assertLess(evidence["different_image_cosine"], 0.99)
        for key in ("primary_first", "primary_repeat", "contrast"):
            proof = evidence[key]
            self.assertEqual(proof["http_status"], 200)
            self.assertEqual(proof["dimension"], 1152)
            self.assertTrue(proof["finite"])
            self.assertTrue(proof["nonzero"])
            self.assertGreater(proof["l2_norm"], 0)
        self.assertNotEqual(
            evidence["primary_first"]["vector_sha256"],
            evidence["contrast"]["vector_sha256"],
        )

    def test_format_and_negative_path_are_explicit(self) -> None:
        self.assertEqual(self.receipt["fixtures"]["format"], "P6_PPM")
        self.assertTrue(self.receipt["fixtures"]["different_content"])
        negative = self.receipt["negative_path_validation"]
        self.assertEqual(negative["http_status"], 500)
        self.assertTrue(negative["error_exact"])
        self.assertTrue(negative["no_embedding_returned"])

    def test_policy_and_cleanup_are_fail_closed(self) -> None:
        cleanup = self.receipt["cleanup"]
        self.assertEqual(cleanup["cleanup_failures"], [])
        for key, value in cleanup.items():
            if key not in ("cleanup_failures", "main_rt_cv_stream_count"):
                self.assertTrue(value, key)
        self.assertEqual(cleanup["main_rt_cv_stream_count"], 0)
        policy = self.receipt["policy"]
        self.assertEqual(policy["agent_generate_calls"], 0)
        self.assertEqual(policy["main_rt_cv_stream_mutations"], 0)
        self.assertEqual(policy["main_vios_stream_mutations"], 0)
        self.assertEqual(policy["network_downloads"], 0)
        self.assertEqual(policy["warehouse_sample_bundle"], "excluded")
        for key in (
            "raw_request_ids_retained",
            "raw_image_paths_retained",
            "raw_embeddings_retained",
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
        self.assertEqual(plan["official_indices"], [379])
        self.assertTrue(plan["cached_assets_exact"])
        self.assertTrue(plan["owned_container_absent"])
        self.assertFalse(plan["writes_or_lifecycle_actions"])


if __name__ == "__main__":
    unittest.main()
