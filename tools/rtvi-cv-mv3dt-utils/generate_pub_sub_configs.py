# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

import argparse
import math
import os
import re
from pathlib import Path
from os.path import join

import cv2
import numpy as np
import tqdm
import yaml


SAFE_CAMERA_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
SAFE_BROKER = re.compile(r"^[A-Za-z0-9.-]+:[0-9]{1,5}$")


def get_camera_fov_mask(cam_calib, num_pix, range_of_interest=None):
    P, Q, K, R, _, pos, end, height = cam_calib
    cx, cy = K[0, 2], K[1, 2]
    cam_h, cam_w = int(cy * 2), int(cx * 2)
    limits_ov = np.asarray(range_of_interest, dtype=float)
    if limits_ov.shape != (4,) or not np.all(np.isfinite(limits_ov)):
        raise ValueError("range_of_interest must contain four finite numbers.")
    if limits_ov[2] <= limits_ov[0] or limits_ov[3] <= limits_ov[1]:
        raise ValueError("range_of_interest must have x2>x1 and y2>y1.")
    x_ov = np.arange(np.round(limits_ov[0]), np.round(limits_ov[2]))
    y_ov = np.arange(np.round(limits_ov[1]), np.round(limits_ov[3]))
    xy_ov = np.array(np.meshgrid(x_ov, y_ov), dtype=float).reshape(2, -1)
    # Create 3D points in z=0, z=h/2, z=h
    xyz_0 = np.vstack([xy_ov, np.zeros(xy_ov.shape[1])]).T.reshape(
        len(x_ov), len(y_ov), 3
    )
    xyz_h = np.vstack([xy_ov, height * np.ones(xy_ov.shape[1])]).T.reshape(
        len(x_ov), len(y_ov), 3
    )
    # Project to the image plane
    xy0_cam = cv2.perspectiveTransform(xyz_0, P).reshape(-1, 2).T
    xyh_cam = cv2.perspectiveTransform(xyz_h, P).reshape(-1, 2).T
    # Create the mask
    mask1 = (xy0_cam[0] > 0) & (xy0_cam[0] < cam_w)
    mask2 = (xy0_cam[1] > 0) & (xy0_cam[1] < cam_h)
    mask3 = (
        np.linalg.norm(xyh_cam - xy0_cam, ord=np.inf, axis=0) > num_pix
    )  # object size: OK
    mask4 = ((xy_ov.T - pos.T) @ (end - pos)).flatten() > 0  # direction: OK
    # Update the mask
    mask = mask1 & mask2 & mask3 & mask4
    return mask


def _safe_camera_name(name):
    if name in {".", ".."} or not SAFE_CAMERA_NAME.fullmatch(name):
        raise ValueError(
            f"Unsafe camera name '{name}'; use letters, digits, '.', '_', or '-'."
        )
    return name


def _reject_symlinked_path_components(path, field_name):
    path = Path(path)
    absolute = path if path.is_absolute() else Path.cwd() / path
    for component in (absolute, *absolute.parents):
        if component.is_symlink():
            raise ValueError(
                f"{field_name} must not be a symlink or contain a symlink component: {component}"
            )


