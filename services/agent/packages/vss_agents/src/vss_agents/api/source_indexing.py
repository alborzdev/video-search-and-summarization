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

"""Durable, source-scoped embedding intent, independent from detector intent.

Smart City defaults to explicit finite indexing. Other profiles preserve their
continuous indexing default. A finite lease never survives an Agent restart;
completed vectors remain searchable without restarting their producer.
"""

from __future__ import annotations

from datetime import UTC
from datetime import datetime
from datetime import timedelta
import json
import logging
import os
from pathlib import Path
import tempfile
from threading import RLock
from typing import Literal
from uuid import uuid4

from pydantic import AwareDatetime
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from vss_agents.api.analysis_profiles import SMART_CITY_PROFILE_ID
from vss_agents.api.source_analysis_state import DEFAULT_STATE_FILE
from vss_agents.api.source_analysis_state import get_source_analysis_profile
from vss_agents.api.source_analysis_state import is_source_deleting
from vss_agents.api.source_analysis_state import is_source_paused

logger = logging.getLogger(__name__)
IndexingMode = Literal["continuous", "on-demand", "disabled"]
SessionState = Literal["starting", "running", "completed", "cancelled", "interrupted", "failed"]
_ACTIVE_SESSION_STATES = {"starting", "running"}


class IndexingSession(BaseModel):
    """One bounded producer lease; timestamps describe requests, not coverage."""

    id: str
    requested_at: AwareDatetime = Field(alias="requestedAt")
    deadline_at: AwareDatetime = Field(alias="deadlineAt")
    duration_seconds: int = Field(alias="durationSeconds", ge=30, le=600)
    started_at: AwareDatetime | None = Field(default=None, alias="startedAt")
    ended_at: AwareDatetime | None = Field(default=None, alias="endedAt")
    state: SessionState = "starting"
    reason: str | None = None

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class SourceIndexingPolicy(BaseModel):
    mode: IndexingMode
    revision: int = Field(default=1, ge=1)
    session: IndexingSession | None = None

    model_config = ConfigDict(extra="forbid")


_policies: dict[str, SourceIndexingPolicy] = {}
_loaded_path: Path | None = None
_load_error: str | None = None
_lock = RLock()


def _state_path() -> Path:
    existing = Path(os.getenv("VSS_SOURCE_ANALYSIS_STATE_FILE", DEFAULT_STATE_FILE))
    return Path(os.getenv("VSS_SOURCE_INDEXING_STATE_FILE", str(existing.with_name("source-indexing-state.json"))))


