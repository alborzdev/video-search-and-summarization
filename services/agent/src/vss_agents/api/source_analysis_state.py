# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Durable desired state for per-source analysis.

The source catalog lives in VST, while the analysis services keep their live
registrations in process memory. Persisting the operator's paused set and
explicit analysis profile makes restart reconciliation safe: sources not in
the paused set are desired-active and may be rehydrated after a reboot, while
each source remains routed to the selected detector or semantic-only analysis.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import tempfile

from vss_agents.api.analysis_profiles import SEMANTIC_PROFILE_ID
from vss_agents.api.analysis_profiles import WAREHOUSE_PROFILE_ID
from vss_agents.api.analysis_profiles import require_analysis_profile

logger = logging.getLogger(__name__)

DEFAULT_STATE_FILE = "/vss-agent/agent_reports/source-analysis-state.json"

# Kept as a module-level set so existing callers and tests can clear the
# process-local view without replacing the object.
_paused_sources: set[str] = set()
_detection_disabled_sources: set[str] = set()
_source_analysis_profiles: dict[str, str] = {}
_source_kinds: dict[str, str] = {}
_loaded_state_path: Path | None = None

# Deletion is a short-lived process concern, not durable desired state.  A
# tombstone prevents the periodic VST reconciler from recreating downstream
# resources while the delete route is still tearing them down.  If the agent
# exits mid-delete, losing this set is intentional: the surviving VST catalog
# is authoritative after restart.
_deleting_sources: set[str] = set()


def _state_path() -> Path:
    return Path(os.getenv("VSS_SOURCE_ANALYSIS_STATE_FILE", DEFAULT_STATE_FILE))


def load_source_analysis_state(*, force: bool = False) -> set[str]:
    """Load the paused source IDs once for the currently configured path."""
    global _loaded_state_path

    path = _state_path()
    if not force and _loaded_state_path == path:
        return _paused_sources

    _paused_sources.clear()
    _detection_disabled_sources.clear()
    _source_analysis_profiles.clear()
    _source_kinds.clear()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        paused = payload.get("paused_source_ids", []) if isinstance(payload, dict) else []
        detection_disabled = payload.get("detection_disabled_source_ids", []) if isinstance(payload, dict) else []
        source_profiles = payload.get("source_analysis_profiles", {}) if isinstance(payload, dict) else {}
        source_kinds = payload.get("source_kinds", {}) if isinstance(payload, dict) else {}
        _paused_sources.update(item for item in paused if isinstance(item, str) and item.strip())
        _detection_disabled_sources.update(
            item for item in detection_disabled if isinstance(item, str) and item.strip()
        )
        if isinstance(source_profiles, dict):
            _source_analysis_profiles.update(
                (source_id, profile_id)
                for source_id, profile_id in source_profiles.items()
                if isinstance(source_id, str)
                and source_id.strip()
                and isinstance(profile_id, str)
                and profile_id.strip()
            )
        if isinstance(source_kinds, dict):
            _source_kinds.update(
                (source_id, source_kind)
                for source_id, source_kind in source_kinds.items()
                if isinstance(source_id, str)
                and source_id.strip()
                and source_kind in {"live", "recorded"}
            )
        # Schema-v2 stored only an enabled bit. Preserve its meaning while
        # migrating to an explicit profile without requiring a one-off job.
        for source_id in _detection_disabled_sources:
            _source_analysis_profiles.setdefault(source_id, SEMANTIC_PROFILE_ID)
    except FileNotFoundError:
        pass
    except Exception:
        # A corrupt state file must not prevent the agent from starting.  The
        # empty fallback is visible as desired-active and runtime status stays
        # partial until reconciliation proves that analysis is actually live.
        logger.warning("Could not load live-analysis desired state from %s", path, exc_info=True)
    _loaded_state_path = path
    return _paused_sources


def _persist_source_analysis_state() -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 4,
        "detection_disabled_source_ids": sorted(_detection_disabled_sources),
        "paused_source_ids": sorted(_paused_sources),
        "source_analysis_profiles": dict(sorted(_source_analysis_profiles.items())),
        "source_kinds": dict(sorted(_source_kinds.items())),
    }

    # Write and replace within the same directory so a reboot cannot leave a
    # partially written JSON document behind.
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def is_source_paused(stream_id: str) -> bool:
    load_source_analysis_state()
    return stream_id in _paused_sources


