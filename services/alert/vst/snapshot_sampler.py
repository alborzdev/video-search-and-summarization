# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Historical VST snapshot sampling for image-only candidate verification."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, List
from urllib.parse import urlsplit, urlunsplit

import requests

logger = logging.getLogger(__name__)

MAX_SNAPSHOT_FRAMES = 4
TIMELINE_END_MARGIN = timedelta(milliseconds=50)


class VSTSnapshotError(RuntimeError):
    """Raised when a candidate incident cannot be represented by snapshots."""


def equidistant_timestamps(
    start_time: str, end_time: str, frame_count: int
) -> List[str]:
    """Return at most four inclusive, equidistant UTC timestamps.

    :param start_time: Inclusive incident start as an ISO-8601 timestamp.
    :param end_time: Inclusive incident end as an ISO-8601 timestamp.
    :param frame_count: Requested number of frames; values above four are capped.
    :return: Normalized ISO-8601 timestamps with a ``Z`` suffix.
    :raises VSTSnapshotError: If timestamps or frame count are invalid.
    """
    if frame_count < 1:
        raise VSTSnapshotError("snapshot frame count must be positive")

    try:
        start = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        end = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise VSTSnapshotError(
            "incident timestamps must be valid ISO-8601 values"
        ) from exc

    if start.tzinfo is None or end.tzinfo is None:
        raise VSTSnapshotError("incident timestamps must include a timezone")
    start = start.astimezone(timezone.utc)
    end = end.astimezone(timezone.utc)
    if end < start:
        raise VSTSnapshotError("incident end timestamp precedes its start timestamp")

    count = min(frame_count, MAX_SNAPSHOT_FRAMES)
    if count == 1 or end == start:
        samples = [start]
    else:
        duration = end - start
        samples = [start + duration * (index / (count - 1)) for index in range(count)]
    return [
        sample.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        for sample in samples
    ]


class VSTSnapshotSampler:
    """Resolve historical VST picture URLs for a candidate incident."""

    def __init__(
        self,
        vst_handler,
        request_get: Callable = requests.get,
    ) -> None:
        """Initialize the sampler around the existing VST handler.

        :param vst_handler: Existing :class:`ITS_VST_HANDLER` instance.
        :param request_get: Injectable HTTP GET callable for tests.
        """
        self._vst_handler = vst_handler
        self._request_get = request_get

    def sample(
        self,
        sensor_name: str,
        start_time: str,
        end_time: str,
        frame_count: int = MAX_SNAPSHOT_FRAMES,
    ) -> List[str]:
        """Fetch signed snapshot URLs at equidistant points in an incident.

        :param sensor_name: VST sensor display name from the incident.
        :param start_time: Incident start timestamp.
        :param end_time: Incident end timestamp.
        :param frame_count: Requested number of snapshots, capped at four.
        :return: Locally reachable VST JPEG URLs in chronological order.
        :raises VSTSnapshotError: If stream resolution or a picture request fails.
        """
        stream_id = self._vst_handler._get_stream_id_from_name(sensor_name)
        if not stream_id:
            raise VSTSnapshotError(f"VST stream not found for sensor '{sensor_name}'")

        config = self._vst_handler.config.get("vst_config", {})
        base_url = str(config.get("base_url", "")).rstrip("/")
        if not base_url:
            raise VSTSnapshotError("VST base URL is not configured")
        timeout = float(config.get("request_timeout", 10))
        start_time, end_time = self._clip_to_timeline(
            stream_id, start_time, end_time, base_url, timeout
        )

        image_urls: List[str] = []
        for timestamp in equidistant_timestamps(start_time, end_time, frame_count):
            endpoint = f"{base_url}/vst/api/v1/replay/stream/{stream_id}/picture/url"
            try:
                response = self._request_get(
                    endpoint, params={"startTime": timestamp}, timeout=timeout
                )
                response.raise_for_status()
                image_url = response.json().get("imageUrl")
            except (requests.RequestException, ValueError, AttributeError) as exc:
                raise VSTSnapshotError(
                    f"VST picture request failed at {timestamp}: {exc}"
                ) from exc
            if not image_url:
                raise VSTSnapshotError(
                    f"VST picture response omitted imageUrl at {timestamp}"
                )
            image_urls.append(self._rewrite_authority(str(image_url), base_url))

        logger.info(
            "Sampled %s VST snapshot(s) for sensor %s between %s and %s",
            len(image_urls),
            sensor_name,
            start_time,
            end_time,
        )
        return image_urls

    def _clip_to_timeline(
        self,
        stream_id: str,
        start_time: str,
        end_time: str,
        base_url: str,
        timeout: float,
    ) -> tuple[str, str]:
        """Clip an incident to the overlapping VST recording interval."""
        endpoint = f"{base_url}/vst/api/v1/storage/timelines"
        try:
            response = self._request_get(endpoint, timeout=timeout)
            response.raise_for_status()
            entries = response.json().get(stream_id, [])
            return _best_timeline_overlap(start_time, end_time, entries)
        except (requests.RequestException, ValueError, AttributeError) as exc:
            raise VSTSnapshotError(f"VST timeline request failed: {exc}") from exc

    @staticmethod
    def _rewrite_authority(image_url: str, base_url: str) -> str:
        """Keep VST's signed path while using the configured local authority."""
        image = urlsplit(image_url)
        base = urlsplit(base_url)
        if (
            not image.scheme
            or not image.netloc
            or not image.path
            or not base.scheme
            or not base.netloc
        ):
            raise VSTSnapshotError("VST returned an invalid image URL")
        return urlunsplit(
            (base.scheme, base.netloc, image.path, image.query, image.fragment)
        )


def _best_timeline_overlap(
    start_time: str,
    end_time: str,
    entries: List[dict[str, Any]],
) -> tuple[str, str]:
    """Return the incident bounds clipped to their best recording overlap."""
    requested = equidistant_timestamps(start_time, end_time, 2)
    requested_start = datetime.fromisoformat(requested[0].replace("Z", "+00:00"))
    requested_end = datetime.fromisoformat(requested[-1].replace("Z", "+00:00"))
    candidates: List[tuple[timedelta, datetime, datetime]] = []
    for entry in entries:
        try:
            available = equidistant_timestamps(
                entry.get("startTime"), entry.get("endTime"), 2
            )
        except VSTSnapshotError:
            continue
        available_start = datetime.fromisoformat(available[0].replace("Z", "+00:00"))
        available_end = datetime.fromisoformat(available[-1].replace("Z", "+00:00"))
        overlap_start = max(requested_start, available_start)
        overlap_end = min(requested_end, available_end)
        if overlap_end >= overlap_start:
            candidates.append((overlap_end - overlap_start, overlap_start, overlap_end))

    if not candidates:
        raise VSTSnapshotError("incident does not overlap the VST recording timeline")

    _, clipped_start, clipped_end = max(candidates, key=lambda item: item[0])
    if clipped_end - clipped_start > TIMELINE_END_MARGIN:
        clipped_end -= TIMELINE_END_MARGIN
    return (
        clipped_start.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        clipped_end.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
    )
