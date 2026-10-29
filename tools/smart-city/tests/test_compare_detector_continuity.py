# SPDX-License-Identifier: Apache-2.0
import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[1] / 'compare_detector_continuity.py'
spec = importlib.util.spec_from_file_location('compare_detector_continuity', path)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def frame(image, source, index):
    return {'image_id': image, 'source_id': source, 'frame_index': index, 'timestamp_ns': index * 100_000_000}


def pred(image, category=1, bbox=(0, 0, 10, 10)):
    return {'image_id': image, 'category_id': category, 'bbox': list(bbox), 'score': .9}


class ContinuityTests(unittest.TestCase):
    def setUp(self):
        self.manifest = {'frames': [frame(1, 'a', 0), frame(2, 'a', 1), frame(3, 'a', 2),
                                    frame(4, 'b', 0), frame(5, 'b', 1)]}
        self.ids, self.sources = m.validate_manifest(self.manifest)

    def test_all_frames_explicitly_processed_and_unsupported_class_rejected(self):
        for coverage in ([1, 2, 3, 4], [1, 2, 3, 4, 5, 5]):
            with self.assertRaises(ValueError):
                m.validate_predictions({'processed_image_ids': coverage, 'predictions': []}, self.ids, {1})
        with self.assertRaises(ValueError):
            m.validate_predictions({'processed_image_ids': list(self.ids), 'predictions': [pred(1, 3)]}, self.ids, {1})
        m.validate_predictions({'processed_image_ids': list(self.ids), 'predictions': []}, self.ids, {1})

    def test_frame_omissions_and_clock_rollback_rejected(self):
        for rows in ([frame(1, 'a', 0), frame(2, 'a', 2)],
                     [frame(1, 'a', 1), frame(2, 'a', 1)],
                     [frame(1, 'a', 0), {**frame(2, 'a', 1), 'timestamp_ns': 0}]):
            with self.assertRaises(ValueError):
                m.validate_manifest({'frames': rows})

    def test_gap_and_separate_sources(self):
        output = m.track(self.sources, [pred(1), pred(3), pred(4), pred(5)], {1}, .3, .5, 1)
        a = output['a']['perCategory']['1']; b = output['b']['perCategory']['1']
        self.assertEqual((a['tracks'], a['observations'], a['missedFramesInsideTracks'], a['gapReacquisitions']), (1, 2, 1, 1))
        self.assertEqual((b['tracks'], b['observations'], b['gapReacquisitions']), (1, 2, 0))
        self.assertEqual(a['medianObservedDurationSeconds'], .2)
        no_gap = m.track(self.sources, [pred(1), pred(3)], {1}, .3, .5, 0)
        self.assertEqual(no_gap['a']['perCategory']['1']['tracks'], 2)

    def test_one_to_one_matching_and_class_isolation(self):
        output = m.track(self.sources, [pred(1), pred(2), pred(2), pred(3, 3)], {1, 3}, .3, .5, 0)['a']
        self.assertEqual(output['perCategory']['1']['tracks'], 2)
        self.assertEqual(output['perCategory']['3']['tracks'], 1)
        assigned = [a['trackId'] for a in output['assignments'] if a['imageId'] == 2]
        self.assertEqual(len(set(assigned)), 2)
        self.assertTrue(all(t['observations'] <= 2 for t in output['tracks']))

    def test_nonfinite_and_invalid_boxes_rejected(self):
        for item in [pred(1, bbox=(0, 0, 0, 1)), {**pred(1), 'score': float('nan')}]:
            with self.assertRaises(ValueError):
                m.validate_predictions({'processed_image_ids': list(self.ids), 'predictions': [item]}, self.ids, {1})


if __name__ == '__main__':
    unittest.main()