def load_and_process_camera_matrices(cam_info_path):
    # Load all .yml and .yaml files
    cam_info_dir = Path(cam_info_path)
    if not cam_info_dir.is_dir() or cam_info_dir.is_symlink():
        raise ValueError(f"cam_info_path must be a real directory: {cam_info_path}")
    cam_files = sorted([*cam_info_dir.glob("*.yml"), *cam_info_dir.glob("*.yaml")])
    if not cam_files:
        raise ValueError(f"No camera info YAML files found in: {cam_info_path}")

    cam_matrices = {}
    cam_names = {}  # cam_id -> camInfo filename stem (used as map key in pub/sub configs)
    seen_names = set()
    for idx, cam_file in enumerate(cam_files):
        if cam_file.is_symlink() or not cam_file.is_file():
            raise ValueError(f"Camera info input must be a regular file: {cam_file}")
        cam = idx + 1
        cam_name = _safe_camera_name(cam_file.stem)
        if cam_name in seen_names:
            raise ValueError(f"Duplicate camera name '{cam_name}'.")
        seen_names.add(cam_name)
        cam_names[cam] = cam_name

        with cam_file.open("r", encoding="utf-8") as file:
            yaml_data = yaml.safe_load(file)
        if not isinstance(yaml_data, dict):
            raise ValueError(f"Camera info root must be a mapping: {cam_file}")
        model_info = yaml_data.get("modelInfo")
        if isinstance(model_info, list) and model_info:
            heights = [
                entry.get("height") for entry in model_info if isinstance(entry, dict)
            ]
            if len(heights) != len(model_info):
                raise ValueError(f"Invalid modelInfo entries in: {cam_file}")
            height = max(float(value) for value in heights)
        elif isinstance(model_info, dict) and "height" in model_info:
            height = float(model_info["height"])
        else:
            raise ValueError(f"Camera info has no model height: {cam_file}")
        if not math.isfinite(height) or height <= 0:
            raise ValueError(
                f"Camera model height must be finite and positive: {cam_file}"
            )
        projection = yaml_data.get("projectionMatrix_3x4_w2p")
        P = np.asarray(projection, dtype=float)
        if P.size != 12 or not np.all(np.isfinite(P)):
            raise ValueError(
                f"Projection matrix must contain 12 finite numbers: {cam_file}"
            )
        P = P.reshape(3, 4)
        Q = np.linalg.pinv(P)
        K, R, t, _, _, _, _ = cv2.decomposeProjectionMatrix(P)
        if not np.all(np.isfinite(K)) or K[2, 2] == 0:
            raise ValueError(
                f"Projection matrix cannot be decomposed safely: {cam_file}"
            )
        K = K / K[2, 2]
        # Camera position on the world plane (-R.t @ t)
        pos = t[:2] / t[-1]
        # Point 3 world units (meters) in front of the camera, used to define
        # the camera's forward direction for FOV culling.
        forward_norm = np.linalg.norm(R[-1, :2])
        if not np.isfinite(forward_norm) or forward_norm == 0:
            raise ValueError(f"Camera forward direction is degenerate: {cam_file}")
        end = pos + R[-1:, :2].T * (3 / forward_norm)
        cam_matrices[cam] = P, Q, K, R, t, pos, end, height
    return cam_matrices, cam_names


def get_overlap_of_2_masks(mask1, mask2):
    overlap = np.logical_and(mask1, mask2)
    overlap_count = int(np.sum(overlap))
    mask1_size = int(np.sum(mask1))
    mask2_size = int(np.sum(mask2))
    # Treat an empty mask as zero overlap (avoids NaN poisoning top_N selection).
    mask1_ratio = overlap_count / mask1_size if mask1_size > 0 else 0.0
    mask2_ratio = overlap_count / mask2_size if mask2_size > 0 else 0.0
    return mask1_ratio, mask2_ratio, overlap_count


def get_overlap_matrix(
    cam_matrices, minimum_object_size, range_of_interest, cam_names=None
):
    if not cam_matrices:
        raise ValueError("At least one camera matrix is required.")
    if minimum_object_size < 0:
        raise ValueError("minimum_object_size must be non-negative.")
    overlap_matrix = {}
    masks = {}

    # Generate masks for all cameras
    for cam in tqdm.tqdm(cam_matrices, desc="Generating masks"):
        mask = get_camera_fov_mask(
            cam_matrices[cam],
            num_pix=minimum_object_size,
            range_of_interest=range_of_interest,
        )
        masks[cam] = mask

    # Surface empty-mask cameras as misconfiguration (no visible world-plane samples).
    empty_cams = [cam for cam, m in masks.items() if int(np.sum(m)) == 0]
    if empty_cams:
        empty_names = [cam_names[c] if cam_names else str(c) for c in empty_cams]
        print(
            f"WARNING: {len(empty_cams)} camera(s) produced an empty FOV mask "
            f"and will have no vision neighbors: {empty_names}. "
            f"Check --range_of_interest, --minimum_object_size, and the "
            f"camInfo projection matrices for these cameras."
        )

    # Calculate overlap ratios for all camera pairs
    for cam1 in tqdm.tqdm(cam_matrices, desc="Calculating overlaps"):
        overlap_matrix[cam1] = {}
        mask1 = masks[cam1]
        for cam2 in cam_matrices:
            if cam1 == cam2:
                continue
            mask2 = masks[cam2]
            mask1_ratio, mask2_ratio, _ = get_overlap_of_2_masks(mask1, mask2)
            overlap_matrix[cam1][cam2] = mask1_ratio

    return overlap_matrix


