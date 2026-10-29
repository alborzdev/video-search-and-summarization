# SPDX-License-Identifier: Apache-2.0
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

path = Path(__file__).resolve().parents[1] / 'compare_detector_predictions.py'
spec = importlib.util.spec_from_file_location('compare_detector_predictions', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

GT = {'images': [{'id': 1, 'width': 100, 'height': 100}, {'id': 2, 'width': 100, 'height': 100}],
      'categories': [{'id': 1, 'name': 'person'}, {'id': 3, 'name': 'car'}, {'id': 6, 'name': 'bus'}],
      'annotations': [{'id': 1, 'image_id': 1, 'category_id': 1, 'bbox': [10, 10, 20, 20],
                       'area': 400, 'iscrowd': 0}]}


def prediction(image=1, category=1, box=(10, 10, 20, 20), score=.9):
    return {'image_id': image, 'category_id': category, 'bbox': list(box), 'score': score}


class ComparisonTests(unittest.TestCase):
    def test_validation_rejects_unsupported_or_unknown_and_invalid(self):
        for pred in [prediction(category=6), prediction(image=3), prediction(box=(1, 1, 0, 1)),
                     prediction(score=float('nan'))]:
            with self.subTest(pred=pred), self.assertRaises(ValueError):
                module.validate(GT, [pred], {1, 3}, [1, 2])
        module.validate(GT, [], {1, 3}, [1, 2])

    def test_agreement_uses_common_class_same_frame_and_one_to_one(self):
        a = [prediction(), prediction(), prediction(image=2), prediction(category=6)]
        b = [prediction(), prediction(image=2, category=3), prediction(score=.1)]
        result = module.agreement(a, b, [1, 2], [1, 3], .3, .5)
        self.assertEqual(result['totals'], {'matched': 1, 'onlyA': 2, 'onlyB': 1})
        self.assertEqual(result['perCategory']['1'], {'matched': 1, 'onlyA': 2, 'onlyB': 0})
        self.assertEqual(result['perImage']['1'], {'matched': 1, 'onlyA': 1, 'onlyB': 0})
        self.assertEqual(result['perImage']['2'], {'matched': 0, 'onlyA': 1, 'onlyB': 1})
        self.assertIn('not precision', result['scope'])

    def test_iou_threshold_and_different_labels(self):
        result = module.agreement([prediction()], [prediction(box=(100, 100, 10, 10)), prediction(category=3)],
                                  [1], [1, 3], .3, .5)
        self.assertEqual(result['totals'], {'matched': 0, 'onlyA': 1, 'onlyB': 2})

    def test_real_coco_perfect_wrong_and_empty(self):
        try:
            import pycocotools  # noqa: F401
        except ImportError:
            self.skipTest('pycocotools unavailable')
        with tempfile.TemporaryDirectory() as directory:
            gt = Path(directory) / 'gt.json'
            gt.write_text(json.dumps(GT))
            perfect = module.coco_score(gt, [prediction()], [1, 2], [1, 3])
            wrong = module.coco_score(gt, [prediction(box=(60, 60, 20, 20))], [1, 2], [1, 3])
            empty = module.coco_score(gt, [], [1, 2], [1])
            self.assertAlmostEqual(perfect['AP50_95'], 1)
            self.assertIsNone(perfect['perCategoryAP50_95']['3'])
            self.assertEqual(wrong['AP50_95'], 0)
            self.assertEqual(empty['AP50_95'], 0)
            self.assertIsNone(module.coco_score(gt, [], [1], []))


if __name__ == '__main__':
    unittest.main()
