"""Run directly with Python; no CUDA, torch, or vendor dependencies required."""

import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch


SOURCE = Path(__file__).resolve().parents[3] / "src/models/vllm_compatible/model_file_cache.py"
SPEC = importlib.util.spec_from_file_location("model_file_cache", SOURCE)
cache = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cache)


class ModelFileCacheTests(unittest.TestCase):
    def test_default_off_never_accesses_checkpoint(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(cache.Path, "resolve") as resolve:
            self.assertIsNone(cache.reclaim_loaded_model_file_cache("/does/not/exist"))
            resolve.assert_not_called()

    def test_opt_in_requires_explicit_root_and_active_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "candidate-cache"
            root.mkdir()
            outside = Path(temp) / "other-model"
            outside.mkdir()
            with patch.dict(os.environ, {"VLM_RECLAIM_MODEL_FILE_CACHE": "true"}, clear=True):
                with self.assertRaisesRegex(ValueError, "required"):
                    cache.reclaim_loaded_model_file_cache(root)
                os.environ["VLM_FILE_CACHE_RECLAIM_ROOT"] = str(root)
                for invalid in (root, outside):
                    with self.subTest(checkpoint=invalid), self.assertRaisesRegex(ValueError, "inside"):
                        cache.reclaim_loaded_model_file_cache(invalid)

    def test_advice_retains_files_and_excludes_other_models_and_escaping_symlinks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "candidate-cache"
            active = root / "cosmos"
            other = root / "other-model"
            active.mkdir(parents=True)
            other.mkdir()
            weights = active / "model-00001.safetensors"
            contents = b"checkpoint contents" * 1000
            weights.write_bytes(contents)
            outside = other / "other.safetensors"
            outside.write_bytes(b"other model")
            (active / "escape.safetensors").symlink_to(outside)
            (active / "alias.safetensors").symlink_to(weights)
            os.link(weights, active / "hardlink.safetensors")
            config = active / "config.json"
            config.write_text("{}")
            advised_inodes = []
            real_advice = os.posix_fadvise

            def advise(fd, offset, length, advice):
                advised_inodes.append((os.fstat(fd).st_dev, os.fstat(fd).st_ino))
                real_advice(fd, offset, length, advice)

            logger = Mock()
            with patch.dict(os.environ, {
                "VLM_RECLAIM_MODEL_FILE_CACHE": "true",
                "VLM_FILE_CACHE_RECLAIM_ROOT": str(root),
            }, clear=True), patch.object(os, "posix_fadvise", side_effect=advise):
                report = cache.reclaim_loaded_model_file_cache(active, logger)

            self.assertEqual(advised_inodes, [(weights.stat().st_dev, weights.stat().st_ino)])
            self.assertEqual(report["advised_files"], 1)
            self.assertEqual(report["advised_bytes"], len(contents))
            self.assertEqual(report["skipped_files"], 3)
            self.assertEqual(report["errors"], 0)
            self.assertEqual(weights.read_bytes(), contents)
            self.assertEqual(outside.read_bytes(), b"other model")
            self.assertEqual(config.read_text(), "{}")
            self.assertTrue((active / "escape.safetensors").is_symlink())
            logger.info.assert_called_once()

    def test_advice_failure_is_reported_without_removing_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            active = root / "cosmos"
            active.mkdir()
            weights = active / "model.safetensors"
            weights.write_bytes(b"weights")
            logger = Mock()
            with patch.dict(os.environ, {
                "VLM_RECLAIM_MODEL_FILE_CACHE": "true",
                "VLM_FILE_CACHE_RECLAIM_ROOT": str(root),
            }, clear=True), patch.object(os, "posix_fadvise", side_effect=OSError("advice failed")):
                report = cache.reclaim_loaded_model_file_cache(active, logger)
            self.assertEqual(report["errors"], 1)
            self.assertEqual(report["advised_files"], 0)
            self.assertEqual(weights.read_bytes(), b"weights")
            logger.warning.assert_called_once()


if __name__ == "__main__":
    unittest.main()
