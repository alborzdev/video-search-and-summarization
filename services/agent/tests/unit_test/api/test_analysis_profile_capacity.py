# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from vss_agents.api.analysis_profile_capacity import AnalysisProfileCapacityError
from vss_agents.api.analysis_profile_capacity import claim_source_analysis_profile_capacity
from vss_agents.api.analysis_profile_capacity import commit_analysis_profile_capacity_reservation
from vss_agents.api.analysis_profile_capacity import release_analysis_profile_capacity_reservation
from vss_agents.api.analysis_profile_capacity import reserve_analysis_profile_capacity
from vss_agents.api.analysis_profiles import SEMANTIC_PROFILE_ID
from vss_agents.api.analysis_profiles import TRAFFIC_PROFILE_ID
from vss_agents.api.analysis_profiles import WAREHOUSE_PROFILE_ID
from vss_agents.api.analysis_profiles import require_analysis_profile
from vss_agents.api.source_analysis_state import _detection_disabled_sources
from vss_agents.api.source_analysis_state import _paused_sources
from vss_agents.api.source_analysis_state import _source_analysis_profiles
from vss_agents.api.source_analysis_state import _source_kinds
from vss_agents.api.source_analysis_state import get_source_analysis_profile
from vss_agents.api.source_analysis_state import load_source_analysis_state
from vss_agents.api.source_analysis_state import set_source_kind
from vss_agents.api.source_analysis_state import source_ids_with_analysis_profile


@pytest.fixture(autouse=True)
def isolated_source_analysis_state(tmp_path, monkeypatch):
    monkeypatch.setenv("VSS_SOURCE_ANALYSIS_STATE_FILE", str(tmp_path / "source-analysis-state.json"))
    load_source_analysis_state(force=True)
    _paused_sources.clear()
    _detection_disabled_sources.clear()
    _source_analysis_profiles.clear()
    _source_kinds.clear()
    yield
    _paused_sources.clear()
    _detection_disabled_sources.clear()
    _source_analysis_profiles.clear()
    _source_kinds.clear()


def test_finite_profile_rejects_a_second_source_with_structured_conflict():
    claim_source_analysis_profile_capacity("intersection-a", TRAFFIC_PROFILE_ID)

    with pytest.raises(AnalysisProfileCapacityError) as exc_info:
        claim_source_analysis_profile_capacity("intersection-b", TRAFFIC_PROFILE_ID)

    assert exc_info.value.detail == {
        "code": "analysis_profile_capacity_exhausted",
        "maxSources": 1,
        "occupiedSourceIds": ["intersection-a"],
        "pendingReservations": 0,
        "profileId": TRAFFIC_PROFILE_ID,
    }
    assert get_source_analysis_profile("intersection-a") == TRAFFIC_PROFILE_ID
    assert get_source_analysis_profile("intersection-b") != TRAFFIC_PROFILE_ID


def test_same_source_can_reapply_its_existing_finite_profile():
    claim_source_analysis_profile_capacity("intersection-a", TRAFFIC_PROFILE_ID)

    claim_source_analysis_profile_capacity("intersection-a", TRAFFIC_PROFILE_ID)

    assert get_source_analysis_profile("intersection-a") == TRAFFIC_PROFILE_ID


def test_concurrent_claims_cannot_overbook_a_finite_profile():
    def claim(source_id: str) -> bool:
        try:
            claim_source_analysis_profile_capacity(source_id, TRAFFIC_PROFILE_ID)
        except AnalysisProfileCapacityError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(claim, ("intersection-a", "intersection-b")))

    assert sorted(results) == [False, True]
    assignments = [
        source_id
        for source_id in ("intersection-a", "intersection-b")
        if get_source_analysis_profile(source_id) == TRAFFIC_PROFILE_ID
    ]
    assert len(assignments) == 1


def test_add_reservation_blocks_another_source_until_it_is_committed():
    reservation = reserve_analysis_profile_capacity(TRAFFIC_PROFILE_ID)
    try:
        with pytest.raises(AnalysisProfileCapacityError) as exc_info:
            reserve_analysis_profile_capacity(TRAFFIC_PROFILE_ID)

        assert exc_info.value.detail == {
            "code": "analysis_profile_capacity_exhausted",
            "maxSources": 1,
            "occupiedSourceIds": [],
            "pendingReservations": 1,
            "profileId": TRAFFIC_PROFILE_ID,
        }
        commit_analysis_profile_capacity_reservation(reservation, "intersection-a")
    finally:
        release_analysis_profile_capacity_reservation(reservation)

    assert get_source_analysis_profile("intersection-a") == TRAFFIC_PROFILE_ID


def test_known_legacy_sources_count_as_the_historical_warehouse_profile():
    set_source_kind("legacy-camera", "live")

    assert source_ids_with_analysis_profile(WAREHOUSE_PROFILE_ID) == {"legacy-camera"}


def test_unlimited_profile_does_not_reject_additional_sources(monkeypatch):
    unlimited_semantic = replace(require_analysis_profile(SEMANTIC_PROFILE_ID), max_sources=0)
    monkeypatch.setattr(
        "vss_agents.api.analysis_profile_capacity.require_analysis_profile",
        lambda _profile_id: unlimited_semantic,
    )

    claim_source_analysis_profile_capacity("camera-a", SEMANTIC_PROFILE_ID)
    claim_source_analysis_profile_capacity("camera-b", SEMANTIC_PROFILE_ID)

    assert get_source_analysis_profile("camera-a") == SEMANTIC_PROFILE_ID
    assert get_source_analysis_profile("camera-b") == SEMANTIC_PROFILE_ID
