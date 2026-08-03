# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Prove lightweight visualization imports do not require Shapely."""

import subprocess
import sys
import textwrap


_BLOCKER_PRELUDE = textwrap.dedent(
    """
    import sys

    for _mod in list(sys.modules):
        if _mod == 'shapely' or _mod.startswith('shapely.'):
            del sys.modules[_mod]

    class _Blocker:
        def find_spec(self, name, path=None, target=None):
            if name == 'shapely' or name.startswith('shapely.'):
                raise ModuleNotFoundError(
                    f'simulated missing: {name}', name=name
                )
            return None

    sys.meta_path.insert(0, _Blocker())
    """
).strip()


def _run_without_shapely(body: str) -> subprocess.CompletedProcess:
    script = _BLOCKER_PRELUDE + "\n" + textwrap.dedent(body)
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_box_and_multiview_modules_import_without_shapely():
    result = _run_without_shapely(
        """
        import sys
        import spatialai_data_utils.visualization as visualization
        from spatialai_data_utils.visualization.box_2d import draw_box_2d
        from spatialai_data_utils.visualization.box_3d import draw_bbox3d_multicam

        assert callable(draw_box_2d)
        assert callable(draw_bbox3d_multicam)
        assert visualization.draw_bbox3d_multicam is draw_bbox3d_multicam
        assert not any(
            name == 'shapely' or name.startswith('shapely.')
            for name in sys.modules
        )
        assert 'spatialai_data_utils.visualization.camera_groups' not in sys.modules
        print('OK')
        """
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_video_and_frame_modules_import_without_shapely():
    result = _run_without_shapely(
        """
        import sys
        from spatialai_data_utils.visualization.video_utils.frame2video import (
            frames_to_video,
            list_frame_paths,
        )
        from spatialai_data_utils.visualization.video_utils.video2frame import (
            video_to_frames,
        )

        assert callable(frames_to_video)
        assert callable(list_frame_paths)
        assert callable(video_to_frames)
        assert not any(
            name == 'shapely' or name.startswith('shapely.')
            for name in sys.modules
        )
        assert 'spatialai_data_utils.visualization.camera_groups' not in sys.modules
        print('OK')
        """
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_camera_group_exports_fail_only_when_accessed_without_shapely():
    result = _run_without_shapely(
        """
        import sys
        import spatialai_data_utils.visualization as visualization

        assert 'CLUSTER_COLORS' in visualization.__all__
        assert 'CLUSTER_COLORS' in dir(visualization)
        assert 'spatialai_data_utils.visualization.camera_groups' not in sys.modules
        try:
            visualization.CLUSTER_COLORS
        except ModuleNotFoundError as exc:
            assert exc.name == 'shapely', exc
            print('DEFERRED')
        else:
            raise AssertionError('camera-group export did not require Shapely')
        """
    )
    assert result.returncode == 0, result.stderr
    assert "DEFERRED" in result.stdout


def test_camera_group_top_level_exports_remain_compatible():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            textwrap.dedent(
                """
                import spatialai_data_utils.visualization as visualization
                from types import SimpleNamespace

                names = (
                    'CLUSTER_COLORS',
                    'draw_polygon',
                    'get_cluster_color',
                    'plot_sensor_groups',
                    'plot_sensor_groups_black_background',
                    'transform_polygon',
                )
                exports = {name: object() for name in names}
                camera_groups = SimpleNamespace(**exports)
                calls = []

                def import_module(name):
                    calls.append(name)
                    assert name == 'spatialai_data_utils.visualization.camera_groups'
                    return camera_groups

                visualization.import_module = import_module
                for name in names:
                    assert getattr(visualization, name) is exports[name]
                assert calls == [
                    'spatialai_data_utils.visualization.camera_groups'
                ] * len(names)
                print('OK')
                """
            ),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout
