"""Run with PYTHONPATH=src python3 -m unittest discover -s tests/frame_sampling."""
import unittest
from utils.frame_sampling import FrameTimestamp as F, SamplingUnavailable, select_frame_targets


class SamplingTests(unittest.TestCase):
    def test_cfr_keeps_last_within_budget(self):
        frames = [F(n, n) for n in range(50)]
        selected = select_frame_targets(frames, 0, 50, 10)
        self.assertEqual(len(selected), 10)
        self.assertEqual((selected[0], selected[-1]), (frames[0], frames[-1]))

    def test_vfr_and_reordered_packets(self):
        frames = [F(n + 6, n) for n in (49, 0, 3, 9, 21, 27, 48)]
        selected = select_frame_targets(frames, 0, 50, 4)
        self.assertEqual(selected[-1], F(55, 49))
        self.assertLessEqual(len(selected), 4)
        self.assertEqual(list(selected), sorted(selected, key=lambda f: f.stream_ns))

    def test_half_open_chunk_and_offset(self):
        selected = select_frame_targets([F(n + 2, n + 20) for n in range(50)], 45, 60, 3)
        self.assertEqual(selected[0], F(27, 45))
        self.assertEqual(selected[-1], F(41, 59))

    def test_one_frame_budget_selects_endpoint(self):
        self.assertEqual(select_frame_targets([F(0, 0), F(9, 9)], 0, 10, 1), (F(9, 9),))

    def test_single_frame_clip(self):
        self.assertEqual(select_frame_targets([F(0, 0)], 0, 1, 10), (F(0, 0),))

    def test_sparse_frames_are_not_duplicated(self):
        selected = select_frame_targets([F(0, 0), F(9, 9), F(9, 9)], 0, 10, 10)
        self.assertEqual(selected, (F(0, 0), F(9, 9)))

    def test_bad_intervals_and_counts(self):
        for start, end, count in ((0, 0, 2), (2, 1, 2), (0, 1, 0)):
            with self.assertRaises(SamplingUnavailable):
                select_frame_targets([F(0, 0)], start, end, count)

    def test_empty_interval(self):
        with self.assertRaises(SamplingUnavailable):
            select_frame_targets([F(0, 0)], 1, 2, 2)

    def test_ambiguous_or_discontinuous_coordinates(self):
        for frames in ([F(0, 0), F(1, 0)], [F(5, 0), F(1, 1)]):
            with self.assertRaises(SamplingUnavailable):
                select_frame_targets(frames, 0, 2, 2)