def is_source_detection_enabled(stream_id: str) -> bool:
    """Return whether this source should use a detector profile.

    Detection remains enabled by default for backwards compatibility with
    existing NVIDIA lifecycle callers. New callers should persist an explicit
    profile with ``set_source_analysis_profile``.
    """
    load_source_analysis_state()
    return get_source_analysis_profile(stream_id) != SEMANTIC_PROFILE_ID


def get_source_analysis_profile(stream_id: str) -> str:
    """Return the durable profile, migrating legacy detector booleans."""
    load_source_analysis_state()
    if stream_id in _source_analysis_profiles:
        return _source_analysis_profiles[stream_id]
    return SEMANTIC_PROFILE_ID if stream_id in _detection_disabled_sources else WAREHOUSE_PROFILE_ID


def source_ids_with_analysis_profile(profile_id: str) -> frozenset[str]:
    """Return durable explicit assignments for one analysis profile.

    Capacity is a registered-source limit: a retained recording remains
    assigned until its explicit deletion or re-profiling releases that slot.
    Legacy detector-disabled state is migrated to an explicit semantic profile
    on load. A known source with no explicit profile still has the historical
    warehouse default, so include it when admitting the warehouse profile.
    Sources absent from durable state cannot be counted without a VST inventory
    lookup and are reconciled into explicit state on their next control action.
    """
    require_analysis_profile(profile_id)
    load_source_analysis_state()
    source_ids = {
        source_id
        for source_id, assigned_profile_id in _source_analysis_profiles.items()
        if assigned_profile_id == profile_id
    }
    if profile_id == WAREHOUSE_PROFILE_ID:
        source_ids.update(
            (set(_paused_sources) | set(_source_kinds))
            - set(_source_analysis_profiles)
            - _detection_disabled_sources
        )
    return frozenset(source_ids)


def set_source_analysis_profile(stream_id: str, profile_id: str) -> None:
    """Persist one explicit profile independently from pause/resume state."""
    require_analysis_profile(profile_id)
    load_source_analysis_state()
    _source_analysis_profiles[stream_id] = profile_id
    if profile_id == SEMANTIC_PROFILE_ID:
        _detection_disabled_sources.add(stream_id)
    else:
        _detection_disabled_sources.discard(stream_id)
    _persist_source_analysis_state()


def get_source_kind(stream_id: str) -> str | None:
    """Return the durable source kind, or None for pre-schema-v4 sources."""
    load_source_analysis_state()
    return _source_kinds.get(stream_id)


def set_source_kind(stream_id: str, source_kind: str) -> None:
    """Persist whether VST's RTSP-looking endpoint is a camera or a replay."""
    if source_kind not in {"live", "recorded"}:
        raise ValueError("source_kind must be 'live' or 'recorded'")
    load_source_analysis_state()
    _source_kinds[stream_id] = source_kind
    _persist_source_analysis_state()


def is_source_deleting(stream_id: str) -> bool:
    """Return whether source teardown currently owns this source ID."""
    return stream_id in _deleting_sources


def set_source_deleting(stream_id: str, deleting: bool) -> None:
    """Set or clear the process-local reconciliation tombstone."""
    if deleting:
        _deleting_sources.add(stream_id)
    else:
        _deleting_sources.discard(stream_id)


def set_source_paused(stream_id: str, paused: bool) -> None:
    load_source_analysis_state()
    if paused:
        _paused_sources.add(stream_id)
    else:
        _paused_sources.discard(stream_id)
    _persist_source_analysis_state()


def set_source_detection_enabled(stream_id: str, enabled: bool) -> None:
    """Persist the detector choice independently from pause/resume state."""
    set_source_analysis_profile(stream_id, WAREHOUSE_PROFILE_ID if enabled else SEMANTIC_PROFILE_ID)


def forget_source_analysis_state(stream_id: str) -> None:
    """Discard a deleted source's desired state without touching other IDs."""
    load_source_analysis_state()
    if (
        stream_id not in _paused_sources
        and stream_id not in _detection_disabled_sources
        and stream_id not in _source_analysis_profiles
        and stream_id not in _source_kinds
    ):
        return
    _paused_sources.discard(stream_id)
    _detection_disabled_sources.discard(stream_id)
    _source_analysis_profiles.pop(stream_id, None)
    _source_kinds.pop(stream_id, None)
    _persist_source_analysis_state()
