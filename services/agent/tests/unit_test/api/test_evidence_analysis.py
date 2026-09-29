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

"""Unit tests for grounded selected-evidence analysis."""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage
from nat.builder.framework_enum import LLMFrameworkEnum
from pydantic import ValidationError
import pytest

from lib.knowledge.schema import Chunk
from lib.knowledge.schema import RetrievalResult
from vss_agents.api import evidence_analysis as evidence_analysis_module
from vss_agents.api.evidence_analysis import EvidenceAnalysisRequest
from vss_agents.api.evidence_analysis import EvidenceClipRequest
from vss_agents.api.evidence_analysis import analyze_evidence


def _request(question: str | None = None) -> EvidenceAnalysisRequest:
    return EvidenceAnalysisRequest(
        query="person near a mobile robot",
        question=question,
        evidence=[
            {
                "client_id": "sensor-a:first",
                "sensor_id": "sensor-a",
                "source_name": "Assembly floor",
                "start_time": "2026-08-17T14:00:00Z",
                "end_time": "2026-08-17T14:00:10Z",
                "search_description": "Person beside a robot",
                "match_type": "Semantic video match",
            },
            {
                "client_id": "sensor-b:second",
                "sensor_id": "sensor-b",
                "source_name": "Loading dock",
                "start_time": "2026-08-17T14:03:00Z",
                "end_time": "2026-08-17T14:03:12Z",
                "search_description": "Robot crossing the floor",
                "match_type": "Detector match",
            },
        ],
    )


