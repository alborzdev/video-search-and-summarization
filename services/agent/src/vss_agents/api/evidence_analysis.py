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

"""Grounded, multi-clip evidence analysis for the Vision Intelligence UI."""

import asyncio
from datetime import datetime
import json
import logging
import os
import re
from typing import Literal
from typing import Protocol
from typing import Self
from typing import cast

import aiohttp
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage
from nat.builder.framework_enum import LLMFrameworkEnum
from nat.builder.workflow_builder import WorkflowBuilder
from pydantic import BaseModel
from pydantic import Field
from pydantic import model_validator

from lib.knowledge.adapters.es_caption import EsCaptionAdapter
from lib.knowledge.adapters.es_caption import EsCaptionConfig
from vss_agents.api.thor_workload_admission import ThorVisualWorkloadAdmission
from vss_agents.api.thor_workload_admission import ThorWorkloadAdmissionError
from vss_agents.tools.vst.utils import get_stream_id

logger = logging.getLogger(__name__)

MAX_EVIDENCE_CLIPS = 6
MAX_EVIDENCE_DURATION_SECONDS = 5 * 60


class EvidenceInspectionTool(Protocol):
    """Minimal async interface required from the configured video tool."""

    async def ainvoke(self, input: dict[str, object]) -> object:
        """Inspect one bounded evidence interval."""

        ...


class EvidenceCaptionRetriever(Protocol):
    """Minimal caption-store interface used to reuse prior Cosmos work."""

    async def retrieve(
        self,
        query: str,
        collection_name: str,
        top_k: int = 5,
        filters: object | None = None,
    ) -> object:
        """Retrieve timestamped captions for one source and interval."""

        ...


class EvidenceClipRequest(BaseModel):
    """One retained video interval selected by the operator."""

    client_id: str = Field(min_length=1, max_length=512)
    sensor_id: str = Field(min_length=1, max_length=160)
    source_name: str = Field(min_length=1, max_length=256)
    start_time: datetime
    end_time: datetime
    search_description: str = Field(default="", max_length=2000)
    match_type: str = Field(default="Semantic video match", max_length=120)

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def validate_interval(self) -> Self:
        if self.start_time.tzinfo is None or self.end_time.tzinfo is None:
            raise ValueError("Evidence timestamps must include a timezone")
        duration = (self.end_time - self.start_time).total_seconds()
        if duration <= 0:
            raise ValueError("Evidence end_time must be after start_time")
        if duration > MAX_EVIDENCE_DURATION_SECONDS:
            raise ValueError(f"Evidence clips cannot exceed {MAX_EVIDENCE_DURATION_SECONDS} seconds")
        return self


class EvidenceAnalysisRequest(BaseModel):
    """Analyze or ask a grounded follow-up about selected evidence."""

    query: str = Field(min_length=1, max_length=1000)
    question: str | None = Field(default=None, min_length=1, max_length=1000)
    evidence: list[EvidenceClipRequest] = Field(min_length=1, max_length=MAX_EVIDENCE_CLIPS)

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def validate_unique_evidence(self) -> Self:
        identities = [item.client_id for item in self.evidence]
        if len(identities) != len(set(identities)):
            raise ValueError("Evidence selections must be unique")
        return self


class VisualInspection(BaseModel):
    """A single VLM observation tied to an immutable evidence citation."""

    evidence_id: str
    client_id: str
    source_name: str
    start_time: datetime
    end_time: datetime
    observation: str
    match_type: str
    inspection_source: Literal["retained_cosmos_caption", "fresh_cosmos_inspection"]


class EvidenceClaim(BaseModel):
    """A synthesized claim and the exact evidence items supporting it."""

    text: str
    evidence_ids: list[str]


class EvidenceTimelineEntry(BaseModel):
    """An evidence-derived timeline entry with server-owned timestamps."""

    evidence_id: str
    source_name: str
    start_time: datetime
    end_time: datetime
    label: str


class EvidenceAnalysisResponse(BaseModel):
    """Structured, citation-bearing analysis returned to the UI."""

    status: Literal["complete", "degraded"]
    query: str
    question: str
    summary: str
    observations: list[EvidenceClaim]
    interpretations: list[EvidenceClaim]
    timeline: list[EvidenceTimelineEntry]
    evidence: list[VisualInspection]
    suggested_questions: list[str]
    warning: str | None = None


