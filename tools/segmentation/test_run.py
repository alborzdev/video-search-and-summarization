"""CLI orchestration and artifact tests, using only CPU and explicit fakes."""

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from tools.segmentation import run


class LocalCLITests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.image = Image.new("RGB", (20, 10), "gray")
        self.input = self.root / "input.png"
        self.image.save(self.input)

    def test_saved_reserve_and_startup_admission(self):
        settings = self.root / "settings.json"
        for value in (0, True, float("nan")):
            settings.write_text(json.dumps({"reserve_gib": value}))
            with self.assertRaises(RuntimeError):
                run.saved_reserve(settings)
        settings.write_text('{"reserve_gib": 28}')
        self.assertEqual(run.saved_reserve(settings), 28)
        with patch.object(run, "saved_reserve", return_value=28), patch.object(run, "guard_active", return_value=True), patch.object(run, "available_gib", return_value=27.9):
            with self.assertRaisesRegex(RuntimeError, "28 GiB"):
                run.admission()
        with patch.object(run, "saved_reserve", return_value=20), patch.object(run, "guard_active", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "guard"):
                run.admission()

    def test_existing_artifacts_are_not_overwritten(self):
        directory = self.root / "outputs"
        run.claim_output(directory)
        original = (directory / ".run-lock").read_bytes()
        with self.assertRaisesRegex(ValueError, "not empty"):
            run.claim_output(directory)
        self.assertEqual((directory / ".run-lock").read_bytes(), original)

    def test_masks_raw_grounding_and_receipts_are_preserved(self):
        mask = np.zeros((10, 20), dtype=bool)
        mask[2:8, 3:14] = True
        raw = {"objects": [{"x_min": .15, "y_min": .2, "x_max": .7, "y_max": .8}]}
        result = {"operation": "segment", "status": "ok", "raw_grounding": raw,
                  "moondream_receipt": {"model_path": "/actual/model"},
                  "segmenter_receipt": {"checkpoint_sha256": "actual-hash"},
                  "objects": [{"box": [.15, .2, .7, .8], "mask": mask,
                               "mask_metadata": {"score": .7}}]}
        saved = run.save_result(self.image, result, self.root / "call")
        decoded = json.loads((self.root / "call/result.json").read_text())
        self.assertEqual(decoded["raw_grounding"], raw)
        self.assertEqual(decoded["segmenter_receipt"], result["segmenter_receipt"])
        self.assertNotIn("mask", decoded["objects"][0])
        np.testing.assert_array_equal(np.asarray(Image.open(saved["objects"][0]["mask_artifact"]["path"])) > 0, mask)
        self.assertIs(result["objects"][0]["mask"], mask)
        self.assertFalse(saved["accuracy_evaluated"])

    def test_absence_generates_no_fake_mask_and_keeps_original_overlay(self):
        result = {"operation": "segment", "status": "no_detections", "raw_grounding": {"objects": []}, "objects": []}
        saved = run.save_result(self.image, result, self.root / "none")
        self.assertEqual(saved["artifacts"]["mask_count"], 0)
        self.assertEqual(list((self.root / "none").glob("mask-*.png")), [])
        np.testing.assert_array_equal(np.asarray(Image.open(saved["artifacts"]["overlay"])), np.asarray(self.image))

    def test_repeated_calls_reuse_one_bridge_and_keep_load_time_separate(self):
        config = {"image": str(self.input), "model": "moondream2", "segmenter": "edgetam", "presence": "off",
                  "max_objects": 3, "gb10_compat": False, "repeat": 2, "task": "detect", "object": "box"}
        bridge = Mock()
        bridge.__enter__ = Mock(return_value=bridge)
        bridge.__exit__ = Mock(return_value=False)
        bridge.detect.side_effect = [
            {"operation": "detect", "status": "no_detections", "objects": [],
             "raw_grounding": {"objects": []}, "timings_ms": {"moondream_load": load, "segmenter_load": 0, "total": load + 5}}
            for load in (100, 0)]
        factory = Mock(return_value=bridge)
        with contextlib.redirect_stdout(io.StringIO()):
            summary = run.run_worker(config, self.root, factory)
        factory.assert_called_once()
        self.assertEqual(bridge.detect.call_count, 2)
        self.assertEqual([r["process_phase"] for r in summary["calls"]], ["first_call", "resident_reuse"])
        self.assertEqual([r["model_load_ms"] for r in summary["calls"]], [100, 0])
        self.assertEqual([r["call_excluding_model_load_ms"] for r in summary["calls"]], [5, 5])

    def test_point_segmentation_forwards_real_grounding_mode(self):
        config = {"image": str(self.input), "model": "moondream3.1-9B-A2B", "segmenter": "sam2.1-tiny", "presence": "off",
                  "max_objects": 1, "gb10_compat": True, "repeat": 1, "task": "segment", "object": "cat", "grounded_by": "point"}
        bridge = Mock()
        bridge.__enter__ = Mock(return_value=bridge)
        bridge.__exit__ = Mock(return_value=False)
        bridge.segment.return_value = {"operation": "segment", "status": "ok",
            "raw_grounding": {"points": [{"x": .5, "y": .5}]},
            "objects": [{"point": [.5, .5], "mask": np.ones((10, 20), dtype=bool)}],
            "timings_ms": {"moondream_load": 1, "segmenter_load": 1, "total": 3}}
        factory = Mock(return_value=bridge)
        with contextlib.redirect_stdout(io.StringIO()):
            run.run_worker(config, self.root, factory)
        self.assertEqual(bridge.segment.call_args.kwargs, {"grounded_by": "point"})
        self.assertEqual(factory.call_args.kwargs["model"], "moondream3.1-9B-A2B")
        result = json.loads((self.root / "call-000/result.json").read_text())
        self.assertEqual(result["objects"][0]["point"], [.5, .5])
        self.assertNotEqual(Image.open(result["artifacts"]["grounding_overlay"]).tobytes(), self.image.tobytes())

    def test_model_opt_in_and_cli_defaults(self):
        args = run.parse_args(["--image", str(self.input), "--object", "cat", "--output-dir", str(self.root / "next")])
        self.assertEqual(args.segmenter, "sam2.1-tiny")
        self.assertEqual(args.grounded_by, "point")
        direct_point = run.parse_args(["--task", "point", "--image", str(self.input), "--object", "cat", "--output-dir", str(self.root / "point")])
        self.assertEqual(direct_point.task, "point")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            run.parse_args(["--image", str(self.input), "--object", "cat", "--output-dir", str(self.root / "next"), "--model", "moondream3.1-9B-A2B"])

    def test_memory_threshold_terminates_only_owned_child_and_saves_receipt(self):
        config = {"image": str(self.input), "output_dir": str(self.root / "guarded"), "timeout": 30}
        process = Mock()
        process.returncode = None
        process.poll.return_value = None
        def terminate(owned):
            self.assertIs(owned, process)
            process.returncode = -15
        process.wait.return_value = -15
        with patch.object(run, "admission", return_value=20), patch.object(run, "saved_reserve", return_value=28), patch.object(run, "available_gib", return_value=30), patch.object(run.subprocess, "Popen", return_value=process), patch.object(run, "terminate_child", side_effect=terminate), contextlib.redirect_stdout(io.StringIO()):
            code = run.supervise(config)
        receipt = json.loads((self.root / "guarded/exit.json").read_text())
        self.assertEqual(code, 1)
        self.assertEqual(receipt["stop_reason"], "reserve_headroom")
        self.assertEqual(receipt["reserve_gib"], 28)

    def test_hidden_child_cannot_be_called_without_supervisor(self):
        with patch.dict(run.os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "active supervisor"):
                run.main(["--_child"])

    def test_nonfinite_rejected_coordinate_is_explicit_valid_json(self):
        path = self.root / "invalid.json"
        run.write_json(path, {"raw_grounding": {"x_min": float("nan")}})
        self.assertEqual(json.loads(path.read_text())["raw_grounding"]["x_min"], {"nonfinite_float": "nan"})


if __name__ == "__main__":
    unittest.main()
