"""CPU-only SVG rendering checks against existing system librsvg."""
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from mask_artifacts import rasterize_mask, save_mask_artifacts


class MaskArtifactTests(unittest.TestCase):
    def setUp(self):
        self.bbox = dict(x_min=.25, y_min=.2, x_max=.75, y_max=.8)
        self.full_bbox = dict(x_min=0, y_min=0, x_max=1, y_max=1)
        self.rectangle = 'M 0 0 L 1 0 L 1 1 L 0 1 Z'

    def test_bbox_relative_rectangle_has_correct_position_and_area(self):
        mask, _ = rasterize_mask(self.rectangle, self.bbox, (200, 100))
        self.assertEqual(mask.getbbox(), (50, 20, 150, 80))
        self.assertEqual(mask.histogram()[255], 6000)

    def test_curves_render_as_curves_not_a_box(self):
        path = 'M0 0 C1 0 1 1 0 1 Z'
        mask, _ = rasterize_mask(path, self.bbox, (200, 100))
        self.assertEqual(mask.getpixel((140, 50)), 0)
        self.assertEqual(mask.getpixel((70, 50)), 255)
        self.assertLess(mask.getbbox()[2], 150)

    def test_hole_and_multiple_contours_are_preserved(self):
        path = self.rectangle + ' M.25 .25 L.25 .75 L.75 .75 L.75 .25 Z'
        mask, _ = rasterize_mask(path, self.bbox, (200, 100))
        self.assertEqual(mask.getpixel((100, 50)), 0)
        self.assertEqual(mask.getpixel((60, 30)), 255)

    def test_markup_and_truncated_commands_are_rejected(self):
        for path in ['M0 0"><image href="https://example.com"/>',
                     'M0 0 C1 1', 'M0 0 LNaN 1', 'M0 0 A1 1 0 2 0 1 1']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                rasterize_mask(path, self.bbox, (200, 100))

    def test_masks_and_boxes_have_distinct_statuses(self):
        cases = [({'bbox': self.bbox}, 'bbox_only', False),
                 ({'path': 'M0 0 L1 0 Z', 'bbox': self.bbox}, 'zero_area_mask', False),
                 ({'path': self.rectangle, 'bbox': self.full_bbox}, 'full_frame_mask', False),
                 ({'path': self.rectangle, 'bbox': self.bbox}, 'nonempty_mask', True)]
        with tempfile.TemporaryDirectory() as directory:
            for number, (result, status, valid) in enumerate(cases):
                with self.subTest(status=status):
                    record = save_mask_artifacts(Image.new('RGB', (200, 100)), result,
                                                 directory, stem=f'case{number}')
                    self.assertEqual(record['status'], status)
                    self.assertEqual(record['valid_mask'], valid)
                    self.assertFalse(record['quality_validated'])
                    self.assertTrue(Path(record['artifacts']['metadata']).exists())
                    if valid:
                        self.assertAlmostEqual(record['mask_fraction'], .3)
                        self.assertTrue(Path(record['artifacts']['overlay']).exists())


if __name__ == '__main__':
    unittest.main()