SYNTHESIS_SYSTEM_PROMPT = """You are the local Vision Analyst synthesizing observations from selected video evidence.
Return exactly one valid JSON object and no markdown. Use only facts in the supplied visual observations.
E1, E2, and similar tokens are clip labels, never people, vehicles, or other subjects. Treat every selected clip as
an independent observation. Never claim or imply that a person, vehicle, or object in one clip is the same identity
as one in another clip unless the supplied observations explicitly prove track continuity. If an operator asks about
\"the person\", \"the man\", or another ambiguous subject across multiple clips, answer separately per clip and say
that cross-clip identity continuity is not established. The summary must represent every supplied evidence clip.
Separate directly visible observations from cautious operational interpretations. Every claim must cite one or more
provided evidence IDs. Do not invent timestamps, cameras, objects, causes, identities, expressions, or events.
Suggested questions must be answerable by re-inspecting only these selected clips. Do not suggest questions about
identity, purpose, intent, causes, operational status, or information outside the visible intervals.

Required JSON shape:
{
  "summary": "one concise evidence-grounded answer",
  "observations": [{"text": "directly visible fact", "evidence_ids": ["E1"]}],
  "interpretations": [{"text": "cautious interpretation", "evidence_ids": ["E1", "E2"]}],
  "timeline": [{"evidence_id": "E1", "label": "short event label"}],
  "suggested_questions": ["useful grounded follow-up", "second follow-up"]
}
"""


def _message_text(value: object) -> str:
    """Extract text from a LangChain response without exposing tool metadata."""

    content = getattr(value, "content", value)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts).strip()
    return str(content).strip()


