"""CPU-only orchestration tests: no models, downloads, Torch or GPU calls."""

import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from tools.segmentation.moondream_bridge import MoondreamBridge, _local_pointer
from tools.segmentation.adapter import Segmenter


BOX = {"x_min": 0.1, "y_min": 0.2, "x_max": 0.8, "y_max": 0.9}


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.memory_patch = patch("tools.segmentation.moondream_bridge._check_memory")
        self.memory_patch.start()
        self.addCleanup(self.memory_patch.stop)
        self.image = Image.new("RGB", (20, 10), "gray")
        self.client = Mock()
        self.client.detect.return_value = {"objects": [copy.deepcopy(BOX)]}
        self.client.point.return_value = {"points": [{"x": 0.25, "y": 0.75}]}
        self.client.query.return_value = {"answer": "Yes."}
        self.mask = np.zeros((10, 20), dtype=bool)
        self.mask[2:9, 2:16] = True
        self.segmenter = Mock()
        self.segmenter.receipt = {"name": "edgetam", "checkpoint_sha256": "test-only"}
        self.segmenter.set_image.return_value = {"encode_ms": 4.0}
        self.segmenter.predict.return_value = {
            "mask": self.mask, "score": 0.8, "decode_ms": 2.0,
            "score_kind": "uncalibrated_predicted_mask_iou"}
        self.client_loader = Mock(return_value=(self.client, {"runtime": "test-double"}))
        self.segmenter_loader = Mock(return_value=self.segmenter)

    def bridge(self, **kwargs):
        bridge = MoondreamBridge(_client_loader=self.client_loader,
                                 _segmenter_loader=self.segmenter_loader, **kwargs)
        self.addCleanup(bridge.close)
        return bridge

    def test_empty_detector_result_never_loads_or_calls_segmenter(self):
        self.client.detect.return_value = {"objects": []}
        result = self.bridge().segment(self.image, "missing aircraft")
        self.assertEqual(result["status"], "no_detections")
        self.assertEqual(result["raw_grounding"], {"objects": []})
        self.assertEqual(result["objects"], [])
        self.assertFalse(result["segmenter_used"])
        self.segmenter_loader.assert_not_called()
        self.client.query.assert_not_called()

    def test_real_grounding_is_preserved_and_normalized_box_is_not_rewritten(self):
        result = self.bridge().segment(self.image, "panel")
        self.client.detect.assert_called_once()
        self.assertEqual(self.client.detect.call_args.args[1], "panel")
        self.assertEqual(self.client.detect.call_args.kwargs["settings"], {"max_objects": 3})
        self.assertEqual(result["grounding_generation_limit"], 3)
        self.assertEqual(result["grounding_settings"], {"max_objects": 3})
        self.assertFalse(result["grounding_returned_at_limit"])
        self.assertEqual(result["grounded_by"], "detect")
        self.segmenter.predict.assert_called_once_with(
            box=[0.1, 0.2, 0.8, 0.9], multimask=False)
        self.assertEqual(result["raw_grounding"], {"objects": [BOX]})
        self.assertEqual(result["objects"][0]["grounding"], BOX)
        self.assertIs(result["objects"][0]["mask"], self.mask)
        self.assertGreater(result["timings_ms"]["total"], 0)
        self.assertEqual(result["image_encoding"]["encode_ms"], 4.0)
        self.client.detect.return_value["objects"][0]["x_min"] = 0.0
        self.assertEqual(result["raw_grounding"]["objects"][0]["x_min"], 0.1)

    def test_three_object_cap_keeps_raw_result_and_encodes_image_once(self):
        self.client.detect.return_value = {"objects": [copy.deepcopy(BOX) for _ in range(6)]}
        result = self.bridge().segment(self.image, "panel")
        self.assertEqual(len(result["objects"]), 3)
        self.assertEqual(len(result["raw_grounding"]["objects"]), 6)
        self.assertEqual(result["valid_grounding_count"], 6)
        self.assertTrue(result["truncated"])
        self.assertTrue(result["grounding_returned_at_limit"])
        self.segmenter.set_image.assert_called_once()
        self.assertEqual(self.segmenter.predict.call_count, 3)

    def test_invalid_boxes_are_rejected_without_clamping_or_masks(self):
        invalid = [
            {**BOX, "x_min": -0.01}, {**BOX, "x_max": float("nan")},
            {**BOX, "y_min": True}, {**BOX, "x_max": 0.05},
        ]
        self.client.detect.return_value = {"objects": invalid}
        result = self.bridge().segment(self.image, "panel")
        self.assertEqual(result["status"], "invalid_grounding")
        self.assertEqual(len(result["rejected_grounding"]), 4)
        self.assertEqual(result["objects"], [])
        self.segmenter_loader.assert_not_called()

    def test_presence_no_stops_before_detect_and_preserves_model_answer(self):
        self.client.query.return_value = {"answer": "NO"}
        result = self.bridge(presence_mode="query").segment(self.image, "aircraft")
        self.assertEqual(result["status"], "presence_rejected")
        self.assertIs(result["presence"]["decision"], False)
        self.assertEqual(result["presence"]["raw_response"], {"answer": "NO"})
        self.assertIn("aircraft", self.client.query.call_args.args[1])
        self.client.detect.assert_not_called()
        self.segmenter_loader.assert_not_called()

    def test_unrecognized_presence_never_becomes_yes_by_substring(self):
        for answer in ("yes, maybe", "not yes", "there is a panel", "", None):
            with self.subTest(answer=answer):
                self.client.query.return_value = {"answer": answer}
                result = self.bridge(presence_mode="query").segment(self.image, "panel")
                self.assertEqual(result["status"], "presence_unrecognized")
                self.assertIsNone(result["presence"]["decision"])
        self.client.detect.assert_not_called()
        self.segmenter_loader.assert_not_called()

    def test_presence_yes_runs_actual_detection_before_segmentation(self):
        result = self.bridge(presence_mode="query").segment(self.image, "panel")
        self.assertEqual(result["status"], "ok")
        self.assertIs(result["presence"]["decision"], True)
        self.client.query.assert_called_once()
        self.client.detect.assert_called_once()
        self.segmenter.predict.assert_called_once()

    def test_lazy_model_reuse_and_no_segmenter_for_describe_or_point(self):
        bridge = self.bridge(segmenter_name="sam2.1-tiny")
        self.client_loader.assert_not_called()
        self.client.query.return_value = {"answer": "A vehicle beside a building."}
        description = bridge.describe(self.image)
        points = bridge.point(np.asarray(self.image), "vehicle")
        self.assertEqual(description["description"], "A vehicle beside a building.")
        self.assertEqual(points["points"][0]["point"], [0.25, 0.75])
        self.client_loader.assert_called_once()
        self.segmenter_loader.assert_not_called()
        self.assertEqual(points["timings_ms"]["moondream_load"], 0)

    def test_spatial_generation_caps_are_forwarded_for_detect_and_point(self):
        bridge = self.bridge(max_objects=1)
        for kind in ("detect", "point"):
            with self.subTest(kind=kind):
                result = getattr(bridge, kind)(self.image, "plane in front")
                method = getattr(self.client, kind)
                self.assertEqual(method.call_args.kwargs["settings"], {"max_objects": 1})
                self.assertEqual(result["grounding_generation_limit"], 1)
                self.assertTrue(result["grounding_returned_at_limit"])

    def test_point_segmentation_uses_actual_point_and_own_score_selection(self):
        candidates = np.stack([np.zeros_like(self.mask), self.mask, np.ones_like(self.mask)])
        selected = Segmenter._result(candidates, [0.2, 0.9, 0.4], self.mask.shape, 2.0)
        self.segmenter.predict.return_value = selected
        result = self.bridge().segment(self.image, "plane in front", grounded_by="point")
        self.client.detect.assert_not_called()
        self.client.point.assert_called_once_with(
            self.image, "plane in front", settings={"max_objects": 3})
        self.segmenter.predict.assert_called_once_with(
            points=[[0.25, 0.75]], labels=[1], multimask=True)
        self.assertEqual(result["grounded_by"], "point")
        self.assertEqual(result["raw_grounding"], {"points": [{"x": 0.25, "y": 0.75}]})
        item = result["objects"][0]
        self.assertEqual(item["point"], [0.25, 0.75])
        self.assertNotIn("box", item)
        self.assertEqual(item["mask_metadata"]["selected_candidate"], 1)
        self.assertEqual(item["mask_metadata"]["candidate_count"], 3)
        np.testing.assert_array_equal(item["mask"], self.mask)

    def test_empty_or_invalid_points_never_invoke_segmenter(self):
        for points, status in (([], "no_detections"),
                               ([{"x": 0.4, "y": 1.1}], "invalid_grounding")):
            with self.subTest(points=points):
                self.client.point.return_value = {"points": points}
                result = self.bridge().segment(self.image, "panel", grounded_by="point")
                self.assertEqual(result["status"], status)
                self.assertEqual(result["objects"], [])
        self.segmenter_loader.assert_not_called()

    def test_unknown_grounding_mode_fails_before_model_load(self):
        with self.assertRaisesRegex(ValueError, "grounded_by"):
            self.bridge().segment(self.image, "panel", grounded_by="auto")
        self.client_loader.assert_not_called()

    def test_selected_segmenter_is_loaded_lazily_and_reused(self):
        bridge = self.bridge(segmenter_name="sam2.1-tiny")
        bridge.segment(self.image, "panel")
        second = bridge.segment(self.image, "panel")
        self.segmenter_loader.assert_called_once_with("sam2.1-tiny", device="cuda", state_dir=None)
        self.assertEqual(second["timings_ms"]["segmenter_load"], 0)
        self.assertEqual(self.segmenter.set_image.call_count, 2)

    def test_malformed_model_output_raises_before_mask_generation(self):
        self.client.detect.return_value = {"objects": "not a list"}
        with self.assertRaisesRegex(RuntimeError, "objects list"):
            self.bridge().segment(self.image, "panel")
        self.segmenter_loader.assert_not_called()

    def test_closed_bridge_does_not_reload(self):
        bridge = self.bridge()
        bridge.detect(self.image, "panel")
        bridge.close()
        bridge.close()
        self.client.close.assert_called_once()
        with self.assertRaisesRegex(RuntimeError, "closed"):
            bridge.detect(self.image, "panel")
        self.client_loader.assert_called_once()

    def test_invalid_configuration_and_moondream3_opt_in(self):
        for kwargs in ({"max_objects": 4}, {"max_objects": True},
                       {"presence_mode": "auto"}, {"segmenter_name": "unknown"},
                       {"model": "moondream3-preview"},
                       {"model": "moondream3.1-9B-A2B"}, {"gb10_compat": True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.bridge(**kwargs)
        for model in ("moondream3-preview", "moondream3.1-9B-A2B"):
            with self.subTest(model=model):
                bridge = self.bridge(model=model, gb10_compat=True)
                bridge.detect(self.image, "panel")
                self.assertTrue(self.client_loader.call_args.kwargs["gb10_compat"])
                self.assertEqual(self.client_loader.call_args.kwargs["model"], model)

    def test_checkpoint_pointer_preserves_snapshot_extension(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            blob = root / "extensionless-blob"
            blob.write_bytes(b"checkpoint test fixture")
            snapshot = root / "snapshot"
            snapshot.mkdir()
            for filename in ("model.safetensors", "model_fp8.pt"):
                with self.subTest(filename=filename):
                    checkpoint = snapshot / filename
                    checkpoint.symlink_to(blob)
                    pointer = root / "pointer.txt"
                    pointer.write_text(str(checkpoint.relative_to(root)))
                    result = _local_pointer(root, pointer.name)
                    self.assertEqual(result, str(checkpoint))
                    self.assertEqual(Path(result).suffix, checkpoint.suffix)
                    self.assertTrue(Path(result).is_file())

    def test_oversized_image_is_rejected_before_model_load(self):
        oversized = np.broadcast_to(np.zeros((1, 1, 3), dtype=np.uint8), (4001, 4000, 3))
        with self.assertRaisesRegex(ValueError, "16 megapixels"):
            self.bridge().segment(oversized, "panel")
        self.client_loader.assert_not_called()


if __name__ == "__main__":
    unittest.main()
