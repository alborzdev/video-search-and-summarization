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
    assert result.summary == "A person is visible near the robot in one of the two selected clips."
    assert [claim.evidence_ids for claim in result.observations] == [["E1"], ["E2"]]
    assert [entry.evidence_id for entry in result.timeline] == ["E1", "E2"]
    assert result.timeline[0].label == "Person walks beside robot"
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
    assert [claim.text for claim in result.interpretations] == ["The scene may indicate active work."]
    assert result.suggested_questions == ["How many people are visible in each clip?"]
    system_prompt = synthesis_llm.ainvoke.await_args.args[0][0].content
    assert "clip labels, never people" in system_prompt
    assert "cross-clip identity continuity is not established" in system_prompt


@pytest.mark.asyncio
async def test_follow_up_is_reinspected_and_synthesis_cannot_cite_unknown_evidence(monkeypatch):
    monkeypatch.setenv("LLM_MODEL_TYPE", "vllm")
    monkeypatch.setenv("EVIDENCE_CAPTION_SEARCH_ENABLED", "false")
    monkeypatch.setenv("EVIDENCE_ALLOW_FRESH_INSPECTION_WHILE_BUSY", "true")
    visual_tool = MagicMock()
    visual_tool.ainvoke = AsyncMock(side_effect=["No contact is visible.", "No contact is visible."])
    synthesis_llm = MagicMock()
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
    for call in visual_tool.ainvoke.await_args_list:
        assert "Did the person touch the robot?" in call.kwargs["input"]["user_prompt"]


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
