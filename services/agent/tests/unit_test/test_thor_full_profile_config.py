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

"""Structural tests for the unified NVIDIA Thor agent profile."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
CONFIG_PATH = REPO_ROOT / "deploy/docker/developer-profiles/dev-profile-thor-full/vss-agent/configs/config.yml"
VA_MCP_CONFIG_PATH = CONFIG_PATH.with_name("va_mcp_server_config.yml")
PROFILE_ENV_PATH = CONFIG_PATH.parents[2] / ".env"


def _load_config() -> dict[str, Any]:
    with CONFIG_PATH.open(encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file)
    assert isinstance(config, dict)
    return config


def _walk(value: Any) -> Iterator[Any]:
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def test_unified_profile_exposes_all_capability_groups() -> None:
    config = _load_config()
    functions = config["functions"]
    workflow = config["workflow"]
    streaming_ingest = config["general"]["front_end"]["streaming_ingest"]

    assert {
        "lvs_video_understanding",
        "lvs_config_media",
        "lvs_stream_understanding",
        "lvs_caption_retrieval",
        "video_report_gen",
        "search",
        "embed_search",
        "attribute_search",
        "critic_agent",
        "rtvi_vlm_alert",
        "rtvi_prompt_gen",
        "template_report_gen",
    } <= functions.keys()
    assert set(workflow["subagent_names"]) == {
        "report_agent",
        "search_agent",
        "incident_report_agent",
    }
    assert set(workflow["subagent_names"]) <= functions.keys()
    assert set(workflow["tool_names"]) <= functions.keys()
    assert streaming_ingest["vst_streamprocessor_url"] == "${STREAM_PROCESSOR_MODULE_ENDPOINT:-}"
    assert streaming_ingest["rtvi_vlm_base_url"]
    assert streaming_ingest["rtvi_cv_base_url"]
    assert streaming_ingest["rtvi_embed_base_url"]


def test_unified_profile_has_one_top_agent_and_all_search_routes() -> None:
    config = _load_config()
    top_agents = [value for value in _walk(config) if value == "top_agent"]
    endpoints = config["general"]["front_end"]["endpoints"]

    assert top_agents == ["top_agent"]
    assert {endpoint["path"] for endpoint in endpoints} == {
        "/api/v1/search",
        "/api/v1/attribute_search",
        "/api/v1/embed_search",
        "/api/v1/critic",
    }


def test_unified_profile_does_not_embed_service_hosts() -> None:
    config = _load_config()
    url_values = [value for value in _walk(config) if isinstance(value, str) and "://" in value]

    assert url_values
    assert all("${" in value for value in url_values)


def test_video_analytics_mcp_profile_uses_shared_service_environment() -> None:
    with VA_MCP_CONFIG_PATH.open(encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file)

    assert config["functions"]["vst_sensor_list"]["vst_internal_url"] == "${VST_INTERNAL_URL}"
    assert config["function_groups"]["video_analytics"]["es_url"] == "${ELASTIC_SEARCH_ENDPOINT}"
    assert config["llms"]["nim_llm"]["_type"] == "${VA_MCP_LLM_MODEL_TYPE:-openai}"
    assert config["llms"]["nim_llm"]["base_url"] == "${LLM_BASE_URL}/v1"


def test_thor_profile_intentionally_enables_search_by_image() -> None:
    profile_env = PROFILE_ENV_PATH.read_text(encoding="utf-8")

    assert "NEXT_PUBLIC_SEARCH_TAB_MEDIA_WITH_OBJECTS_BBOX=true" in profile_env.splitlines()


def test_thor_profile_incident_reports_have_a_real_template() -> None:
    """The browser Generate Report action must have a mounted template contract."""

    config = CONFIG_PATH.read_text(encoding="utf-8")
    profile_env = PROFILE_ENV_PATH.read_text(encoding="utf-8")
    template = (
        REPO_ROOT
        / "deploy/docker/developer-profiles/dev-profile-alerts/vss-agent/templates/incident_report_template.md"
    )

    assert "template_path: ${VSS_AGENT_TEMPLATE_PATH}" in config
    assert "template_name: ${VSS_AGENT_TEMPLATE_NAME}" in config
    assert "VSS_AGENT_TEMPLATE_PATH=" in profile_env
    assert "VSS_AGENT_TEMPLATE_NAME=" in profile_env
    assert template.is_file()
    assert "{verification_verdict}" in template.read_text(encoding="utf-8")


def test_top_agent_must_execute_resolved_media_plan_before_answering() -> None:
    """Do not expose an unfinished tool plan as the user-facing answer."""

    workflow = _load_config()["workflow"]

    assert "A plan, checklist, proposed tool call, or incomplete step is never a final" in workflow["prompt"]
    assert "vst_video_list followed by video_understanding" in workflow["prompt"]
    assert "Never expose a plan, checklist" in workflow["response_format_prompt"]


def test_multi_video_reports_use_one_report_agent_call() -> None:
    """Keep the 3.2.1 multi-video routing fix in the independent Thor prompt."""

    prompt = _load_config()["workflow"]["prompt"]

    assert "For multiple uploaded videos" in prompt
    assert "SINGLE report_agent call" in prompt
    assert "Never split a multi-video report" in prompt
    assert "media_type='rtsp'" in prompt


def test_quick_video_questions_have_a_bounded_thor_frame_budget() -> None:
    function = _load_config()["functions"]["video_understanding"]

    assert function["max_frames"] == 16
    assert function["max_fps"] == 1
    assert function["max_frames_per_request"] == "${VLM_MAX_FRAMES_PER_REQUEST:-30}"
