"""Small independent CPU checks for RLE, metrics, and oracle prompt semantics."""
import unittest

import numpy as np

from tools.segmentation.evaluate import decode_coco_rle, evaluate_mask, oracle_prompts_from_mask


class EvaluationTests(unittest.TestCase):
    def test_coco_column_major_and_compressed_runs(self):
        expected = np.array([[0, 1, 0], [1, 1, 0]], dtype=bool)
        for counts in ([1, 3, 2], "132"):
            np.testing.assert_array_equal(decode_coco_rle({"size": [2, 3], "counts": counts}), expected)

    def test_signed_delta_compressed_runs(self):
        # Encodes runs [0,2,3,1,5,1]: the fourth run's delta is -1 ('O').
        expected = np.array([1,1,0,0,0,1,0,0,0,0,0,1], dtype=bool).reshape((3,4), order="F")
        np.testing.assert_array_equal(decode_coco_rle({"size": [3,4], "counts": "023O20"}), expected)
        for counts in ("P", [-1, 13], [11], "zzzzzzzzzzzzzz"):
            with self.assertRaises(ValueError):
                decode_coco_rle({"size": [3,4], "counts": counts})

    def test_iou_and_empty_negative_are_explicit(self):
        gt = np.array([[1,1], [0,0]], dtype=bool)
        pred = np.array([[1,0], [1,0]], dtype=bool)
        result = evaluate_mask(pred, gt, prompt_source="moondream_predicted")
        self.assertAlmostEqual(result["iou"], 1/3)
        self.assertEqual(result["false_positive_pixels"], 1)
        self.assertEqual(result["false_negative_pixels"], 1)
        self.assertFalse(result["end_to_end_validated"])
        blank = np.zeros((2,2), dtype=bool)
        self.assertEqual(evaluate_mask(blank, blank, prompt_source="none")["iou"], 1)
        self.assertEqual(evaluate_mask(pred, blank, prompt_source="none")["negative_image_false_positive_fraction"], .5)

    def test_oracle_point_avoids_empty_bbox_center(self):
        mask = np.zeros((9,9), dtype=bool)
        mask[1:8,1:3] = True
        mask[1:3,1:8] = True
        prompts = oracle_prompts_from_mask(mask)
        positive, negative = prompts["positive_point_xy_pixels"], prompts["negative_point_xy_pixels"]
        self.assertTrue(mask[int(positive[1]),int(positive[0])])
        self.assertFalse(mask[int(negative[1]),int(negative[0])])
        self.assertEqual(prompts["box_xyxy_pixels"], [1,1,8,8])
        self.assertEqual(prompts["prompt_source"], "oracle_ground_truth")
        self.assertFalse(prompts["end_to_end"])

    def test_prompt_labels_and_shape_not_silently_repaired(self):
        mask = np.ones((2,2), dtype=bool)
        result = evaluate_mask(mask, mask, prompt_source="oracle_ground_truth",
            positive_points=[[.5,.5]], negative_points=[[1.5,1.5]])
        self.assertFalse(result["point_constraints_satisfied"])
        with self.assertRaises(ValueError):
            evaluate_mask(mask, np.ones((3,3)), prompt_source="none")
        with self.assertRaises(ValueError):
            evaluate_mask(mask, mask, prompt_source="automatic")
        self.assertIsNone(evaluate_mask(mask, prompt_source="manual")["iou"])


if __name__ == "__main__":
    unittest.main()
