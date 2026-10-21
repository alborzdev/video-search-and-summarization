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

"""Tests for the Agent-owned Thor visual workload admission boundary."""

import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
from unittest.mock import MagicMock

from fastapi import FastAPI
import httpx
import pytest

from vss_agents.api.thor_workload_admission import CaptionSession
from vss_agents.api.thor_workload_admission import ThorVisualWorkloadAdmission
from vss_agents.api.thor_workload_admission import ThorWorkloadAdmissionError


class FakeVisualAdmission(ThorVisualWorkloadAdmission):
    """Avoid HTTP while exercising the lease sequencing itself."""

    def __init__(self, history_directory: str | None = None) -> None:
        super().__init__(history_directory=history_directory)
        self.events: list[str] = []
        self.sessions: list[CaptionSession] = []
        self.restored_sessions: list[CaptionSession] = []

    async def _ensure_vlm_ready(self, workload: str) -> None:
        self.events.append(f"ready:{workload}")

    async def _active_caption_sessions(self, workload: str) -> list[CaptionSession]:
        self.events.append(f"sources:{workload}")
        return self.sessions

    async def _suspend_captioning(self, source_id: str, workload: str) -> None:
        self.events.append(f"suspend:{source_id}:{workload}")

    async def _restore_captioning(self, sessions: list[CaptionSession]) -> None:
        self.restored_sessions.extend(sessions)
        self.events.extend(f"restore:{session.source_id}" for session in sessions)


class FailingRestoreAdmission(FakeVisualAdmission):
    """Exercises cleanup failures without probing external services."""

    async def _restore_captioning(self, sessions: list[CaptionSession]) -> None:
        raise RuntimeError("caption restore failed")


@pytest.mark.asyncio
async def test_agent_lease_yields_and_restores_each_active_caption_source():
    admission = FakeVisualAdmission()
    admission.sessions = [
        CaptionSession("camera-a", ("forklift near person",), "warehouse safety"),
        CaptionSession("camera-b", ("vehicle stopped",), "traffic safety"),
    ]

    async with admission.reserve("current_visual_question"):
        admission.events.append("operation")

    assert admission.events == [
        "ready:current_visual_question",
        "sources:current_visual_question",
        "suspend:camera-a:current_visual_question",
        "suspend:camera-b:current_visual_question",
        "operation",
        "restore:camera-a",
        "restore:camera-b",
    ]
    assert admission.restored_sessions == admission.sessions


def test_saved_live_caption_configuration_is_preserved_exactly(tmp_path: Path):
    (tmp_path / "camera-a.json").write_text(
        json.dumps(
            {
                "events": ["forklift near person", "blocked emergency exit"],
                "scenario": "operator-selected warehouse safety",
                "sourceKind": "live",
            }
        ),
        encoding="utf-8",
    )
    admission = ThorVisualWorkloadAdmission(history_directory=str(tmp_path))

    session = admission._caption_session("camera-a", "Warehouse north dock")

    assert session == CaptionSession(
        source_id="camera-a",
        events=("forklift near person", "blocked emergency exit"),
        scenario="operator-selected warehouse safety",
    )


@pytest.mark.parametrize(
    ("source_id", "source_name", "history_value", "expected_scenario"),
    [
        ("traffic-a", "Road intersection 7", None, "traffic monitoring"),
        ("warehouse-a", "Loading dock", "{broken", "warehouse monitoring"),
        ("camera-a", "Camera A", '{"sourceKind":"replay"}', "activity monitoring"),
    ],
)
def test_missing_or_invalid_history_uses_scenario_aware_defaults(
    tmp_path: Path,
    source_id: str,
    source_name: str,
    history_value: str | None,
    expected_scenario: str,
):
    if history_value is not None:
        (tmp_path / f"{source_id}.json").write_text(history_value, encoding="utf-8")
    admission = ThorVisualWorkloadAdmission(history_directory=str(tmp_path))

    assert admission._caption_session(source_id, source_name).scenario == expected_scenario


