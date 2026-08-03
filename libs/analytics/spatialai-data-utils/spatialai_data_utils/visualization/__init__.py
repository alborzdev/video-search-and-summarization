# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Visualization convenience exports.

The individual visualization modules have different optional dependencies.
Keep the historical package-level API, but resolve its exports on first use so
importing a lightweight submodule does not pull in unrelated dependencies such
as Shapely.
"""

from __future__ import annotations

import json
from importlib import import_module
from importlib.resources import files
from typing import Any

with (files("spatialai_data_utils") / "assets" / "colormap.json").open("r") as f:
    COLOR_MAP = json.load(f)

_LAZY_EXPORTS = {
    "box3d_to_corners": "spatialai_data_utils.visualization.box_3d",
    "draw_bbox3d_multicam": "spatialai_data_utils.visualization.box_3d",
    "draw_bbox3d_on_bev": "spatialai_data_utils.visualization.box_3d",
    "draw_bbox3d_on_img": "spatialai_data_utils.visualization.box_3d",
    "draw_points3d_on_img": "spatialai_data_utils.visualization.box_3d",
    "draw_box3d_corners_on_img": "spatialai_data_utils.visualization.box_3d",
    "build_world2img_from_calib": "spatialai_data_utils.visualization.draw_utils",
    "build_world2img_from_calib_info": "spatialai_data_utils.visualization.draw_utils",
    "draw_camera_tag": "spatialai_data_utils.visualization.draw_utils",
    "generate_bbox_text": "spatialai_data_utils.visualization.draw_utils",
    "load_image": "spatialai_data_utils.visualization.draw_utils",
    "save_viz": "spatialai_data_utils.visualization.draw_utils",
    "CLUSTER_COLORS": "spatialai_data_utils.visualization.camera_groups",
    "draw_polygon": "spatialai_data_utils.visualization.camera_groups",
    "get_cluster_color": "spatialai_data_utils.visualization.camera_groups",
    "plot_sensor_groups": "spatialai_data_utils.visualization.camera_groups",
    "plot_sensor_groups_black_background": (
        "spatialai_data_utils.visualization.camera_groups"
    ),
    "transform_polygon": "spatialai_data_utils.visualization.camera_groups",
    "project_bev_objects_bbox_in_image": (
        "spatialai_data_utils.core.geometry.projection"
    ),
    "draw_bev_objects_bbox_in_image": "spatialai_data_utils.visualization.render",
    "visualize_3dbbox": "spatialai_data_utils.visualization.render",
    "visualize_nvschema": "spatialai_data_utils.visualization.render",
}

__all__ = ["COLOR_MAP", *_LAZY_EXPORTS]


def __getattr__(name: str) -> Any:
    """Resolve a historical package-level export on first access."""

    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Include lazily exported names in interactive discovery."""

    return sorted({*globals(), *__all__})
