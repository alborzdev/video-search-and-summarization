# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Bounded, process-local terminal state for on-demand verification jobs.

The FastAPI process owns both this registry and its ``BackgroundTasks`` work.
State transitions are protected by one lock so cancellation and the final
pre-publish gate cannot race: cancellation is accepted only before a job has
atomically entered ``publishing``.

This is deliberately not durable.  A process restart loses job state, and a
successful terminal record is not proof that an external sink retained the
document.  The propagated sink receipt states exactly what the transport was
able to acknowledge.
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Mapping, Optional


_CORRELATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_TERMINAL_STATES = frozenset({"completed", "failed", "cancelled"})
_SINK_OUTCOMES = frozenset(
    {"acknowledged", "submitted_unconfirmed", "failed", "unconfirmed"}
)


class JobAlreadyExistsError(ValueError):
    """Raised when a live correlation ID is registered twice."""


class JobCapacityError(RuntimeError):
    """Raised when capacity is exhausted entirely by active jobs."""


class JobIdGenerationError(JobAlreadyExistsError):
    """Raised when bounded server-side ID generation cannot find a free key."""


@dataclass(frozen=True)
class JobHandle:
    """Unexposed registration identity used by one background worker."""

    correlation_id: str
    generation: str


@dataclass
class _Job:
    correlation_id: str
    generation: str
    state: str
    created_at: float
    updated_at: float
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, str]] = None


def _iso_timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )


def _sanitize_sink_receipt(value: Any) -> Dict[str, str]:
    """Return the small public sink receipt shape, never payload or secrets."""

    if not isinstance(value, Mapping):
        return {
            "transport": "unknown",
            "outcome": "unconfirmed",
        }

    transport = str(value.get("transport") or "unknown").strip().lower()
    if not re.fullmatch(r"[a-z0-9_-]{1,32}", transport):
        transport = "unknown"

    outcome = str(value.get("outcome") or "unconfirmed").strip().lower()
    if outcome not in _SINK_OUTCOMES:
        outcome = "unconfirmed"

    receipt = {"transport": transport, "outcome": outcome}
    # These are bounded non-secret transport identifiers.  Raw errors,
    # payloads, prompts, URLs, and VLM output are intentionally never stored.
    for key in ("documentId", "index", "topic", "partition", "offset"):
        candidate = value.get(key)
        if candidate is None:
            continue
        text = str(candidate)
        if len(text) <= 256 and "\n" not in text and "\r" not in text:
            receipt[key] = text
    return receipt


def _sanitize_processing_result(value: Any) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "processingOutcome": "unknown",
        "sinkDelivery": _sanitize_sink_receipt(None),
    }
    if not isinstance(value, Mapping):
        return result

    processing_outcome = str(value.get("processingOutcome") or "unknown")
    if processing_outcome in {"verified", "verification_failed", "unknown"}:
        result["processingOutcome"] = processing_outcome
    result["sinkDelivery"] = _sanitize_sink_receipt(value.get("sinkDelivery"))

    verdict = value.get("verdict")
    if verdict is not None:
        verdict_text = str(verdict)
        if len(verdict_text) <= 64:
            result["verdict"] = verdict_text

    code = value.get("verificationResponseCode")
    if isinstance(code, int) and not isinstance(code, bool):
        result["verificationResponseCode"] = code

    error_source = value.get("errorSource")
    if error_source is not None:
        source_text = str(error_source)
        if len(source_text) <= 128:
            result["errorSource"] = source_text
    return result