@pytest.mark.asyncio
async def test_restore_request_uses_the_saved_session_payload(monkeypatch: pytest.MonkeyPatch):
    requests: list[dict[str, object]] = []

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, _url: str, json: dict[str, object]):
            requests.append(json)
            return httpx.Response(200)

    monkeypatch.setattr(
        "vss_agents.api.thor_workload_admission.httpx.AsyncClient",
        lambda **_kwargs: FakeClient(),
    )
    admission = ThorVisualWorkloadAdmission(model_name="cosmos-test")
    session = CaptionSession(
        source_id="camera-a",
        events=("forklift near person", "blocked emergency exit"),
        scenario="operator-selected warehouse safety",
    )

    await admission._restore_captioning([session])

    assert requests == [
        {
            "enable_qa": True,
            "events": ["forklift near person", "blocked emergency exit"],
            "id": "camera-a",
            "model": "cosmos-test",
            "objects_of_interest": [],
            "scenario": "operator-selected warehouse safety",
        }
    ]


@pytest.mark.asyncio
async def test_agent_lease_releases_lock_when_caption_restore_raises():
    admission = FailingRestoreAdmission()

    with pytest.raises(RuntimeError, match="caption restore failed"):
        async with admission.reserve("current_visual_question"):
            pass

    with pytest.raises(RuntimeError, match="caption restore failed"):
        async with admission.reserve("evidence_analysis"):
            pass


@pytest.mark.asyncio
async def test_agent_lease_refuses_a_competing_direct_request_without_queueing():
    admission = FakeVisualAdmission()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def hold_lease() -> None:
        async with admission.reserve("current_visual_question"):
            entered.set()
            await release.wait()

    task = asyncio.create_task(hold_lease())
    await entered.wait()
    with pytest.raises(ThorWorkloadAdmissionError) as error:
        async with admission.reserve("evidence_analysis"):
            pass
    release.set()
    await task

    assert error.value.status_code == 503
    assert error.value.code == "LOCAL_COSMOS_RESERVATION_ACTIVE"
    assert error.value.response_body()["admission"] == {
        "decision": "block",
        "reasonCode": "LOCAL_COSMOS_RESERVATION_ACTIVE",
        "requiredAction": "Wait for the local visual lane to become available and try again.",
        "workload": "evidence_analysis",
    }


@pytest.mark.asyncio
async def test_active_live_alert_is_a_structured_conflict(tmp_path: Path):
    (tmp_path / ".live-alert-rule-1.json").write_text('{"sourceId":"camera-a"}', encoding="utf-8")
    admission = FakeVisualAdmission(str(tmp_path))

    with pytest.raises(ThorWorkloadAdmissionError) as error:
        async with admission.reserve("evidence_analysis"):
            pass

    assert error.value.status_code == 409
    assert error.value.code == "LIVE_ALERT_RESERVATION_ACTIVE"
    assert (
        error.value.response_body()["error"] == "A continuous live VLM alert currently owns the exclusive Cosmos lane."
    )


class RejectingAdmission:
    @asynccontextmanager
    async def reserve(self, workload: str):
        raise ThorWorkloadAdmissionError(
            409,
            "LIVE_ALERT_RESERVATION_ACTIVE",
            "A continuous live VLM alert currently owns the exclusive Cosmos lane.",
            workload,  # type: ignore[arg-type]
        )
        yield


@pytest.mark.asyncio
async def test_evidence_endpoint_returns_admission_failure_before_tool_execution():
    evidence_analysis = pytest.importorskip("vss_agents.api.evidence_analysis")
    app = FastAPI()
    evidence_analysis.register_evidence_analysis_routes(app, MagicMock(), RejectingAdmission())  # type: ignore[arg-type]
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/evidence-analysis",
            json={
                "query": "What is visible?",
                "evidence": [
                    {
                        "client_id": "camera-a:1",
                        "sensor_id": "camera-a",
                        "source_name": "Camera A",
                        "start_time": "2026-08-17T14:00:00Z",
                        "end_time": "2026-08-17T14:00:10Z",
                    }
                ],
            },
        )

    assert response.status_code == 409
    assert response.json()["code"] == "LIVE_ALERT_RESERVATION_ACTIVE"
    assert response.json()["admission"]["workload"] == "evidence_analysis"
