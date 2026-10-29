# SPDX-License-Identifier: Apache-2.0
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

folder = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(folder))
spec = importlib.util.spec_from_file_location('run_rfdetr_video_frames', folder / 'run_rfdetr_video_frames.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class DummyTensor:
    def numpy(self):
        return 'cpu-input'


class DummySession:
    def __init__(self):
        self.calls = []

    def run(self, outputs, inputs):
        self.calls.append((outputs, inputs))
        return ['boxes', 'logits']


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        (self.root / 'one.jpg').write_bytes(b'frame-one')
        (self.root / 'two.jpg').write_bytes(b'frame-two')
        self.doc = {'schemaVersion': 'city.video-frames.v1', 'frames': [
            {'image_id': 1, 'source_id': 'cam-a', 'frame_index': 0, 'timestamp_ns': 100,
             'fileName': 'one.jpg', 'width': 640, 'height': 360, 'sha256': hashlib.sha256(b'frame-one').hexdigest()},
            {'image_id': 2, 'source_id': 'cam-a', 'frame_index': 1, 'timestamp_ns': 200,
             'fileName': 'two.jpg', 'width': 640, 'height': 360, 'sha256': hashlib.sha256(b'frame-two').hexdigest()}]}
        self.path = self.root / 'manifest.json'
        self.write_manifest()

    def write_manifest(self):
        self.path.write_text(json.dumps(self.doc))

    def test_frame_hashes_and_manifest_identity_checked(self):
        result, ids, digest = m.load_frames(self.path)
        self.assertEqual(ids, {1, 2})
        self.assertEqual(len(digest), 64)
        self.assertEqual(result, self.doc)
        (self.root / 'one.jpg').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            m.load_frames(self.path)

    def test_traversal_duplicate_frame_and_dimensions_rejected(self):
        for key, value in [('fileName', '../outside.jpg'), ('image_id', 1), ('width', 0), ('sha256', 'wrong')]:
            with self.subTest(key=key):
                old = self.doc['frames'][1][key]
                self.doc['frames'][1][key] = value
                self.write_manifest()
                with self.assertRaises(ValueError):
                    m.load_frames(self.path)
                self.doc['frames'][1][key] = old

    def test_inference_covers_exact_inputs_and_production_query_policy(self):
        session = DummySession()
        sizes = []
        def preprocess(path, resolution, expected):
            sizes.append((path.name, resolution, expected))
            return DummyTensor()
        def decode(outputs, image_id, width, height, threshold):
            self.assertEqual(outputs, {'dets': 'boxes', 'labels': 'logits'})
            self.assertEqual(threshold, .35)
            return [
                {'image_id': image_id, 'category_id': 3, 'bbox': [0, 0, 10, 10], 'score': .8, 'queryIndex': 1},
                {'image_id': image_id, 'category_id': 6, 'bbox': [0, 0, 10, 10], 'score': .7, 'queryIndex': 1},
                {'image_id': image_id, 'category_id': 3, 'bbox': [0, 0, 10, 10], 'score': .6, 'queryIndex': 2}]
        processed, predictions = m.infer_frames(self.doc, self.root, session, 576, .35, preprocess=preprocess, decode=decode)
        self.assertEqual(processed, [1, 2])
        self.assertEqual([(p['image_id'], p['queryIndex']) for p in predictions], [(1, 1), (1, 2), (2, 1), (2, 2)])
        self.assertEqual([p['category_id'] for p in predictions], [3, 3, 3, 3])
        self.assertEqual(sizes, [('one.jpg', 576, (640, 360)), ('two.jpg', 576, (640, 360))])
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(session.calls[0], (['dets', 'labels'], {'input': 'cpu-input'}))

    def test_changed_frame_before_inference_fails_closed(self):
        (self.root / 'one.jpg').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'changed during'):
            m.infer_frames(self.doc, self.root, DummySession(), 576, .35)


if __name__ == '__main__':
    unittest.main()
