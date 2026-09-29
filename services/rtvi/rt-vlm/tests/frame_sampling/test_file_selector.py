"""Exercise the real selector without importing CUDA/model dependencies."""
import ast
from collections import deque
import logging
from pathlib import Path
from types import SimpleNamespace
import unittest
from utils.frame_sampling import FrameTimestamp as F, SamplingUnavailable, select_frame_targets

source = Path(__file__).parents[2] / 'src/vlm_pipeline/video_file_frame_getter.py'
node = next(n for n in ast.parse(source.read_text()).body
            if isinstance(n, ast.ClassDef) and n.name == 'DefaultFrameSelector')
namespace = dict(deque=deque, ChunkInfo=object, logger=logging.getLogger('selector-test'),
                 SamplingUnavailable=SamplingUnavailable, select_frame_targets=select_frame_targets)
exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), namespace)
Selector = namespace['DefaultFrameSelector']


def chunk(start=0, end=50, offset=0):
    return SimpleNamespace(start_pts=start, end_pts=end, pts_offset_ns=offset, file='fixture.mp4')


class FileSelectorTests(unittest.TestCase):
    def test_native_targets_and_python_selection_agree(self):
        selector = Selector(10)
        selector.set_chunk(chunk())
        frames = [F(n+6, n) for n in range(50)]
        selector.set_file_timestamps(frames)
        native_targets = tuple(selector._selected_pts_array)
        python_targets = tuple(f.decoder_ns for f in frames if selector.choose_frame(None, f.decoder_ns))
        self.assertEqual(python_targets, native_targets)
        self.assertEqual(len(python_targets), 10)
        self.assertEqual(python_targets[-1]+selector._decoder_to_stream_offset_ns, 49)

    def test_seek_reset_restores_consumed_target(self):
        selector = Selector(5)
        selector.set_chunk(chunk(25, 50))
        selector.set_file_timestamps([F(n+2, n) for n in range(50)])
        original = tuple(selector._selected_pts_array)
        self.assertTrue(selector.choose_frame(None, original[0]))
        selector.reset_file_targets()
        self.assertEqual(tuple(selector._selected_pts_array), original)

    def test_reused_selector_clears_endpoint_mapping(self):
        selector = Selector(5)
        selector.set_chunk(chunk())
        selector.set_file_timestamps([F(n+6, n) for n in range(50)])
        selector.set_chunk(chunk(100,150))
        self.assertFalse(selector._endpoint_sampling)
        self.assertEqual(selector._decoder_to_stream_offset_ns, 0)
        self.assertEqual(tuple(selector._selected_pts_array), (100,110,120,130,140))

    def test_split_file_offset_and_half_open_boundary(self):
        selector = Selector(3)
        selector.set_chunk(chunk(125,150,100))
        selector.set_file_timestamps([F(n+6,n) for n in range(60)])
        result=[f.decoder_ns+selector._decoder_to_stream_offset_ns+100
                for f in [F(n+6,n) for n in range(60)] if selector.choose_frame(None,f.decoder_ns)]
        self.assertEqual(result[0],125)
        self.assertEqual(result[-1],149)
        self.assertEqual(len(result),3)

    def test_invalid_plan_does_not_partially_mutate_selector(self):
        selector=Selector(2)
        selector.set_chunk(chunk())
        original=tuple(selector._selected_pts_array)
        with self.assertRaises(SamplingUnavailable):
            selector.set_file_timestamps([F(0,0),F(3,2)])
        self.assertFalse(selector._endpoint_sampling)
        self.assertEqual(tuple(selector._selected_pts_array),original)

    def test_all_frames_mode_is_not_replanned(self):
        selector=Selector(-1)
        selector.set_chunk(chunk())
        selector.set_file_timestamps([])
        self.assertTrue(selector.selects_all_frames)
        self.assertTrue(selector.choose_frame(None,49))
