# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Atomic admission for finite-source analysis profiles.

The Thor-local agent is a single service process. A process-wide lock protects
the durable profile assignment and temporary reprocessing reservations as one
critical section, so concurrent HTTP requests cannot both claim a finite
DeepStream worker slot. A reservation deliberately remains in memory: a
process restart terminates the in-flight operation, while its durable source
profile remains the last successfully committed assignment.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from uuid import uuid4

from vss_agents.api.analysis_profiles import require_analysis_profile
from vss_agents.api.source_analysis_state import set_source_analysis_profile
from vss_agents.api.source_analysis_state import source_ids_with_analysis_profile


@dataclass(frozen=True)
class AnalysisProfileCapacityReservation:
    """A short-lived admission held while a source transition is in progress."""

    profile_id: str
    reservation_id: str
    source_id: str | None


class AnalysisProfileCapacityError(RuntimeError):
    """Structured operator-safe reason a source cannot claim a profile."""

    def __init__(
        self,
        *,
        code: str,
        max_sources: int,
        occupied_source_ids: list[str],
        pending_reservations: int,
        profile_id: str,
    ) -> None:
        self.code = code
        self.max_sources = max_sources
        self.occupied_source_ids = occupied_source_ids
        self.pending_reservations = pending_reservations
        self.profile_id = profile_id
        super().__init__(code)

    @property
    def detail(self) -> dict[str, int | list[str] | str]:
        return {
            "code": self.code,
            "maxSources": self.max_sources,
            "occupiedSourceIds": self.occupied_source_ids,
            "pendingReservations": self.pending_reservations,
            "profileId": self.profile_id,
        }


_capacity_lock = RLock()
_reservations: dict[str, AnalysisProfileCapacityReservation] = {}
_PENDING_RESERVATION_PREFIX = "reservation:"


def _reservation_occupant(reservation: AnalysisProfileCapacityReservation) -> str:
    return reservation.source_id or f"{_PENDING_RESERVATION_PREFIX}{reservation.reservation_id}"


def _occupied_source_ids(
    profile_id: str,
    *,
    exclude_reservation_id: str | None = None,
) -> set[str]:
    occupied = set(source_ids_with_analysis_profile(profile_id))
    occupied.update(
        _reservation_occupant(reservation)
        for reservation in _reservations.values()
        if reservation.profile_id == profile_id and reservation.reservation_id != exclude_reservation_id
    )
    return occupied


def _capacity_conflict_occupants(occupied: set[str]) -> tuple[list[str], int]:
    """Split real source IDs from uncommitted add reservations for HTTP detail."""
    pending_reservations = sum(item.startswith(_PENDING_RESERVATION_PREFIX) for item in occupied)
    source_ids = sorted(item for item in occupied if not item.startswith(_PENDING_RESERVATION_PREFIX))
    return source_ids, pending_reservations


def _assert_capacity(
    profile_id: str,
    source_id: str,
    *,
    exclude_reservation_id: str | None = None,
) -> None:
    profile = require_analysis_profile(profile_id)
    if profile.max_sources <= 0:
        return
    occupied = _occupied_source_ids(profile.id, exclude_reservation_id=exclude_reservation_id)
    occupied.add(source_id)
    if len(occupied) <= profile.max_sources:
        return
    occupied_source_ids, pending_reservations = _capacity_conflict_occupants(occupied - {source_id})
    raise AnalysisProfileCapacityError(
        code="analysis_profile_capacity_exhausted",
        max_sources=profile.max_sources,
        occupied_source_ids=occupied_source_ids,
        pending_reservations=pending_reservations,
        profile_id=profile.id,
    )


def _assert_source_is_not_transitioning(source_id: str) -> None:
    for reservation in _reservations.values():
        if reservation.source_id == source_id:
            profile = require_analysis_profile(reservation.profile_id)
            occupied_source_ids, pending_reservations = _capacity_conflict_occupants(_occupied_source_ids(profile.id))
            raise AnalysisProfileCapacityError(
                code="analysis_profile_transition_in_progress",
                max_sources=profile.max_sources,
                occupied_source_ids=occupied_source_ids,
                pending_reservations=pending_reservations,
                profile_id=profile.id,
            )


def claim_source_analysis_profile_capacity(source_id: str, profile_id: str) -> None:
    """Atomically assign a source to a profile after checking finite capacity."""
    with _capacity_lock:
        _assert_source_is_not_transitioning(source_id)
        _assert_capacity(profile_id, source_id)
        set_source_analysis_profile(source_id, profile_id)


def reserve_analysis_profile_capacity(
    profile_id: str,
    *,
    source_id: str | None = None,
) -> AnalysisProfileCapacityReservation:
    """Reserve one profile slot across an async VST or detector transition."""
    with _capacity_lock:
        if source_id is not None:
            _assert_source_is_not_transitioning(source_id)
        reservation = AnalysisProfileCapacityReservation(
            profile_id=require_analysis_profile(profile_id).id,
            reservation_id=uuid4().hex,
            source_id=source_id,
        )
        _assert_capacity(reservation.profile_id, _reservation_occupant(reservation))
        _reservations[reservation.reservation_id] = reservation
        return reservation


def commit_analysis_profile_capacity_reservation(
    reservation: AnalysisProfileCapacityReservation,
    source_id: str,
) -> None:
    """Atomically replace a reservation with the durable source assignment."""
    with _capacity_lock:
        current = _reservations.get(reservation.reservation_id)
        if current != reservation:
            raise RuntimeError("Analysis profile capacity reservation is no longer active")
        _assert_capacity(
            reservation.profile_id,
            source_id,
            exclude_reservation_id=reservation.reservation_id,
        )
        set_source_analysis_profile(source_id, reservation.profile_id)
        _reservations.pop(reservation.reservation_id, None)


def release_analysis_profile_capacity_reservation(reservation: AnalysisProfileCapacityReservation) -> None:
    """Release an uncommitted reservation after a failed transition."""
    with _capacity_lock:
        if _reservations.get(reservation.reservation_id) == reservation:
            _reservations.pop(reservation.reservation_id, None)