def _extract_json_object(value: str) -> dict:
    """Parse the first complete JSON object from a model response."""

    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", value, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("The synthesis model did not return a JSON object")
    parsed = json.loads(cleaned[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("The synthesis response must be a JSON object")
    return parsed


def _format_timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _claim_list(value: object, allowed_ids: set[str]) -> list[EvidenceClaim]:
    """Validate LLM claims and discard any unsupported citation IDs."""

    if not isinstance(value, list):
        return []
    claims: list[EvidenceClaim] = []
    for item in value[:12]:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        raw_ids = item.get("evidence_ids")
        evidence_ids = (
            [str(item_id) for item_id in raw_ids if str(item_id) in allowed_ids] if isinstance(raw_ids, list) else []
        )
        if text and evidence_ids:
            claims.append(EvidenceClaim(text=text[:2000], evidence_ids=list(dict.fromkeys(evidence_ids))))
    return claims


_INTERPRETATION_HEDGES = (
    "may",
    "might",
    "appears",
    "suggests",
    "could",
    "likely",
    "possibly",
    "consistent with",
    "cannot establish",
    "cannot determine",
    "unclear",
)


def _cautious_interpretations(value: object, allowed_ids: set[str]) -> list[EvidenceClaim]:
    """Keep only explicitly qualified interpretations from the local synthesis model."""

    return [
        claim
        for claim in _claim_list(value, allowed_ids)
        if any(hedge in claim.text.lower() for hedge in _INTERPRETATION_HEDGES)
    ]


_UNANSWERABLE_QUESTION_PATTERNS = (
    r"\bwho (?:is|was|are|were)\b",
    r"\bidentity\b",
    r"\bname\b",
    r"\bintent(?:ion)?\b",
    r"\bpurpose\b",
    r"\bwhy\b",
    r"\bcause[ds]?\b",
    r"\boperational\b",
    r"\bworking properly\b",
    r"\bsame (?:person|individual|pedestrian|worker|driver|vehicle|car|truck|forklift|robot|object)\b",
)


_CROSS_CLIP_IDENTITY_PATTERNS = (
    r"\bsame (?:person|individual|pedestrian|worker|driver|vehicle|car|truck|forklift|robot|object)\b",
    r"\b(?:match|compare|confirm|establish|determine|verify) (?:the )?identit(?:y|ies)\b",
    r"\bidentit(?:y|ies) (?:match|comparison|continuity)\b",
)


def _asks_for_cross_clip_identity(question: str, evidence_count: int) -> bool:
    """Reject biometric/object re-identification that independent clips cannot prove."""

    return evidence_count > 1 and any(
        re.search(pattern, question, flags=re.IGNORECASE) for pattern in _CROSS_CLIP_IDENTITY_PATTERNS
    )


def _suggested_questions(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    questions: list[str] = []
    for item in value:
        question = str(item).strip()[:300]
        if not question:
            continue
        if any(re.search(pattern, question, flags=re.IGNORECASE) for pattern in _UNANSWERABLE_QUESTION_PATTERNS):
            continue
        questions.append(question)
    return questions[:3]


def _ensure_observation_coverage(
    claims: list[EvidenceClaim], inspections: list[VisualInspection]
) -> list[EvidenceClaim]:
    """Guarantee that synthesis cannot silently omit a selected, inspected clip."""

    cited = {evidence_id for claim in claims for evidence_id in claim.evidence_ids}
    return [
        *claims,
        *(
            EvidenceClaim(text=item.observation, evidence_ids=[item.evidence_id])
            for item in inspections
            if item.evidence_id not in cited
        ),
    ]


def _env_enabled(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _caption_retriever() -> EvidenceCaptionRetriever | None:
    """Build the local caption retriever only when its endpoint is configured."""

    endpoint = os.environ.get("ELASTIC_SEARCH_ENDPOINT", "").strip()
    if not _env_enabled("EVIDENCE_CAPTION_SEARCH_ENABLED", bool(endpoint)) or not endpoint:
        return None
    return cast(
        "EvidenceCaptionRetriever",
        EsCaptionAdapter(
            EsCaptionConfig(
                elasticsearch_url=endpoint,
                index=os.environ.get("EVIDENCE_CAPTION_INDEX", "default_*"),
                timeout=max(1, min(15, int(os.environ.get("EVIDENCE_CAPTION_TIMEOUT_SECONDS", "5")))),
                verify_ssl=_env_enabled("EVIDENCE_CAPTION_VERIFY_SSL", True),
            )
        ),
    )


def _caption_text(value: str) -> str:
    """Turn RT-VLM JSON caption payloads into concise operator-readable facts."""

    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", value.strip(), flags=re.IGNORECASE).strip()
    try:
        payload = json.loads(cleaned)
    except (TypeError, ValueError):
        return value.strip()[:3000]

    entries = payload if isinstance(payload, list) else [payload]
    observations: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        description = str(entry.get("description", "")).strip()
        event_type = str(entry.get("type", "")).strip()
        if description:
            observations.append(f"{event_type}: {description}" if event_type else description)
    return " ".join(dict.fromkeys(observations))[:3000]


async def _retained_caption_inspection(
    retriever: EvidenceCaptionRetriever,
    clip: EvidenceClipRequest,
    evidence_id: str,
) -> VisualInspection | None:
    """Reuse Cosmos captions that already overlap the exact selected interval."""

    stream_id = await get_stream_id(clip.sensor_id)
    result = await retriever.retrieve(
        query="",
        collection_name=stream_id,
        top_k=4,
        filters={
            "doc_type": "raw_events",
            "time_range": {
                "start": clip.start_time.timestamp(),
                "end": clip.end_time.timestamp(),
            },
        },
    )
    if not getattr(result, "success", False):
        return None
    chunks = list(getattr(result, "chunks", []) or [])
    chunks.sort(key=lambda chunk: float(chunk.metadata.get("start_seconds") or 0))
    observations = [_caption_text(str(chunk.content)) for chunk in chunks]
    observation = " ".join(dict.fromkeys(item for item in observations if item)).strip()
    if not observation:
        return None
    return VisualInspection(
        evidence_id=evidence_id,
        client_id=clip.client_id,
        source_name=clip.source_name,
        start_time=clip.start_time,
        end_time=clip.end_time,
        observation=observation,
        match_type=clip.match_type,
        inspection_source="retained_cosmos_caption",
    )


async def _fresh_inspection_is_available() -> bool:
    """Avoid queuing file inspections behind a single busy live Cosmos worker."""

    if _env_enabled("EVIDENCE_ALLOW_FRESH_INSPECTION_WHILE_BUSY", False):
        return True
    base_url = os.environ.get("RTVI_VLM_BASE_URL", "").rstrip("/")
    if not base_url:
        return True
    timeout = aiohttp.ClientTimeout(total=2)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session, session.get(f"{base_url}/v1/metrics") as response:
            if response.status != 200:
                return True
            metrics = await response.text()
    except Exception:
        return True

    def metric(name: str) -> float:
        match = re.search(rf"^{re.escape(name)}\s+([0-9.]+)$", metrics, flags=re.MULTILINE)
        return float(match.group(1)) if match else 0.0

    return metric("active_live_streams") < 1 and metric("video_file_queries_pending") < 1


async def _inspect_evidence(
    builder: WorkflowBuilder,
    request: EvidenceAnalysisRequest,
) -> tuple[list[VisualInspection], list[str]]:
    inspections: list[VisualInspection] = []
    warnings: list[str] = []
    retriever = _caption_retriever()
    tool: EvidenceInspectionTool | None = None
    fresh_available: bool | None = None
    active_question = request.question or request.query
    for index, clip in enumerate(request.evidence, start=1):
        evidence_id = f"E{index}"
        if retriever is not None:
            try:
                retained = await _retained_caption_inspection(retriever, clip, evidence_id)
                if retained is not None:
                    inspections.append(retained)
                    continue
            except Exception:
                logger.info("No retained Cosmos caption was usable for %s", evidence_id, exc_info=True)

        if fresh_available is None:
            fresh_available = await _fresh_inspection_is_available()
        if not fresh_available:
            warnings.append(f"{evidence_id} is waiting for a retained caption while Cosmos is processing live history.")
            continue

        if tool is None:
            resolved = await builder.get_tool("video_understanding_iso", wrapper_type=LLMFrameworkEnum.LANGCHAIN)
            if resolved is None:
                warnings.append(f"{evidence_id} could not be inspected because the local vision tool is unavailable.")
                continue
            tool = cast("EvidenceInspectionTool", resolved)
        try:
            answer = await asyncio.wait_for(
                tool.ainvoke(
                    input={
                        "sensor_id": clip.sensor_id,
                        "start_timestamp": _format_timestamp(clip.start_time),
                        "end_timestamp": _format_timestamp(clip.end_time),
                        "user_prompt": (
                            f"Inspect this exact clip as {evidence_id}. The investigation query is: "
                            f"{request.query.strip()}\n"
                            f"The current operator question is: {active_question.strip()}\n"
                            "Describe only directly visible objects, people, actions, spatial relationships, and "
                            "changes that help answer the question. State uncertainty explicitly. Do not infer "
                            "identity, intent, cause, or events outside this clip. Be concise and use plain text."
                        ),
                        "vlm_reasoning": False,
                    }
                ),
                timeout=max(15, min(180, int(os.environ.get("EVIDENCE_FRESH_INSPECTION_TIMEOUT_SECONDS", "60")))),
            )
            observation = _message_text(answer)
            if not observation:
                raise RuntimeError("the visual inspection returned no observation")
            inspections.append(
                VisualInspection(
                    evidence_id=evidence_id,
                    client_id=clip.client_id,
                    source_name=clip.source_name,
                    start_time=clip.start_time,
                    end_time=clip.end_time,
                    observation=observation,
                    match_type=clip.match_type,
                    inspection_source="fresh_cosmos_inspection",
                )
            )
        except TimeoutError:
            warnings.append(f"{evidence_id} visual inspection timed out while the local vision model was busy.")
        except Exception as exc:
            logger.warning("Fresh visual inspection failed for %s", evidence_id, exc_info=True)
            warnings.append(f"{evidence_id} could not be visually inspected: {exc}")
    return inspections, warnings


def _synthesis_prompt(request: EvidenceAnalysisRequest, inspections: list[VisualInspection]) -> str:
    evidence_lines = []
    for item in inspections:
        evidence_lines.append(
            "\n".join(
                (
                    f"[{item.evidence_id}] Source: {item.source_name}",
                    f"Range: {_format_timestamp(item.start_time)} to {_format_timestamp(item.end_time)}",
                    f"Match provenance: {item.match_type}",
                    f"Visual observation: {item.observation}",
                )
            )
        )
    return (
        f"Original investigation query: {request.query.strip()}\n"
        f"Question to answer now: {(request.question or request.query).strip()}\n\n"
        "Selected evidence:\n\n" + "\n\n".join(evidence_lines)
    )


def _timeline(value: object, inspections: list[VisualInspection]) -> list[EvidenceTimelineEntry]:
    labels: dict[str, str] = {}
    if isinstance(value, list):
        for item in value:
            if not isinstance(item, dict):
                continue
            evidence_id = str(item.get("evidence_id", ""))
            label = str(item.get("label", "")).strip()
            if evidence_id and label:
                labels[evidence_id] = label[:300]
    return [
        EvidenceTimelineEntry(
            evidence_id=item.evidence_id,
            source_name=item.source_name,
            start_time=item.start_time,
            end_time=item.end_time,
            label=labels.get(item.evidence_id, item.observation[:180]),
        )
        for item in sorted(inspections, key=lambda inspection: inspection.start_time)
    ]


def _degraded_response(
    request: EvidenceAnalysisRequest, inspections: list[VisualInspection], warning: str
) -> EvidenceAnalysisResponse:
    observations = [EvidenceClaim(text=item.observation, evidence_ids=[item.evidence_id]) for item in inspections]
    return EvidenceAnalysisResponse(
        status="degraded",
        query=request.query,
        question=request.question or request.query,
        summary=f"{len(inspections)} selected clip{' was' if len(inspections) == 1 else 's were'} visually inspected.",
        observations=observations,
        interpretations=[],
        timeline=_timeline([], inspections),
        evidence=inspections,
        suggested_questions=[],
        warning=warning,
    )


async def analyze_evidence(builder: WorkflowBuilder, request: EvidenceAnalysisRequest) -> EvidenceAnalysisResponse:
    """Inspect every selected interval, then synthesize only citation-bearing claims."""

    inspections, inspection_warnings = await _inspect_evidence(builder, request)
    if not inspections:
        detail = " ".join(inspection_warnings) or "No selected interval could be visually inspected."
        raise RuntimeError(detail)

    active_question = request.question or request.query
    if _asks_for_cross_clip_identity(active_question, len(inspections)):
        warning = " ".join(inspection_warnings) or None
        return EvidenceAnalysisResponse(
            status="degraded" if warning else "complete",
            query=request.query,
            question=active_question,
            summary=(
                "The selected clips cannot establish whether the visible subjects are the same identity. "
                "They are independent observations with no continuous tracked identity linking them."
            ),
            observations=[
                EvidenceClaim(text=item.observation, evidence_ids=[item.evidence_id]) for item in inspections
            ],
            interpretations=[],
            timeline=_timeline([], inspections),
            evidence=inspections,
            suggested_questions=[
                "What people and objects are visible in each clip?",
                "How do the visible actions differ between the clips?",
            ],
            warning=warning,
        )

    llm_name = f"{os.environ.get('LLM_MODEL_TYPE', 'nim')}_llm"
    try:
        llm = await builder.get_llm(llm_name, wrapper_type=LLMFrameworkEnum.LANGCHAIN)
        if llm is None:
            raise RuntimeError(f"The local synthesis model '{llm_name}' is unavailable")
        result = await asyncio.wait_for(
            llm.ainvoke(
                [
                    SystemMessage(content=SYNTHESIS_SYSTEM_PROMPT),
                    HumanMessage(content=_synthesis_prompt(request, inspections)),
                ]
            ),
            timeout=max(30, min(240, int(os.environ.get("EVIDENCE_SYNTHESIS_TIMEOUT_SECONDS", "120")))),
        )
        payload = _extract_json_object(_message_text(result))
        allowed_ids = {item.evidence_id for item in inspections}
        observations = _ensure_observation_coverage(_claim_list(payload.get("observations"), allowed_ids), inspections)
        summary = str(payload.get("summary", "")).strip()
        if not summary:
            raise ValueError("The synthesis model returned no summary")
        return EvidenceAnalysisResponse(
            status="degraded" if inspection_warnings else "complete",
            query=request.query,
            question=request.question or request.query,
            summary=summary[:4000],
            observations=observations,
            interpretations=_cautious_interpretations(payload.get("interpretations"), allowed_ids),
            timeline=_timeline(payload.get("timeline"), inspections),
            evidence=inspections,
            suggested_questions=_suggested_questions(payload.get("suggested_questions")),
            warning=" ".join(inspection_warnings) or None,
        )
    except Exception as exc:
        logger.warning("Evidence synthesis degraded to per-clip observations", exc_info=True)
        return _degraded_response(
            request,
            inspections,
            " ".join(
                [
                    *inspection_warnings,
                    f"The available clips were visually inspected, but local synthesis was unavailable: {exc}",
                ]
            ),
        )


def register_evidence_analysis_routes(
    app: FastAPI,
    builder: WorkflowBuilder,
    admission: ThorVisualWorkloadAdmission | None = None,
) -> None:
    """Register the same-origin backend used by the redesigned Investigation UI."""
    visual_admission = admission or ThorVisualWorkloadAdmission()

    @app.post("/api/v1/evidence-analysis", include_in_schema=False)
    async def evidence_analysis(request: EvidenceAnalysisRequest) -> JSONResponse:
        try:
            async with visual_admission.reserve("evidence_analysis"):
                result = await analyze_evidence(builder, request)
        except ThorWorkloadAdmissionError as exc:
            return JSONResponse(status_code=exc.status_code, content=exc.response_body())
        except Exception as exc:
            logger.warning("Selected evidence analysis failed", exc_info=True)
            return JSONResponse(status_code=502, content={"error": f"Evidence analysis could not be completed: {exc}"})
        return JSONResponse(status_code=200, content=result.model_dump(mode="json"))
