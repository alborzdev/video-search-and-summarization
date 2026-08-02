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
import importlib.util
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
CONFIG_PATH = REPO_ROOT / "deploy/docker/developer-profiles/dev-profile-thor-full/vss-agent/configs/config.yml"
VA_MCP_CONFIG_PATH = CONFIG_PATH.with_name("va_mcp_server_config.yml")
PROFILE_ENV_PATH = CONFIG_PATH.parents[2] / ".env"
ALERT_CONFIG_PATH = REPO_ROOT / "deploy/docker/developer-profiles/dev-profile-alerts/vlm-as-verifier/configs/config.yml"
ALERT_ENV_SUBSTITUTION_PATH = REPO_ROOT / "deploy/docker/services/alert/scripts/env-substitute.py"


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
    local_tools = {name for name in workflow["tool_names"] if "." not in name}
    assert local_tools <= functions.keys()
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
        "/api/v1/search/attribute",
        "/api/v1/search/fusion",
        "/api/v1/search/image",
        "/api/v1/attribute_search",
        "/api/v1/embed_search",
        "/api/v1/critic",
    }
    endpoint_functions = {endpoint["path"]: endpoint["function_name"] for endpoint in endpoints}
    assert endpoint_functions["/api/v1/search/attribute"] == "attribute_search"
    assert endpoint_functions["/api/v1/search/fusion"] == "search"
    assert endpoint_functions["/api/v1/search/image"] == "search"


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


def test_top_agent_exposes_every_local_video_analytics_mcp_tool() -> None:
    config = _load_config()
    expected_server_tools = {
        "get_incident",
        "get_incidents",
        "get_sensor_ids",
        "get_places",
        "get_fov_histogram",
        "get_average_speeds",
        "analyze",
    }
    expected_remote_tools = {f"video_analytics__{name}" for name in expected_server_tools}
    expected_agent_tools = {f"video_analytics_mcp.{name}" for name in expected_remote_tools}

    with VA_MCP_CONFIG_PATH.open(encoding="utf-8") as config_file:
        server_config = yaml.safe_load(config_file)

    assert set(server_config["function_groups"]["video_analytics"]["include"]) == expected_server_tools
    assert set(config["function_groups"]["video_analytics_mcp"]["include"]) == expected_remote_tools
    assert expected_agent_tools <= set(config["workflow"]["tool_names"])
    assert (
        config["functions"]["incident_report_agent"]["get_incidents_tool"]
        == "video_analytics_mcp.video_analytics__get_incidents"
    )
    assert (
        config["functions"]["incident_report_agent"]["get_incident_tool"]
        == "video_analytics_mcp.video_analytics__get_incident"
    )


def test_thor_enables_all_local_alert_extensions(monkeypatch: Any) -> None:
    profile_env = PROFILE_ENV_PATH.read_text(encoding="utf-8").splitlines()
    flags = {
        "ALERT_DIRECT_MEDIA_ENABLED",
        "ALERT_ENRICHMENT_ENABLED",
        "ALERT_ALWAYS_ON_ENABLED",
        "ALERT_WEBSOCKET_ENABLED",
    }
    for flag in flags:
        assert f"{flag}=true" in profile_env
        monkeypatch.setenv(flag, "true")

    spec = importlib.util.spec_from_file_location("alert_env_substitute", ALERT_ENV_SUBSTITUTION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rendered = module.substitute_env_vars(ALERT_CONFIG_PATH.read_text(encoding="utf-8"))
    config = yaml.safe_load(rendered)

    assert config["alert_agent"]["media_download"]["enabled"] is True
    assert config["alert_agent"]["enrichment"]["enabled"] is True
    assert config["alert_agent"]["always_on"] is True
    assert config["websocket"]["enabled"] is True


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


def test_thor_audio_flag_reaches_every_audio_aware_agent_path() -> None:
    config = _load_config()
    functions = config["functions"]
    expected_value = "${ENABLE_AUDIO:-false}"

    audio_flags = {
        "general.front_end.streaming_ingest": config["general"]["front_end"]["streaming_ingest"]["enable_audio"],
        "functions.video_understanding": functions["video_understanding"]["enable_audio"],
        "functions.video_understanding_iso": functions["video_understanding_iso"]["enable_audio"],
        "functions.vst_video_clip": functions["vst_video_clip"]["enable_audio"],
        "functions.vst_video_url": functions["vst_video_url"]["enable_audio"],
        "functions.lvs_video_understanding": functions["lvs_video_understanding"]["enable_audio"],
        "functions.lvs_config_media": functions["lvs_config_media"]["enable_audio"],
        "functions.video_report_gen": functions["video_report_gen"]["enable_audio"],
    }

    assert set(audio_flags.values()) == {expected_value}