def get_subscription_map(overlap_matrix, criteria):
    if ":" not in criteria:
        raise ValueError(
            f"Unknown --neighbor_criteria '{criteria}'. "
            f"Expected 'top_N:<int>' or 'overlap_threshold:<float>'."
        )
    criteria_type, value = criteria.split(":", 1)
    subscription_map = {}
    if criteria_type == "top_N":
        N = int(value)
        if N < 0:
            raise ValueError(f"top_N must be non-negative, got {N}.")
        for cam in overlap_matrix:
            neighbors = list(overlap_matrix[cam].keys())
            k = min(N, len(neighbors))
            if k == 0:
                subscription_map[cam] = []
                continue
            ranked = sorted(
                neighbors,
                key=lambda neighbor: (-overlap_matrix[cam][neighbor], neighbor),
            )
            subscription_map[cam] = sorted(ranked[:k])

    elif criteria_type == "overlap_threshold":
        threshold = float(value)
        if not math.isfinite(threshold) or threshold < 0 or threshold > 1:
            raise ValueError("overlap_threshold must be finite and between 0 and 1.")
        for cam in overlap_matrix:
            subscription_map[cam] = sorted(
                neighbor
                for neighbor, ratio in overlap_matrix[cam].items()
                if ratio >= threshold
            )

    else:
        raise ValueError(
            f"Unknown --neighbor_criteria '{criteria}'. "
            f"Expected 'top_N:<int>' or 'overlap_threshold:<float>'."
        )

    return subscription_map


def _parse_brokers(mqtt_brokers):
    brokers = [broker.strip() for broker in mqtt_brokers.split(",")]
    if not brokers or any(not broker for broker in brokers):
        raise ValueError("At least one non-empty MQTT broker is required.")
    for broker in brokers:
        if not SAFE_BROKER.fullmatch(broker):
            raise ValueError(f"Invalid MQTT broker '{broker}'; expected host:port.")
        port = int(broker.rsplit(":", 1)[1])
        if port < 1 or port > 65535:
            raise ValueError(f"Invalid MQTT broker port in '{broker}'.")
    return brokers


