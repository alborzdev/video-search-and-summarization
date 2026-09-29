import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

PATH = Path(__file__).resolve().parents[2] / 'src/utils/input_capture.py'
spec = importlib.util.spec_from_file_location('capture', PATH)
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)


class CaptureTests(unittest.TestCase):
    def test_disabled_does_not_touch_disk(self):
        with patch.object(capture.Path, 'mkdir', side_effect=AssertionError('disk touched')):
            self.assertIsNone(capture.capture_input('', 'one', np.zeros((1,2,2,3), dtype=np.uint8), {}))

    def test_lossless_input_metadata_and_linked_response(self):
        with tempfile.TemporaryDirectory() as root:
            frames = np.arange(48, dtype=np.uint8).reshape(4,2,2,3)
            original = frames.copy()
            target = capture.capture_input(root, 'one', frames, {'frame_times':[0,2.5,5,7.5], 'sampling':{'seed':42}})
            np.testing.assert_array_equal(np.load(target/'frames.npy', allow_pickle=False), original)
            np.testing.assert_array_equal(frames, original)
            metadata = json.loads((target/'input.json').read_text())
            self.assertEqual(metadata['sampling']['seed'],42)
            self.assertEqual(metadata['shape'],[4,2,2,3])
            self.assertEqual(metadata['pixels_sha256'],capture.hashlib.sha256(original.tobytes()).hexdigest())
            capture.capture_response(target, {'request_id':'one','outputs':['YES']})
            self.assertEqual(json.loads((target/'response.json').read_text())['outputs'],['YES'])
            with self.assertRaises(FileExistsError):
                capture.capture_input(root, 'one', frames, {})

    def test_request_and_byte_budgets(self):
        frames = np.zeros((1,2,2,3),dtype=np.uint8)
        with tempfile.TemporaryDirectory() as root, patch.object(capture,'MAX_REQUESTS',1):
            self.assertIsNotNone(capture.capture_input(root,'one',frames,{}))
            self.assertIsNone(capture.capture_input(root,'two',frames,{}))
        with tempfile.TemporaryDirectory() as root, patch.object(capture,'MAX_TOTAL_BYTES',32):
            self.assertIsNone(capture.capture_input(root,'one',frames,{}))
        with tempfile.TemporaryDirectory() as root, patch.object(capture,'MAX_ARRAY_BYTES',1):
            self.assertIsNone(capture.capture_input(root,'one',frames,{}))

    def test_rejects_unsupported_frames_and_unsafe_names(self):
        with tempfile.TemporaryDirectory() as root:
            frames=np.zeros((1,2,2,3),dtype=np.uint8)
            with self.assertRaises(ValueError):capture.capture_input(root,'../escape',frames,{})
            self.assertIsNone(capture.capture_input(root,'float',frames.astype(float),{}))
            self.assertIsNone(capture.capture_input(root,'strided',frames[:,:,::2,:],{}))
            self.assertEqual(list(Path(root).iterdir()),[])

    def test_time_limit_persists_between_calls(self):
        with tempfile.TemporaryDirectory() as root:
            frames=np.zeros((1,2,2,3),dtype=np.uint8)
            with patch.object(capture.time,'time',return_value=1000):
                self.assertIsNotNone(capture.capture_input(root,'one',frames,{}))
            with patch.object(capture.time,'time',return_value=1120):
                self.assertIsNone(capture.capture_input(root,'two',frames,{}))
            self.assertEqual(len(list(Path(root).glob('*/frames.npy'))),1)

    def test_json_limits(self):
        with tempfile.TemporaryDirectory() as root:
            frames=np.zeros((1,2,2,3),dtype=np.uint8)
            target=capture.capture_input(root,'one',frames,{})
            with patch.object(capture,'MAX_JSON_BYTES',10):
                self.assertIsNone(capture.capture_input(root,'two',frames,{'too_long':'x'*11}))
                capture.capture_response(target,{'output':'x'*11})
            self.assertFalse((target/'response.json').exists())


if __name__ == '__main__':unittest.main()