@pytest.mark.asyncio
async def test_analyze_evidence_inspects_every_clip_and_returns_supported_claims(monkeypatch):
    monkeypatch.setenv("LLM_MODEL_TYPE", "vllm")
    monkeypatch.setenv("EVIDENCE_CAPTION_SEARCH_ENABLED", "false")
    monkeypatch.setenv("EVIDENCE_ALLOW_FRESH_INSPECTION_WHILE_BUSY", "true")
    visual_tool = MagicMock()
    visual_tool.ainvoke = AsyncMock(
        side_effect=[
            "A person in dark clothing walks beside a wheeled robot.",
            "A wheeled robot moves through the loading area; no person is visible.",
        ]
    )
    synthesis_llm = MagicMock()
    synthesis_llm.bind.return_value = synthesis_llm
    synthesis_llm.ainvoke = AsyncMock(
        return_value=AIMessage(
            content=(
                '{"summary":"A person is visible near the robot in one of the two selected clips.",'
                '"observations":[{"text":"A person walks beside a wheeled robot.","evidence_ids":["E1"]},'
                '{"text":"The robot also appears without a visible person.","evidence_ids":["E2"]}],'
                '"interpretations":[{"text":"The selected clips may show different operating contexts.",'
                '"evidence_ids":["E1","E2"]}],'
                '"timeline":[{"evidence_id":"E2","label":"Robot crosses loading area"},'
                '{"evidence_id":"E1","label":"Person walks beside robot"}],'
                '"suggested_questions":["Was the person in the robot path?"]}'
            )
        )
    )
    builder = MagicMock()
    builder.get_tool = AsyncMock(return_value=visual_tool)
    builder.get_llm = AsyncMock(return_value=synthesis_llm)

    result = await analyze_evidence(builder, _request())

    assert result.status == "complete"
    synthesis_llm.bind.assert_called_once()
    response_format = synthesis_llm.bind.call_args.kwargs["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["schema"]["required"] == ["summary"]
    assert set(result.timings_ms) == {"inspection", "synthesis", "total"}
    assert all(value >= 0 for value in result.timings_ms.values())
    assert result.timings_ms["total"] >= result.timings_ms["inspection"]
    assert result.summary == "A person is visible near the robot in one of the two selected clips."
    assert [claim.evidence_ids for claim in result.observations] == [["E1"], ["E2"]]
    assert [entry.evidence_id for entry in result.timeline] == ["E1", "E2"]
    assert result.timeline[0].label == result.evidence[0].observation[:180]
    assert [claim.text for claim in result.observations] == [item.observation for item in result.evidence]
    assert [item.client_id for item in result.evidence] == ["sensor-a:first", "sensor-b:second"]
    assert {item.inspection_source for item in result.evidence} == {"fresh_cosmos_inspection"}
    assert visual_tool.ainvoke.await_count == 2
    builder.get_tool.assert_awaited_once_with(
        "video_understanding_iso",
        wrapper_type=LLMFrameworkEnum.LANGCHAIN,
    )
    builder.get_llm.assert_awaited_once_with(
        "vllm_llm",
        wrapper_type=LLMFrameworkEnum.LANGCHAIN,
    )


@pytest.mark.asyncio
async def test_synthesis_cannot_omit_clips_or_return_unqualified_inferences(monkeypatch):
    monkeypatch.setenv("LLM_MODEL_TYPE", "vllm")
    monkeypatch.setenv("EVIDENCE_CAPTION_SEARCH_ENABLED", "false")
    monkeypatch.setenv("EVIDENCE_ALLOW_FRESH_INSPECTION_WHILE_BUSY", "true")
    visual_tool = MagicMock()
    visual_tool.ainvoke = AsyncMock(
        side_effect=[
            "One person gestures beside a robot.",
            "Two people are visible beside a stationary robot.",
        ]
    )
    synthesis_llm = MagicMock()
    synthesis_llm.bind.return_value = synthesis_llm
    synthesis_llm.ainvoke = AsyncMock(
        return_value=AIMessage(
            content=(
                '{"summary":"A person is visible near a robot.",'
                '"observations":[{"text":"E1 gestures beside a robot.","evidence_ids":["E1"]}],'
                '"interpretations":[{"text":"The man is the robot operator.","evidence_ids":["E1"]},'
                '{"text":"The scene may indicate active work.","evidence_ids":["E2"]}],'
                '"timeline":[],"suggested_questions":["Why is the robot there?",'
                '"Is the robot operational?","How many people are visible in each clip?"]}'
            )
        )
    )
    builder = MagicMock()
    builder.get_tool = AsyncMock(return_value=visual_tool)
    builder.get_llm = AsyncMock(return_value=synthesis_llm)

    result = await analyze_evidence(builder, _request("What is the man doing?"))

    assert [claim.evidence_ids for claim in result.observations] == [["E1"], ["E2"]]
    assert result.observations[1].text == "Two people are visible beside a stationary robot."
    assert result.interpretations == []
    assert result.observations[0].text == result.evidence[0].observation
    assert result.suggested_questions == [
        "What people and objects are visible in each clip?",
        "How do the visible actions differ between the clips?",
    ]
    system_prompt = synthesis_llm.ainvoke.await_args.args[0][0].content
    assert "clip labels, never people" in system_prompt
    assert "without assuming the subjects are the same" in system_prompt
    assert "spatial prepositions" in system_prompt


@pytest.mark.asyncio
async def test_follow_up_is_reinspected_and_synthesis_cannot_cite_unknown_evidence(monkeypatch):
    monkeypatch.setenv("LLM_MODEL_TYPE", "vllm")
    monkeypatch.setenv("EVIDENCE_CAPTION_SEARCH_ENABLED", "false")
    monkeypatch.setenv("EVIDENCE_ALLOW_FRESH_INSPECTION_WHILE_BUSY", "true")
    visual_tool = MagicMock()
    visual_tool.ainvoke = AsyncMock(side_effect=["No contact is visible.", "No contact is visible."])
    synthesis_llm = MagicMock()
    synthesis_llm.bind.return_value = synthesis_llm
    synthesis_llm.ainvoke = AsyncMock(
        return_value=AIMessage(
            content=(
                '{"summary":"No contact is visible in the selected clips.",'
                '"observations":[{"text":"No contact is visible.","evidence_ids":["E1","E99"]}],'
                '"interpretations":[],"timeline":[],"suggested_questions":[]}'
            )
        )
    )
    builder = MagicMock()
    builder.get_tool = AsyncMock(return_value=visual_tool)
    builder.get_llm = AsyncMock(return_value=synthesis_llm)

    result = await analyze_evidence(builder, _request("Did the person touch the robot?"))

    assert result.question == "Did the person touch the robot?"
    assert result.observations[0].evidence_ids == ["E1"]
    for index, call in enumerate(visual_tool.ainvoke.await_args_list, start=1):
        prompt = call.kwargs["input"]["user_prompt"]
        assert f"single video clip, labeled E{index}" in prompt
        assert "No other clip is provided" in prompt
        assert "Did the person touch the robot?" in prompt
        assert "a separate step will compare the observations" in prompt
        assert f"Report only what is visible in E{index}" in prompt
    assert "Did the person touch the robot?" in synthesis_llm.ainvoke.await_args.args[0][1].content


@pytest.mark.asyncio
async def test_cross_clip_identity_question_returns_explicit_non_identification(monkeypatch):
    monkeypatch.setenv("EVIDENCE_CAPTION_SEARCH_ENABLED", "false")
    monkeypatch.setenv("EVIDENCE_ALLOW_FRESH_INSPECTION_WHILE_BUSY", "true")
    visual_tool = MagicMock()
    visual_tool.ainvoke = AsyncMock(
        side_effect=[
            "A pedestrian in a white top crosses from right to left.",
            "A pedestrian in a white shirt walks through a crosswalk.",
        ]
    )
    builder = MagicMock()
    builder.get_tool = AsyncMock(return_value=visual_tool)
    builder.get_llm = AsyncMock()

    result = await analyze_evidence(
        builder,
        _request("Is the pedestrian in E1 the same person as in E2?"),
    )

    assert result.status == "complete"
    assert "cannot establish" in result.summary
    assert "no continuous tracked identity" in result.summary
    assert [claim.evidence_ids for claim in result.observations] == [["E1"], ["E2"]]
    assert result.interpretations == []
    assert all("same person" not in question.lower() for question in result.suggested_questions)
    builder.get_llm.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_synthesis_degrades_to_cited_visual_observations(monkeypatch):
    monkeypatch.setenv("LLM_MODEL_TYPE", "vllm")
    monkeypatch.setenv("EVIDENCE_CAPTION_SEARCH_ENABLED", "false")
    monkeypatch.setenv("EVIDENCE_ALLOW_FRESH_INSPECTION_WHILE_BUSY", "true")
    visual_tool = MagicMock()
    visual_tool.ainvoke = AsyncMock(side_effect=["Visible observation one.", "Visible observation two."])
    synthesis_llm = MagicMock()
    synthesis_llm.bind.return_value = synthesis_llm
    synthesis_llm.ainvoke = AsyncMock(return_value=AIMessage(content="not json"))
    builder = MagicMock()
    builder.get_tool = AsyncMock(return_value=visual_tool)
    builder.get_llm = AsyncMock(return_value=synthesis_llm)

    result = await analyze_evidence(builder, _request())

    assert result.status == "degraded"
    assert [claim.evidence_ids for claim in result.observations] == [["E1"], ["E2"]]
    assert result.interpretations == []
    assert result.warning and "synthesis was unavailable" in result.warning


@pytest.mark.asyncio
async def test_analyze_evidence_reuses_timestamped_cosmos_captions(monkeypatch):
    monkeypatch.setenv("LLM_MODEL_TYPE", "vllm")
    retriever = MagicMock()
    retriever.retrieve = AsyncMock(
        side_effect=[
            RetrievalResult(
                backend="es_caption",
                chunks=[
                    Chunk(
                        chunk_id="one",
                        content=(
                            '```json\n[{"type":"robot movement","description":'
                            '"A wheeled robot moves beside a person."}]\n```'
                        ),
                        score=0,
                        metadata={"start_seconds": 1786975200.0},
                    )
                ],
            ),
            RetrievalResult(
                backend="es_caption",
                chunks=[
                    Chunk(
                        chunk_id="two",
                        content=(
                            '```json\n[{"type":"robot movement","description":'
                            '"The robot crosses the loading area."}]\n```'
                        ),
                        score=0,
                        metadata={"start_seconds": 1786975380.0},
                    )
                ],
            ),
        ]
    )
    monkeypatch.setattr(evidence_analysis_module, "_caption_retriever", lambda: retriever)
    monkeypatch.setattr(
        evidence_analysis_module,
        "get_stream_id",
        AsyncMock(side_effect=["stream-a", "stream-b"]),
    )
    synthesis_llm = MagicMock()
    synthesis_llm.bind.return_value = synthesis_llm
    synthesis_llm.ainvoke = AsyncMock(
        return_value=AIMessage(
            content=(
                '{"summary":"The retained captions show robot activity.",'
                '"observations":[{"text":"A robot is visible.","evidence_ids":["E1","E2"]}],'
                '"interpretations":[],"timeline":[],"suggested_questions":[]}'
            )
        )
    )
    builder = MagicMock()
    builder.get_tool = AsyncMock()
    builder.get_llm = AsyncMock(return_value=synthesis_llm)

    result = await analyze_evidence(builder, _request())

    assert result.status == "complete"
    assert {item.inspection_source for item in result.evidence} == {"retained_cosmos_caption"}
    assert result.evidence[0].observation == "robot movement: A wheeled robot moves beside a person."
    builder.get_tool.assert_not_awaited()
    assert retriever.retrieve.await_count == 2


@pytest.mark.asyncio
async def test_single_fresh_clip_answers_without_a_second_model_call(monkeypatch):
    monkeypatch.setenv("EVIDENCE_CAPTION_SEARCH_ENABLED", "false")
    monkeypatch.setenv("EVIDENCE_ALLOW_FRESH_INSPECTION_WHILE_BUSY", "true")
    request = _request("Did the person touch the robot?")
    request.evidence = request.evidence[:1]
    observation = "The person reaches toward the robot; contact is unclear."
    visual_tool = MagicMock()
    visual_tool.ainvoke = AsyncMock(return_value=observation)
    builder = MagicMock()
    builder.get_tool = AsyncMock(return_value=visual_tool)
    builder.get_llm = AsyncMock()

    result = await analyze_evidence(builder, request)

    assert result.status == "complete"
    assert result.summary == observation
    assert result.question == request.question
    assert result.observations[0].evidence_ids == ["E1"]
    assert result.evidence[0].client_id == request.evidence[0].client_id
    assert result.interpretations == []
    assert result.timeline[0].start_time == request.evidence[0].start_time
    assert request.question in visual_tool.ainvoke.await_args.kwargs["input"]["user_prompt"]
    assert request.query not in visual_tool.ainvoke.await_args.kwargs["input"]["user_prompt"]
    builder.get_llm.assert_not_awaited()


@pytest.mark.asyncio
async def test_single_retained_caption_still_synthesizes_an_answer(monkeypatch):
    request = _request("Did the person touch the robot?")
    request.evidence = request.evidence[:1]
    inspection = evidence_analysis_module.VisualInspection(
        evidence_id="E1",
        client_id=request.evidence[0].client_id,
        source_name=request.evidence[0].source_name,
        start_time=request.evidence[0].start_time,
        end_time=request.evidence[0].end_time,
        observation="A person stands near a robot.",
        match_type="Semantic video match",
        inspection_source="retained_cosmos_caption",
    )
    monkeypatch.setattr(evidence_analysis_module, "_inspect_evidence", AsyncMock(return_value=([inspection], [])))
    llm = MagicMock()
    llm.bind.return_value = llm
    llm.ainvoke = AsyncMock(return_value=AIMessage(content=(
        '{"summary":"The retained observation does not establish contact.",'
        '"observations":[],"interpretations":[],"timeline":[],"suggested_questions":[]}'
    )))
    builder = MagicMock()
    builder.get_llm = AsyncMock(return_value=llm)

    result = await analyze_evidence(builder, request)

    assert result.summary == "The retained observation does not establish contact."
    builder.get_llm.assert_awaited_once()


def test_evidence_request_rejects_unbounded_or_naive_intervals():
    with pytest.raises(ValidationError, match="timezone"):
        EvidenceClipRequest(
            client_id="clip",
            sensor_id="sensor",
            source_name="Camera",
            start_time="2026-08-17T14:00:00",
            end_time="2026-08-17T14:00:10",
        )

    with pytest.raises(ValidationError, match="cannot exceed"):
        EvidenceClipRequest(
            client_id="clip",
            sensor_id="sensor",
            source_name="Camera",
            start_time="2026-08-17T14:00:00Z",
            end_time="2026-08-17T14:06:00Z",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_stream_emits_inspection_before_completion_and_holds_admission(monkeypatch, cancel):
    import asyncio
    import json
    from contextlib import asynccontextmanager
    from fastapi import FastAPI

    active = False
    finish = asyncio.Event()

    @asynccontextmanager
    async def reserve(_workload):
        nonlocal active
        active = True
        try:
            yield
        finally:
            active = False

    inspection = evidence_analysis_module.VisualInspection(
        evidence_id="E1", client_id="first", source_name="Floor",
        start_time="2026-08-17T14:00:00Z", end_time="2026-08-17T14:00:10Z",
        observation="A person is visible.", match_type="Semantic Match",
        inspection_source="fresh_cosmos_inspection",
    )

    async def analyze(builder, request, callback):
        callback(inspection)
        await finish.wait()
        return evidence_analysis_module._degraded_response(request, [inspection], "QA")

    monkeypatch.setattr(evidence_analysis_module, "analyze_evidence", analyze)
    app = FastAPI()
    evidence_analysis_module.register_evidence_analysis_routes(app, MagicMock(), MagicMock(reserve=reserve))
    route = next(route for route in app.routes if route.path.endswith("/stream"))
    response = await route.endpoint(_request())
    stream = response.body_iterator
    first = json.loads(await anext(stream))
    assert first["type"] == "inspection"
    assert first["inspection"]["evidence_id"] == "E1"
    assert active
    if cancel:
        await stream.aclose()
        assert not active
        return
    finish.set()
    last = json.loads(await anext(stream))
    assert last["type"] == "complete"
    with pytest.raises(StopAsyncIteration):
        await anext(stream)
    assert not active


@pytest.mark.asyncio
async def test_inspection_callback_preserves_each_completed_clip(monkeypatch):
    monkeypatch.setenv("EVIDENCE_CAPTION_SEARCH_ENABLED", "false")
    monkeypatch.setenv("EVIDENCE_ALLOW_FRESH_INSPECTION_WHILE_BUSY", "true")
    tool = MagicMock(ainvoke=AsyncMock(side_effect=["First observation", "Second observation"]))
    builder = MagicMock(get_tool=AsyncMock(return_value=tool))
    seen = []
    inspections, warnings = await evidence_analysis_module._inspect_evidence(builder, _request(), seen.append)
    assert not warnings
    assert seen == inspections
    assert [item.evidence_id for item in seen] == ["E1", "E2"]
