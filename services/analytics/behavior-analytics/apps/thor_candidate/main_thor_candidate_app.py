# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Generate Thor candidate incidents from the existing RT-CV object metadata."""

import logging

from mdx.analytics.core.app.app_base import BaseApp
from mdx.analytics.core.schema.config import AppConfig
from mdx.analytics.core.schema.proto import schema_pb2 as nvSchema
from mdx.analytics.core.stream.state.frame.frame_state_management import FrameStateMgmt
from mdx.analytics.core.utils.processing_stats import BatchStats
from mdx.analytics.core.utils.schema_util import group_frames_by_sensor_id

from fov_adapter import ensure_fov_metric
from incident_gate import first_incident_per_activity

logger = logging.getLogger(__name__)


class ThorCandidateApp(BaseApp):
    """Create FOV candidate incidents without adding another GPU pipeline."""

    def __init__(self, config: AppConfig, calibration_path: str | None) -> None:
        """Initialize the single-device candidate incident processor.

        :param config: Behavior Analytics application configuration.
        :param calibration_path: Optional calibration file path.
        """
        super().__init__(config, calibration_path)
        self.frame_state_mgmt = FrameStateMgmt(self.config)
        self.reported_fov_sensors: set[str] = set()
        self.register_processor(
            self.read_raw,
            self.generate_incidents,
            int(self.config.get_app_config("numWorkersForIncidentGeneration", default_value="1")),
        )

    def generate_incidents(self, frames: list[nvSchema.Frame], stats: BatchStats) -> None:
        """Normalize a batch and emit incidents through standard mechanics.

        :param frames: Raw RT-CV frames.
        :param stats: Batch processing statistics.
        """
        enhanced_frames = [self.calibration.transform_frame(frame) for frame in frames]
        target_type = self.config.fov_count_violation_incident_object_type
        for frame in enhanced_frames:
            ensure_fov_metric(frame, target_type)

        for sensor_id, sensor_frames in group_frames_by_sensor_id(enhanced_frames).items():
            self.frame_state_mgmt.update_frames(sensor_id, sensor_frames)
            state = self.frame_state_mgmt.get_state(sensor_id)
            activity_active = bool(state and state.fov_count_violation_state)
            if activity_active and sensor_id in self.reported_fov_sensors:
                continue

            incidents = self.frame_state_mgmt.get_incidents(sensor_id)
            incidents = first_incident_per_activity(
                sensor_id,
                incidents,
                activity_active,
                self.reported_fov_sensors,
            )
            if incidents:
                logger.info(
                    "Batch %s - Created %s Thor candidate incident(s) for sensor %s",
                    stats.batch_id,
                    len(incidents),
                    sensor_id,
                )
                self.write_incidents(incidents)


if __name__ == "__main__":
    from mdx.analytics.core.app.app_runner import run

    run(ThorCandidateApp)
