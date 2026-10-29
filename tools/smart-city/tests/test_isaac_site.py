# SPDX-License-Identifier: Apache-2.0
"""CPU geometry controls independent of the live scene and site configuration."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('isaac_site', Path(__file__).parents[1] / 'isaac_site.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_clipped_roi_preserves_visible_intersections():
    result = module.clip_image_polygon([[-.2, .2], [.8, .2], [.8, 1.2], [-.2, 1.2]])
    assert sorted(result) == sorted([[0., .2], [.8, .2], [.8, 1.], [0., 1.]])


def test_fully_offscreen_roi_rejected():
    with pytest.raises(ValueError, match='no visible'):
        module.clip_image_polygon([[2., 2.], [3., 2.], [3., 3.]])


def test_projective_inverse_and_behind_camera_control():
    matrix = [[2., 0., 30.], [0., 3., 20.], [.001, .002, 1.]]
    ground = [4., 7.]
    pixel = module.project(matrix, ground)
    assert module.project(module.invert3(matrix), pixel) == pytest.approx(ground)
    with pytest.raises(ValueError, match='behind'):
        module.project([[1., 0., 0.], [0., 1., 0.], [0., 0., -1.]], ground)
    with pytest.raises(ValueError, match='Singular'):
        module.invert3([[1., 0., 0.], [0., 0., 0.], [0., 0., 1.]])


def test_third_camera_rejected_before_any_registration_read():
    with pytest.raises(ValueError, match='two'):
        module.build({'cameraOrder': ['A', 'B', 'C']}, {})