class TerminalJobStore:
    """Thread-safe bounded state store for one FastAPI worker process."""

    def __init__(
        self,
        *,
        capacity: int = 1000,
        ttl_seconds: float = 3600,
        clock: Callable[[], float] = time.time,
        id_factory: Callable[[], str] = lambda: f"job-{uuid.uuid4().hex}",
        generation_factory: Callable[[], str] = lambda: uuid.uuid4().hex,
    ) -> None:
        if not isinstance(capacity, int) or isinstance(capacity, bool):
            raise ValueError("capacity must be an integer")
        if capacity < 1 or capacity > 100000:
            raise ValueError("capacity must be between 1 and 100000")
        if isinstance(ttl_seconds, bool) or not isinstance(
            ttl_seconds, (int, float)
        ):
            raise ValueError("ttl_seconds must be a number")
        if ttl_seconds < 1 or ttl_seconds > 604800:
            raise ValueError("ttl_seconds must be between 1 and 604800")

        self._capacity = capacity
        self._ttl_seconds = float(ttl_seconds)
        self._clock = clock
        self._id_factory = id_factory
        self._generation_factory = generation_factory
        self._lock = threading.Lock()
        self._jobs: "OrderedDict[str, _Job]" = OrderedDict()

    @staticmethod
    def validate_correlation_id(correlation_id: str) -> str:
        if not isinstance(correlation_id, str) or not _CORRELATION_ID.fullmatch(
            correlation_id
        ):
            raise ValueError(
                "correlationId must be 1-256 characters using letters, "
                "digits, '.', '_', ':', or '-'"
            )
        return correlation_id

    def _prune_locked(self, now: float) -> None:
        expired = [
            correlation_id
            for correlation_id, job in self._jobs.items()
            if job.state in _TERMINAL_STATES
            and now - job.updated_at >= self._ttl_seconds
        ]
        for correlation_id in expired:
            del self._jobs[correlation_id]

    def _make_room_locked(self) -> None:
        if len(self._jobs) < self._capacity:
            return
        # Capacity is a hard memory bound.  Prefer dropping the oldest
        # terminal receipt; active jobs are never evicted because that would
        # silently remove their cancellation gate.
        for correlation_id, job in self._jobs.items():
            if job.state in _TERMINAL_STATES:
                del self._jobs[correlation_id]
                return
        raise JobCapacityError("on-demand verification job capacity exhausted")

    def register(self) -> JobHandle:
        """Create a server-keyed job and return its unexposed worker handle."""

        now = self._clock()
        with self._lock:
            self._prune_locked(now)
            correlation_id = ""
            for _ in range(8):
                try:
                    candidate = self.validate_correlation_id(self._id_factory())
                except ValueError as exc:
                    raise JobIdGenerationError(
                        "invalid server-generated job ID"
                    ) from exc
                if candidate not in self._jobs:
                    correlation_id = candidate
                    break
            if not correlation_id:
                raise JobIdGenerationError(
                    "unable to allocate an on-demand verification job ID"
                )
            generation = self._generation_factory()
            if (
                not isinstance(generation, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", generation)
            ):
                raise JobIdGenerationError("invalid internal job generation")
            self._make_room_locked()
            self._jobs[correlation_id] = _Job(
                correlation_id=correlation_id,
                generation=generation,
                state="queued",
                created_at=now,
                updated_at=now,
            )
            return JobHandle(correlation_id, generation)

    def mark_running(self, handle: JobHandle) -> bool:
        with self._lock:
            job = self._jobs.get(handle.correlation_id)
            if (
                job is None
                or job.generation != handle.generation
                or job.state != "queued"
            ):
                return False
            job.state = "running"
            job.updated_at = self._clock()
            return True

    def begin_publish(self, handle: JobHandle) -> bool:
        """Atomically close the cancellation window before a sink call."""

        with self._lock:
            job = self._jobs.get(handle.correlation_id)
            if (
                job is None
                or job.generation != handle.generation
                or job.state != "running"
            ):
                return False
            job.state = "publishing"
            job.updated_at = self._clock()
            return True

    def complete(self, handle: JobHandle, result: Any) -> bool:
        with self._lock:
            job = self._jobs.get(handle.correlation_id)
            if (
                job is None
                or job.generation != handle.generation
                or job.state != "publishing"
            ):
                return False
            sanitized = _sanitize_processing_result(result)
            sink_outcome = sanitized["sinkDelivery"]["outcome"]
            job.state = "failed" if sink_outcome == "failed" else "completed"
            job.result = sanitized
            job.error = None
            job.updated_at = self._clock()
            return True

    def fail(self, handle: JobHandle, error_code: str) -> bool:
        safe_code = str(error_code).strip().lower()
        if not re.fullmatch(r"[a-z0-9_-]{1,64}", safe_code):
            safe_code = "processing_failed"
        with self._lock:
            job = self._jobs.get(handle.correlation_id)
            if (
                job is None
                or job.generation != handle.generation
                or job.state in _TERMINAL_STATES
            ):
                return False
            job.state = "failed"
            job.error = {"code": safe_code}
            job.result = None
            job.updated_at = self._clock()
            return True

    def cancel(self, correlation_id: str) -> Optional[Dict[str, Any]]:
        now = self._clock()
        with self._lock:
            self._prune_locked(now)
            job = self._jobs.get(correlation_id)
            if job is None:
                return None
            accepted = job.state in {"queued", "running"}
            if accepted:
                job.state = "cancelled"
                job.result = None
                job.error = None
                job.updated_at = now
            snapshot = self._snapshot_locked(job)
            snapshot["cancellationAccepted"] = accepted
            return snapshot

    def get(self, correlation_id: str) -> Optional[Dict[str, Any]]:
        now = self._clock()
        with self._lock:
            self._prune_locked(now)
            job = self._jobs.get(correlation_id)
            if job is None:
                return None
            return self._snapshot_locked(job)

    @staticmethod
    def _snapshot_locked(job: _Job) -> Dict[str, Any]:
        snapshot: Dict[str, Any] = {
            "correlationId": job.correlation_id,
            "state": job.state,
            "terminal": job.state in _TERMINAL_STATES,
            "createdAt": _iso_timestamp(job.created_at),
            "updatedAt": _iso_timestamp(job.updated_at),
        }
        if job.result is not None:
            snapshot["result"] = dict(job.result)
            snapshot["result"]["sinkDelivery"] = dict(
                job.result["sinkDelivery"]
            )
        if job.error is not None:
            snapshot["error"] = dict(job.error)
        return snapshot