def _persist() -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "schemaVersion": 1,
        "sources": {key: value.model_dump(mode="json", by_alias=True) for key, value in _policies.items()},
    }
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(body, handle, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def load_indexing_policies(*, force: bool = False) -> None:
    """Fail closed on corrupt state and interrupt finite leases after restart."""
    global _loaded_path, _load_error
    with _lock:
        path = _state_path()
        if not force and _loaded_path == path:
            return
        _policies.clear()
        _load_error = None
        interrupted = False
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
            if body.get("schemaVersion") != 1 or not isinstance(body.get("sources"), dict):
                raise ValueError("Unknown indexing policy schema")
            for key, value in body["sources"].items():
                if not isinstance(key, str) or not key:
                    raise ValueError("Invalid source ID")
                policy = SourceIndexingPolicy.model_validate(value)
                session = policy.session
                if session and session.state in _ACTIVE_SESSION_STATES:
                    session.state = "interrupted"
                    session.reason = "agent-restarted; explicit start required"
                    session.ended_at = min(datetime.now(UTC), session.deadline_at)
                    interrupted = True
                _policies[key] = policy
        except FileNotFoundError:
            pass
        except Exception:
            _policies.clear()
            _load_error = "indexing-policy-state-unreadable"
            logger.warning("Indexing state is unreadable; automatic indexing is disabled", exc_info=True)
        _loaded_path = path
        if interrupted:
            _persist()


def indexing_policy_error() -> str | None:
    load_indexing_policies()
    return _load_error


def get_indexing_policy(stream_id: str) -> SourceIndexingPolicy:
    with _lock:
        load_indexing_policies()
        if _load_error:
            return SourceIndexingPolicy(mode="disabled")
        existing = _policies.get(stream_id)
        if existing:
            return existing.model_copy(deep=True)
        default: IndexingMode = (
            "on-demand" if get_source_analysis_profile(stream_id) == SMART_CITY_PROFILE_ID else "continuous"
        )
        return SourceIndexingPolicy(mode=default)


def finish_indexing_session(stream_id: str, state: SessionState, reason: str) -> None:
    with _lock:
        load_indexing_policies()
        policy = _policies.get(stream_id)
        if policy and policy.session and policy.session.state in _ACTIVE_SESSION_STATES:
            policy.session.state = state
            policy.session.reason = reason
            policy.session.ended_at = min(datetime.now(UTC), policy.session.deadline_at)
            _persist()


def set_indexing_mode(stream_id: str, mode: IndexingMode) -> SourceIndexingPolicy:
    with _lock:
        load_indexing_policies()
        if _load_error:
            raise ValueError("Repair unreadable indexing policy state before changing indexing")
        finish_indexing_session(stream_id, "cancelled", "indexing-policy-changed")
        prior = get_indexing_policy(stream_id)
        prior.mode = mode
        if mode == "continuous":
            prior.session = None
        prior.revision += 1
        _policies[stream_id] = prior
        _persist()
        return prior.model_copy(deep=True)


def begin_indexing_session(stream_id: str, duration_seconds: int) -> IndexingSession:
    with _lock:
        policy = get_indexing_policy(stream_id)
        if policy.mode != "on-demand" or indexing_policy_error():
            raise ValueError("Finite indexing requires the on-demand policy")
        if is_source_paused(stream_id) or is_source_deleting(stream_id):
            raise ValueError("Resume this source before starting an indexing window")
        if policy.session and policy.session.state in _ACTIVE_SESSION_STATES:
            raise ValueError("An indexing window is already active")
        now = datetime.now(UTC)
        policy.session = IndexingSession(
            id=str(uuid4()),
            requestedAt=now,
            deadlineAt=now + timedelta(seconds=duration_seconds),
            durationSeconds=duration_seconds,
        )
        policy.revision += 1
        _policies[stream_id] = policy
        _persist()
        return policy.session.model_copy(deep=True)


def mark_indexing_started(stream_id: str, session_id: str) -> None:
    with _lock:
        policy = get_indexing_policy(stream_id)
        if policy.session and policy.session.id == session_id and policy.session.state == "starting":
            policy.session.state = "running"
            policy.session.started_at = datetime.now(UTC)
            _policies[stream_id] = policy
            _persist()


def indexing_is_allowed(stream_id: str, session_id: str | None = None) -> bool:
    """Check the durable lease at every start/reconnect; a profile is not a lease."""
    if is_source_paused(stream_id) or is_source_deleting(stream_id):
        return False
    policy = get_indexing_policy(stream_id)
    if policy.mode == "continuous":
        return session_id is None
    session = policy.session
    if policy.mode != "on-demand" or not session or session.state not in _ACTIVE_SESSION_STATES:
        return False
    if datetime.now(UTC) >= session.deadline_at:
        finish_indexing_session(stream_id, "completed", "deadline-reached")
        return False
    return session_id is None or session.id == session_id


def indexing_required_for_analysis(stream_id: str) -> bool:
    """CV health is independent from explicit finite/background indexing."""
    return get_indexing_policy(stream_id).mode == "continuous"


def forget_indexing_policy(stream_id: str) -> None:
    with _lock:
        load_indexing_policies()
        if _policies.pop(stream_id, None) is not None:
            _persist()