def generate_pub_sub_config(
    cam_info_path,
    mqtt_brokers="127.0.0.1:1883",
    minimum_object_size=50,
    neighbor_criteria="overlap_threshold:%f" % (2 / (1920 * 1080)),
    output_path="./peer_configs",
    range_of_interest=None,
):
    """Generate one deterministic, fail-closed MV3DT pub/sub configuration."""
    cam_matrices, cam_names = load_and_process_camera_matrices(cam_info_path)
    cam_ids = sorted(cam_matrices)
    n = len(cam_ids)
    print(f"Loaded {n} cameras: {[cam_names[c] for c in cam_ids]}")

    brokers = _parse_brokers(mqtt_brokers)
    num_instances = len(brokers)
    block_size = (n + num_instances - 1) // num_instances
    cam2instance = {
        cam: min((index // block_size), num_instances - 1)
        for index, cam in enumerate(cam_ids)
    }
    print(
        f"Distributing {n} cameras across {num_instances} instance(s), ~{block_size} per instance"
    )

    if range_of_interest is not None:
        if isinstance(range_of_interest, str):
            try:
                range_of_interest_ov = np.array(
                    [float(value) for value in range_of_interest.split(",")],
                    dtype=float,
                )
            except ValueError as exc:
                raise ValueError(
                    "range_of_interest must contain four numbers."
                ) from exc
        else:
            range_of_interest_ov = np.asarray(range_of_interest, dtype=float)
    else:
        range_padding = 20
        cam_poses = [cam_matrices[cam][5] for cam in cam_ids]
        min_x = min(pose[0][0] for pose in cam_poses)
        max_x = max(pose[0][0] for pose in cam_poses)
        min_y = min(pose[1][0] for pose in cam_poses)
        max_y = max(pose[1][0] for pose in cam_poses)
        range_of_interest_ov = np.array(
            [
                min_x - range_padding,
                min_y - range_padding,
                max_x + range_padding,
                max_y + range_padding,
            ],
            dtype=float,
        )
    if range_of_interest_ov.shape != (4,) or not np.all(
        np.isfinite(range_of_interest_ov)
    ):
        raise ValueError("range_of_interest must contain exactly four finite numbers.")
    if (
        range_of_interest_ov[2] <= range_of_interest_ov[0]
        or range_of_interest_ov[3] <= range_of_interest_ov[1]
    ):
        raise ValueError("range_of_interest must have x2>x1 and y2>y1.")

    overlap_matrix = get_overlap_matrix(
        cam_matrices, minimum_object_size, range_of_interest_ov, cam_names=cam_names
    )
    subscription_map = get_subscription_map(overlap_matrix, neighbor_criteria)

    num_neighbors = np.mean([len(subscription_map[cam]) for cam in subscription_map])
    print(f"Average number of neighbors: {num_neighbors}")
    for cam in cam_ids:
        print(
            f"    {cam_names[cam]}:", [cam_names[nei] for nei in subscription_map[cam]]
        )

    config = {"pubBrokerTopicStr": {}, "subPeerBrokerTopicStrs": {}}
    for cam in cam_ids:
        cam_name = cam_names[cam]
        cam_broker = brokers[cam2instance[cam]]
        config["pubBrokerTopicStr"][cam_name] = f"{cam_broker};/trck/{cam_name}"
        config["subPeerBrokerTopicStrs"][cam_name] = []
        for neighbor in subscription_map[cam]:
            neighbor_name = cam_names[neighbor]
            neighbor_broker = brokers[cam2instance[neighbor]]
            config["subPeerBrokerTopicStrs"][cam_name].append(
                f"{neighbor_broker};/trck/{neighbor_name}"
            )

    output_dir = Path(output_path)
    _reject_symlinked_path_components(output_dir, "Output directory")
    output_dir.mkdir(parents=True, exist_ok=True)
    _reject_symlinked_path_components(output_dir, "Output directory")
    out_path = output_dir / "pub_sub_info_config.yml"
    if out_path.is_symlink():
        raise ValueError(f"Refusing to overwrite symlink output: {out_path}")
    out_path.write_text(
        yaml.safe_dump(config, default_flow_style=False, sort_keys=True),
        encoding="utf-8",
    )
    print(f"Written: {out_path}")
    return out_path


def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--cam_info_path",
        type=str,
        default=join(os.getcwd(), "camInfo"),
        help="Directory containing camera calibration info (intrinsic & extrinsic params)",
    )

    parser.add_argument(
        "--mqtt_brokers",
        type=str,
        default="127.0.0.1:1883",
        help="Comma-separated MQTT broker host:port list. For a Docker Compose deployment a single entry is sufficient; "
        "if multiple entries are provided, cameras (sorted by filename) are distributed evenly across the brokers.",
    )

    parser.add_argument(
        "--minimum_object_size",
        type=int,
        default=50,
        help="Number of pixels (in height) to consider an object visible when rendering FOV",
    )

    parser.add_argument(
        "--neighbor_criteria",
        type=str,
        default="overlap_threshold:%f" % (2 / (1920 * 1080)),
        help='Format: "top_N:{N}" or "overlap_threshold:{thres}". Determines neighbor selection method',
    )

    parser.add_argument(
        "--output_path",
        type=str,
        default="./peer_configs",
        help="Directory to store output pub_sub_info_config.yml",
    )

    parser.add_argument(
        "--range_of_interest",
        type=str,
        default=None,
        help='Range of interest of world plane in format "x1,y1,x2,y2" where (x1,y1) is min corner and (x2,y2) is max corner',
    )

    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    generate_pub_sub_config(
        cam_info_path=args.cam_info_path,
        mqtt_brokers=args.mqtt_brokers,
        minimum_object_size=args.minimum_object_size,
        neighbor_criteria=args.neighbor_criteria,
        output_path=args.output_path,
        range_of_interest=args.range_of_interest,
    )
