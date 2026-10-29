"""Camera reframing must keep image rules on the same physical rays."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('reframe_isaac', Path(__file__).parents[1] / 'reframe_isaac.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_wider_camera_preserves_rule_rays_and_direction():
    old = {'width': 960, 'height': 540, 'K': [[480, 0, 480], [0, 480, 270], [0, 0, 1]], 'imageToGroundHomography': [[1,0,0],[0,1,0],[0,0,1]]}
    new = {'width': 1280, 'height': 480, 'K': [[480 * 8 / 9, 0, 640], [0, 480 * 8 / 9, 240], [0, 0, 1]], 'imageToGroundHomography': [[1.125,0,-240],[0,1.125,0],[0,0,1]]}
    original = {'space': 'image-normalized', 'points': [[.1, .2], [.9, .8]], 'direction': [.3, -.2]}
    result = module.image_geometry(original, old, new)
    for before, after in zip(original['points'], result['points']):
        assert (before[0] * old['width'] - old['K'][0][2]) / old['K'][0][0] == pytest.approx((after[0] * new['width'] - new['K'][0][2]) / new['K'][0][0])
        assert (before[1] * old['height'] - old['K'][1][2]) / old['K'][1][1] == pytest.approx((after[1] * new['height'] - new['K'][1][2]) / new['K'][1][1])
    assert result['direction'] == pytest.approx([.2, -.2])
    assert original['points'] == [[.1, .2], [.9, .8]]


def test_ground_rule_geometry_is_not_changed():
    ground = {'space': 'site-metres', 'points': [[-20, 75], [-21, 75]]}
    assert module.image_geometry(ground, {}, {}) == ground


def test_camera_move_preserves_ground_points():
    old = {'width': 100, 'height': 100, 'imageToGroundHomography': [[1,0,0],[0,1,0],[0,0,1]]}
    moved = {'width': 100, 'height': 100, 'imageToGroundHomography': [[1,0,10],[0,1,-5],[0,0,1]]}
    line = {'space': 'image-normalized', 'points': [[.3,.3],[.7,.7]], 'direction': [.1,.1]}
    result = module.image_geometry(line, old, moved)
    assert result['points'][0] == pytest.approx([.2,.35])
    assert result['points'][1] == pytest.approx([.6,.75])
    assert result['direction'] == pytest.approx([.1,.1])
