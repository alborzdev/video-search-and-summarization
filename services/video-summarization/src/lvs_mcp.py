# SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

"""Implements the LVS MCP Server.

Exposes the same functionality as the REST API through MCP tools."""

import asyncio
import json
import os
import re
import stat
from datetime import datetime
from ipaddress import ip_address
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from lvs_mcp_sse import SessionCleaningSseServerTransport
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, TextContent, Tool
from via_logger import logger

# Get API prefix from environment (same as via_server.py)
API_PREFIX = (
    "/v1" if os.environ.get("VSS_API_ENABLE_VERSIONING", "").lower() in ["true", "1"] else ""
)

_DEFAULT_MAX_MEDIA_BYTES = 8 * 1024 * 1024 * 1024
_MAX_CONFIGURABLE_MEDIA_BYTES = 100 * 1000 * 1000 * 1000
# Local MCP defaults and hard configuration ceilings for consuming the
# in-process LVS SSE response. The 600-second default matches the existing RTVI
# request timeout; operators can raise it for longer videos without removing
# the required total-call bound.
_DEFAULT_MAX_SSE_BYTES = 4 * 1024 * 1024
_MAX_CONFIGURABLE_SSE_BYTES = 64 * 1024 * 1024
_DEFAULT_MAX_SSE_EVENTS = 1024
_MAX_CONFIGURABLE_SSE_EVENTS = 100_000
_DEFAULT_SSE_TIMEOUT_SECONDS = 600
_MAX_CONFIGURABLE_SSE_TIMEOUT_SECONDS = 24 * 60 * 60
_SSE_DISCONNECT_GRACE_SECONDS = 1.0
_MAX_CONCURRENT_SSE_STREAMS = 4
_RFC3339_MILLISECONDS = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})\.\d{3}Z$"
)
_SENSOR_NAME = re.compile(r"^[A-Za-z0-9_. -]{0,256}$")
_FILE_TOOLS = frozenset({"add_file", "list_files", "get_file_info", "delete_file"})


class _SseResponseError(ValueError):
    """Raised when the in-process LVS SSE response violates its local policy."""


def _find_sse_response_error(error: BaseException) -> Optional[_SseResponseError]:
    """Recover a bounded-stream error wrapped by an ASGI task group."""

    if isinstance(error, _SseResponseError):
        return error
    for nested in getattr(error, "exceptions", ()):
        found = _find_sse_response_error(nested)
        if found is not None:
            return found
    return None


def _reject_duplicate_json_keys(pairs: List[tuple[str, Any]]) -> Dict[str, Any]:
    value: Dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise _SseResponseError("LVS SSE event contains duplicate JSON keys")
        value[key] = item
    return value


def _mcp_bind_host() -> str:
    """Return a loopback-only MCP bind address.

    The legacy SSE transport has no authentication, so exposing it on all
    interfaces would make the file-management tools remotely writable.
    """

    host = os.environ.get("LVS_MCP_HOST", "127.0.0.1").strip()
    try:
        is_loopback = ip_address(host).is_loopback
    except ValueError as exc:
        raise ValueError("LVS_MCP_HOST must be a loopback IP address") from exc
    if not is_loopback:
        raise ValueError("LVS_MCP_HOST must be a loopback IP address")
    return host


class _BoundedMediaReader:
    """File proxy that refuses to stream more than the configured byte limit."""

    def __init__(self, stream, limit: int):
        self._stream = stream
        self._limit = limit
        self._read = 0

    def read(self, size: int = -1):
        remaining = self._limit - self._read
        bounded_size = remaining + 1 if size < 0 or size > remaining + 1 else size
        chunk = self._stream.read(bounded_size)
        self._read += len(chunk)
        if self._read > self._limit:
            raise ValueError("path grew beyond LVS_MCP_MAX_FILE_BYTES while uploading")
        return chunk

    def __getattr__(self, name):
        return getattr(self._stream, name)


class LvsMCPServer:
    """MCP Server that exposes LVS functionality as tools."""

    def __init__(self, lvs_server_instance):
        """Initialize MCP server with a reference to LvsServer instance.

        Args:
            lvs_server_instance: Instance of ViaServer class containing the backend logic
        """
        self._lvs_server = lvs_server_instance
        self._server = Server("lvs-engine")
        # Active requests consume capacity synchronously. Only an ASGI app that
        # ignores a delivered disconnect past the bounded cleanup grace is kept
        # strongly as a fail-safe and continues to consume its capacity slot.
        self._sse_stream_lock = Lock()
        self._sse_stream_count = 0
        self._sse_stream_tasks: set[asyncio.Task[Any]] = set()
        self._setup_handlers()

    def _reserve_sse_stream(self) -> None:
        """Atomically reserve capacity before invoking the ASGI application."""

        with self._sse_stream_lock:
            if self._sse_stream_count >= _MAX_CONCURRENT_SSE_STREAMS:
                raise _SseResponseError(
                    "LVS SSE stream capacity is exhausted "
                    f"(maximum {_MAX_CONCURRENT_SSE_STREAMS} active or draining streams)"
                )
            self._sse_stream_count += 1

    def _release_sse_stream(self) -> None:
        """Release one synchronously owned stream-capacity reservation."""

        with self._sse_stream_lock:
            self._sse_stream_count -= 1

    def _retain_sse_stream_task(self, task: asyncio.Task[Any]) -> None:
        """Retain only an app that ignored disconnect past the cleanup grace."""

        with self._sse_stream_lock:
            self._sse_stream_tasks.add(task)
        task.add_done_callback(self._sse_stream_done)

    def _sse_stream_done(self, task: asyncio.Task[Any]) -> None:
        """Consume a fail-safe task result and release its retained capacity."""

        try:
            task.result()
        except BaseException as error:
            logger.error(
                "In-process LVS SSE ASGI task ended abnormally; releasing its "
                "capacity slot, but downstream resource cleanup is not guaranteed: %s",
                error,
                exc_info=(type(error), error, error.__traceback__),
            )
        finally:
            with self._sse_stream_lock:
                if task in self._sse_stream_tasks:
                    self._sse_stream_tasks.remove(task)
                    self._sse_stream_count -= 1

    def _setup_handlers(self):
        """Set up MCP tool handlers."""

        @self._server.list_tools()
        async def list_tools() -> List[Tool]:
            """Return list of available tools."""
            return [
                # Health Check
                Tool(
                    name="health_ready",
                    description="Check if LVS server is ready to accept requests",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                    },
                ),
                Tool(
                    name="health_live",
                    description="Check if LVS server is alive",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                    },
                ),
                # Models API
                Tool(
                    name="list_models",
                    description="List available VLM models",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                    },
                ),
                # File-management API. NVIDIA's 3.2.1 documentation advertises
                # these four tools but does not publish their MCP schemas. This
                # source-derived local contract is deliberately narrower than
                # the underlying REST API: local regular files only, rooted at
                # LVS_MCP_MEDIA_ROOT, with remote URLs and base64 excluded.
                Tool(
                    name="add_file",
                    description="Upload a local video from the configured read-only media root",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 1024,
                                "description": "Relative path beneath LVS_MCP_MEDIA_ROOT",
                            },
                            "creation_time": {
                                "type": "string",
                                "format": "date-time",
                                "description": "Optional UTC timestamp with millisecond precision",
                            },
                            "sensor_name": {
                                "type": "string",
                                "maxLength": 256,
                                "pattern": r"^[A-Za-z0-9_. -]*$",
                            },
                        },
                        "required": ["path"],
                        "additionalProperties": False,
                    },
                ),
                Tool(
                    name="list_files",
                    description="List uploaded video files",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                ),
                Tool(
                    name="get_file_info",
                    description="Get metadata for an uploaded video file",
                    inputSchema={
                        "type": "object",
                        "properties": {"file_id": {"type": "string", "format": "uuid"}},
                        "required": ["file_id"],
                        "additionalProperties": False,
                    },
                ),
                Tool(
                    name="delete_file",
                    description="Delete an uploaded video and its LVS collection",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "file_id": {"type": "string", "format": "uuid"},
                            "confirm_file_id": {
                                "type": "string",
                                "format": "uuid",
                                "description": "Must exactly repeat file_id",
                            },
                        },
                        "required": ["file_id", "confirm_file_id"],
                        "additionalProperties": False,
                    },
                ),
                # Summarization API
                Tool(
                    name="summarize_video",
                    description="Generate a summary of video content. Either 'id' (file UUID) or 'url' must be provided, but not both.",  # noqa: E501
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string",
                                "description": "File or stream UUID to summarize. Either URL or ID must be provided, but not both.",  # noqa: E501
                            },
                            "url": {
                                "type": "string",
                                "description": "URL of the video to summarize. Either URL or ID must be provided, but not both.",  # noqa: E501
                            },
                            "prompt": {
                                "type": "string",
                                "description": "Prompt for VLM caption generation. Required when CA-RAG is enabled for the initial captioning phase, or for direct summarization when CA-RAG is disabled.",  # noqa: E501
                            },
                            "model": {
                                "type": "string",
                                "description": "Model to use for summarization",
                            },
                            "chunk_duration": {
                                "type": "integer",
                                "description": "Duration of each chunk in seconds",
                                "default": 60,
                            },
                            "chunk_overlap_duration": {
                                "type": "integer",
                                "description": "Overlap between chunks in seconds",
                                "default": 0,
                            },
                            "stream": {
                                "type": "boolean",
                                "description": "Enable streaming response",
                                "default": False,
                            },
                            "max_tokens": {
                                "type": "integer",
                                "description": "Maximum tokens in response",
                            },
                            "temperature": {
                                "type": "number",
                                "description": "Sampling temperature",
                            },
                            "schema": {
                                "type": "string",
                                "description": "JSON schema for structured \
                                output extraction from video content",  # noqa: E501
                            },
                            "batch_response_method": {
                                "type": "string",
                                "description": "Method for batch response processing",
                            },
                            "scenario": {
                                "type": "string",
                                "description": "Scenario or use case context for the summarization. \
                                    Examples: 'warehouse', 'public safety', \
                                    'police body camera monitoring'",
                            },
                            "events": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "List of events to detect or extract from the video",
                            },
                            "auto_generate_prompt": {
                                "type": "boolean",
                                "description": "Enable automatic prompt generation based on schema and events",  # noqa: E501
                            },
                            "time_metadata_keys": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "List of metadata keys containing time information",
                            },
                            "override_vlm_prompt": {
                                "type": "boolean",
                                "description": "Override the VLM prompt with the user supplied prompt. Please set this to True when you want to use a custom prompt for VLM caption generation and pass the prompt in the prompt field.",  # noqa: E501
                                "default": False,
                            },
                            "enable_vlm_structured_output": {
                                "type": "boolean",
                                "description": "Enable VLM structured output",
                                "default": True,
                            },
                            "objects_of_interest": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "List of objects of interest to detect or extract from the video.",  # noqa: E501
                            },
                        },
                        "required": ["model", "scenario", "events"],
                    },
                ),
                Tool(
                    name="generate_vlm_captions",
                    description="Generate VLM captions for video frames. Either 'id' (file UUID) or 'url' must be provided.",  # noqa: E501
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string",
                                "description": "File or stream UUID. Either id or url must be provided.",
                            },
                            "url": {
                                "type": "string",
                                "description": "URL of the video. Either id or url must be provided.",
                            },
                            "prompt": {
                                "type": "string",
                                "description": "Prompt for caption generation",
                            },
                            "model": {
                                "type": "string",
                                "description": "Model to use",
                            },
                            "chunk_duration": {
                                "type": "integer",
                                "description": "Duration of each chunk in seconds",
                                "default": 60,
                            },
                        },
                        "required": ["prompt", "model"],
                    },
                ),
                # Stream Captioning API
                Tool(
                    name="generate_captions",
                    description=(
                        "Start VLM captioning on a stream. The stream must have "
                        "been previously added via RTVI stream/add. Returns "
                        "immediately once captioning is acknowledged."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string",
                                "description": "Stream UUID (from RTVI stream/add)",
                            },
                            "model": {
                                "type": "string",
                                "description": "Model to use for caption generation",
                            },
                            "prompt": {
                                "type": "string",
                                "description": "VLM prompt for caption generation",
                            },
                            "chunk_duration": {
                                "type": "integer",
                                "description": "Chunk duration in seconds (0 = no chunking)",
                                "default": 0,
                            },
                            "scenario": {
                                "type": "string",
                                "description": "Scenario for auto-prompt generation",
                            },
                            "events": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Events for auto-prompt generation",
                            },
                            "objects_of_interest": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Objects of interest for auto-prompt generation",
                            },
                            "enable_vlm_structured_output": {
                                "type": "boolean",
                                "description": "Enable structured VLM output",
                                "default": True,
                            },
                            "override_vlm_prompt": {
                                "type": "boolean",
                                "description": "Use prompt as-is instead of auto-generating",
                                "default": False,
                            },
                            "max_tokens": {
                                "type": "integer",
                                "description": "Maximum tokens per chunk",
                            },
                            "temperature": {
                                "type": "number",
                                "description": "Sampling temperature",
                            },
                        },
                        "required": ["id", "model"],
                    },
                ),
                # Stream Summarize API
                Tool(
                    name="stream_summarize",
                    description=(
                        "Summarize a stream by aggregating existing captions from "
                        "the database. The stream must have been started with "
                        "generate_captions first."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string",
                                "description": "Stream UUID to summarize",
                            },
                            "model": {
                                "type": "string",
                                "description": "Model identifier",
                            },
                            "start_time": {
                                "type": "number",
                                "description": "Time window start (seconds, 0 = no filter)",
                                "default": 0,
                            },
                            "end_time": {
                                "type": "number",
                                "description": "Time window end (seconds, 0 = no filter)",
                                "default": 0,
                            },
                            "summarize_max_tokens": {
                                "type": "integer",
                                "description": "Max tokens for LLM aggregation",
                            },
                            "summarize_temperature": {
                                "type": "number",
                                "description": "Temperature for LLM aggregation",
                            },
                        },
                        "required": ["id", "model"],
                    },
                ),
                # Recommended Config API
                Tool(
                    name="get_recommended_config",
                    description="Get recommended configuration for video processing",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "video_length": {
                                "type": "integer",
                                "description": "Video length in seconds",
                            },
                            "target_response_time": {
                                "type": "integer",
                                "description": "Target response time in seconds",
                            },
                            "usecase_event_duration": {
                                "type": "integer",
                                "description": "Expected event duration in seconds",
                            },
                        },
                        "required": ["video_length", "target_response_time"],
                    },
                ),
                # Metrics
                Tool(
                    name="get_metrics",
                    description="Get LVS server metrics in Prometheus format",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                    },
                ),
            ]

        # Retain the pure registration closure for networkless contract tests.
        self._list_tools_handler = list_tools

        @self._server.call_tool()
        async def call_tool(name: str, arguments: Dict[str, Any]) -> CallToolResult:
            """Handle tool calls by delegating to _invoke_call_tool."""
            return await self._invoke_call_tool(name, arguments)

        # Retain the exact registered closure for networkless contract tests.
        self._call_tool_handler = call_tool

    async def _invoke_call_tool(
        self, name: str, arguments: Dict[str, Any]
    ) -> CallToolResult:
        """Execute a tool and return an MCP-native success or tool-error result."""
        try:
            result = await self._handle_tool_call(name, arguments)
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(result, indent=2))],
                isError=False,
            )
        except Exception as error:
            # Keep diagnostic detail in the service log, never in the MCP file-tool
            # response. The low-level SDK recognizes CallToolResult and preserves
            # isError=true instead of normalizing this into an ordinary success.
            logger.error(
                "Error executing MCP tool %r: %s",
                name,
                error,
                exc_info=True,
            )
            payload = (
                {"error": f"{name} failed; see the LVS service log for details"}
                if isinstance(name, str) and name in _FILE_TOOLS
                else {"error": str(error), "type": type(error).__name__}
            )
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(payload))],
                isError=True,
            )

    async def _handle_tool_call(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Route tool calls to appropriate LvsServer methods."""

        if not isinstance(name, str) or not name:
            raise ValueError("tool name must be a non-empty string")
        if not isinstance(arguments, dict):
            raise ValueError("tool arguments must be an object")

        # Health Check
        if name == "health_ready":
            return await self._health_ready()

        elif name == "health_live":
            return await self._health_live()

        # Models API
        elif name == "list_models":
            return await self._list_models()

        # File-management API
        elif name == "add_file":
            return await self._add_file(arguments)

        elif name == "list_files":
            return await self._list_files(arguments)

        elif name == "get_file_info":
            return await self._get_file_info(arguments)

        elif name == "delete_file":
            return await self._delete_file(arguments)

        # Summarization API
        elif name == "summarize_video":
            return await self._summarize_video(arguments)

        elif name == "generate_vlm_captions":
            return await self._generate_vlm_captions(arguments)

        # Stream APIs
        elif name == "generate_captions":
            return await self._generate_captions(arguments)

        elif name == "stream_summarize":
            return await self._stream_summarize(arguments)

        # Recommended Config API
        elif name == "get_recommended_config":
            return await self._get_recommended_config(arguments)

        # Metrics
        elif name == "get_metrics":
            return await self._get_metrics()

        else:
            raise ValueError(f"Unknown tool: {name}")

    # Implementation methods that delegate to LvsServer

    async def _call_http_api(
        self, method: str, path: str, return_text: bool = False, **kwargs
    ) -> Dict[str, Any]:
        """Helper to call LvsServer's HTTP API internally.

        Args:
            method: HTTP method (GET, POST, DELETE, etc.)
            path: API path (e.g., "/files" or "/v1/files" depending on API_PREFIX)
            return_text: If True, return response text instead of JSON
            **kwargs: Additional arguments to pass to the HTTP client (json, params, data, files, etc.)

        Returns:
            Response JSON as dictionary or text string
        """
        from httpx import ASGITransport, AsyncClient

        # Use ASGITransport to call the FastAPI app directly
        transport = ASGITransport(app=self._lvs_server._app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.request(method, path, **kwargs)

            if response.status_code >= 400:
                try:
                    error_data = response.json()
                    logger.error(
                        f"Error response from API: status={response.status_code}, data={error_data}, type={type(error_data)}"  # noqa: E501
                    )

                    # Handle both dict and other response formats
                    if isinstance(error_data, dict):
                        code = error_data.get(
                            "code", error_data.get("detail", {}).get("code", "Error")
                        )
                        message = error_data.get(
                            "message",
                            error_data.get("detail", {}).get("message", str(error_data)),
                        )
                        error_msg = f"{code}: {message}"
                    else:
                        error_msg = f"HTTP {response.status_code}: {str(error_data)}"
                except Exception as e:
                    logger.error(
                        f"Failed to parse error response: status={response.status_code}, text={response.text[:500]}, exception={e}"  # noqa: E501
                    )
                    error_msg = f"HTTP {response.status_code}: {response.text}"
                raise ValueError(error_msg)

            # Handle different response types
            if response.status_code == 204:  # No content
                return {}

            if return_text:
                return {"text": response.text}

            return response.json()

    @staticmethod
    def _sse_limits() -> tuple[int, int, int]:
        """Read the bounded SSE policy from validated integer environment values."""

        settings = (
            (
                "LVS_MCP_MAX_SSE_BYTES",
                _DEFAULT_MAX_SSE_BYTES,
                _MAX_CONFIGURABLE_SSE_BYTES,
            ),
            (
                "LVS_MCP_MAX_SSE_EVENTS",
                _DEFAULT_MAX_SSE_EVENTS,
                _MAX_CONFIGURABLE_SSE_EVENTS,
            ),
            (
                "LVS_MCP_SSE_TIMEOUT_SECONDS",
                _DEFAULT_SSE_TIMEOUT_SECONDS,
                _MAX_CONFIGURABLE_SSE_TIMEOUT_SECONDS,
            ),
        )
        values = []
        for name, default, maximum in settings:
            raw = os.environ.get(name, str(default)).strip()
            if not raw.isdecimal() or not 0 < int(raw) <= maximum:
                raise ValueError(f"{name} must be an integer from 1 through {maximum}")
            values.append(int(raw))
        return values[0], values[1], values[2]

    @staticmethod
    def _sse_disconnect_grace_seconds() -> float:
        """Return the bounded interval allowed for ASGI disconnect cleanup."""

        return _SSE_DISCONNECT_GRACE_SECONDS

    @staticmethod
    def _parse_sse_body(body: bytes, *, max_events: int) -> List[str]:
        """Return strict, data-only SSE payloads from one complete response."""

        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _SseResponseError("LVS SSE response is not valid UTF-8") from exc
        text = text.replace("\r\n", "\n")
        if "\r" in text:
            raise _SseResponseError("LVS SSE response contains an invalid line ending")
        if not text.endswith("\n\n"):
            raise _SseResponseError("LVS SSE response ended with a truncated event")

        payloads: List[str] = []
        for frame in text[:-2].split("\n\n"):
            if not frame:
                continue
            lines = frame.split("\n")
            event_lines = [line for line in lines if line and not line.startswith(":")]
            if not event_lines:
                continue
            data_lines = []
            for line in event_lines:
                if not line.startswith("data:"):
                    raise _SseResponseError("LVS SSE response contains an unexpected field")
                data = line[5:]
                if data.startswith(" "):
                    data = data[1:]
                data_lines.append(data)
            data = "\n".join(data_lines)
            if not data:
                raise _SseResponseError("LVS SSE response contains malformed event data")
            payloads.append(data)
            if len(payloads) > max_events:
                raise _SseResponseError("LVS SSE response exceeded the event limit")

        if not payloads:
            raise _SseResponseError("LVS SSE response contains no data events")
        return payloads

    @staticmethod
    def _validate_sse_media_info(value: Any) -> None:
        if not isinstance(value, dict):
            raise _SseResponseError("LVS SSE event has invalid media_info")
        media_type = value.get("type")
        if media_type == "offset":
            if set(value) != {"type", "start_offset", "end_offset"}:
                raise _SseResponseError("LVS SSE event has invalid offset media_info")
            start = value["start_offset"]
            end = value["end_offset"]
            if (
                isinstance(start, bool)
                or not isinstance(start, int)
                or isinstance(end, bool)
                or not isinstance(end, int)
                or not 0 <= start <= end <= 4_000_000_000
            ):
                raise _SseResponseError("LVS SSE event has invalid offset media_info")
            return
        if media_type == "timestamp":
            if set(value) != {"type", "start_timestamp", "end_timestamp"}:
                raise _SseResponseError("LVS SSE event has invalid timestamp media_info")
            start = value["start_timestamp"]
            end = value["end_timestamp"]
            if (
                not isinstance(start, str)
                or not isinstance(end, str)
                or not _RFC3339_MILLISECONDS.fullmatch(start)
                or not _RFC3339_MILLISECONDS.fullmatch(end)
            ):
                raise _SseResponseError("LVS SSE event has invalid timestamp media_info")
            try:
                datetime.strptime(start, "%Y-%m-%dT%H:%M:%S.%fZ")
                datetime.strptime(end, "%Y-%m-%dT%H:%M:%S.%fZ")
            except ValueError as exc:
                raise _SseResponseError(
                    "LVS SSE event has invalid timestamp media_info"
                ) from exc
            if start > end:
                raise _SseResponseError("LVS SSE event has reversed timestamp media_info")
            return
        raise _SseResponseError("LVS SSE event has unsupported media_info")

    @staticmethod
    def _validate_sse_choice(value: Any) -> str:
        if not isinstance(value, dict) or set(value) != {
            "finish_reason",
            "index",
            "message",
        }:
            raise _SseResponseError("LVS SSE event has an invalid summary choice")
        message = value.get("message")
        if (
            value.get("finish_reason") != "stop"
            or value.get("index") != 0
            or not isinstance(message, dict)
            or set(message) != {"content", "role"}
            or message.get("role") != "assistant"
        ):
            raise _SseResponseError("LVS SSE event has an invalid summary choice")
        content = message.get("content")
        if not isinstance(content, str) or not content or len(content) > 1_000_000:
            raise _SseResponseError("LVS SSE event has invalid summary content")
        return content

    @staticmethod
    def _validate_sse_usage(value: Any) -> None:
        if not isinstance(value, dict) or set(value) != {
            "total_chunks_processed",
            "query_processing_time",
        }:
            raise _SseResponseError("LVS SSE completion has invalid usage")
        for field in ("total_chunks_processed", "query_processing_time"):
            item = value[field]
            if (
                isinstance(item, bool)
                or not isinstance(item, int)
                or not 0 <= item <= 1_000_000
            ):
                raise _SseResponseError("LVS SSE completion has invalid usage")

    def _validate_summarize_sse(
        self, body: bytes, request_arguments: Dict[str, Any], *, max_events: int
    ) -> Dict[str, Any]:
        """Validate and retain every source event from a completed summarize stream."""

        payloads = self._parse_sse_body(body, max_events=max_events)
        if payloads[-1] != "[DONE]" or "[DONE]" in payloads[:-1]:
            raise _SseResponseError("LVS SSE response is missing one terminal [DONE] event")

        stream_events: List[Dict[str, Any]] = []
        completion_event: Optional[Dict[str, Any]] = None
        identity: Optional[tuple[str, str, str, int]] = None
        expected_model = request_arguments.get("model")
        expected_video_id = request_arguments.get("id")
        if not isinstance(expected_model, str):
            raise _SseResponseError("LVS SSE request model identity is invalid")
        if expected_video_id is not None and not isinstance(expected_video_id, str):
            raise _SseResponseError("LVS SSE request video identity is invalid")

        required = {
            "id",
            "video_id",
            "model",
            "created",
            "object",
            "media_info",
            "choices",
            "usage",
        }
        for raw in payloads[:-1]:
            try:
                event = json.loads(raw, object_pairs_hook=_reject_duplicate_json_keys)
            except _SseResponseError:
                raise
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise _SseResponseError("LVS SSE event contains malformed JSON") from exc
            if not isinstance(event, dict) or set(event) != required:
                raise _SseResponseError("LVS SSE event has an unexpected response shape")

            request_id = self._validated_uuid(event["id"], "LVS SSE request id")
            video_id = self._validated_uuid(event["video_id"], "LVS SSE video id")
            model = event["model"]
            created = event["created"]
            if (
                not isinstance(model, str)
                or not model
                or len(model) > 1024
                or isinstance(created, bool)
                or not isinstance(created, int)
                or not 0 <= created <= 4_000_000_000
            ):
                raise _SseResponseError("LVS SSE event has invalid response identity")
            current_identity = (request_id, video_id, model, created)
            if identity is None:
                identity = current_identity
            elif identity != current_identity:
                raise _SseResponseError("LVS SSE response identity changed between events")
            if model != expected_model or (
                expected_video_id is not None and video_id != expected_video_id
            ):
                raise _SseResponseError("LVS SSE response does not match the request identity")

            if event["object"] == "summarization.progressing":
                if completion_event is not None:
                    raise _SseResponseError("LVS SSE progress followed its completion event")
                if event["usage"] is not None:
                    raise _SseResponseError("LVS SSE progress event contains unexpected usage")
                self._validate_sse_media_info(event["media_info"])
                choices = event["choices"]
                if not isinstance(choices, list) or len(choices) != 1:
                    raise _SseResponseError("LVS SSE progress has invalid choices")
                content = self._validate_sse_choice(choices[0])
                if content.startswith("Summarization failed. "):
                    raise _SseResponseError(content)
                stream_events.append(event)
                continue

            if event["object"] == "summarization.completion":
                if completion_event is not None:
                    raise _SseResponseError("LVS SSE response has duplicate completion events")
                if not stream_events:
                    raise _SseResponseError("LVS SSE completion has no summary events")
                if event["media_info"] is not None or event["choices"] != []:
                    raise _SseResponseError("LVS SSE completion has an unexpected response shape")
                self._validate_sse_usage(event["usage"])
                completion_event = event
                continue

            raise _SseResponseError("LVS SSE event has an unexpected object type")

        if not stream_events:
            raise _SseResponseError("LVS SSE response contains no summary events")
        return {
            "stream_events": stream_events,
            "completion_event": completion_event,
            "terminal": "[DONE]",
        }

    async def _call_sse_api(
        self, method: str, path: str, *, request_arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Consume the in-process LVS SSE route without httpx's full-body buffering."""

        max_bytes, max_events, timeout_seconds = self._sse_limits()
        request_body = json.dumps(
            request_arguments, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        request_sent = False
        disconnect_delivered = False
        disconnect_requested = asyncio.Event()
        receive_lock = asyncio.Lock()
        response_started = False
        response_complete = False
        policy_error: Optional[_SseResponseError] = None
        status_code: Optional[int] = None
        response_headers: List[tuple[bytes, bytes]] = []
        response_body = bytearray()
        event_count = 0
        frame = bytearray()
        previous_was_cr = False

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "headers": [
                (b"content-type", b"application/json"),
                (b"accept", b"text/event-stream"),
                (b"content-length", str(len(request_body)).encode("ascii")),
            ],
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "server": ("test", 80),
            "client": ("127.0.0.1", 0),
            "root_path": "",
        }

        async def receive() -> Dict[str, Any]:
            nonlocal disconnect_delivered, request_sent
            async with receive_lock:
                if not request_sent:
                    request_sent = True
                    return {
                        "type": "http.request",
                        "body": request_body,
                        "more_body": False,
                    }
            await disconnect_requested.wait()
            async with receive_lock:
                if not disconnect_delivered:
                    disconnect_delivered = True
                    return {"type": "http.disconnect"}
            # ASGI applications must treat disconnect as terminal. If a broken
            # application asks again, do not manufacture a second disconnect.
            await asyncio.Future()
            raise AssertionError("unreachable")

        def set_policy_error(message: str) -> None:
            nonlocal policy_error
            if policy_error is None:
                policy_error = _SseResponseError(message)
                disconnect_requested.set()

        def accept_byte(value: int) -> None:
            nonlocal event_count
            frame.append(value)
            if frame.endswith(b"\n\n"):
                candidate = frame[:-2]
                if any(
                    line and not line.startswith(b":")
                    for line in candidate.split(b"\n")
                ):
                    event_count += 1
                    if event_count > max_events:
                        set_policy_error("LVS SSE response exceeded the event limit")
                frame.clear()

        async def send(message: Dict[str, Any]) -> None:
            nonlocal response_started, response_complete, status_code, previous_was_cr
            if policy_error is not None:
                raise policy_error
            if disconnect_requested.is_set():
                raise _SseResponseError(
                    "LVS SSE response continued after client disconnect"
                )
            message_type = message.get("type")
            if message_type == "http.response.start":
                if response_started:
                    raise _SseResponseError("LVS SSE response started more than once")
                status_code = message.get("status")
                headers = message.get("headers", [])
                if not isinstance(status_code, int) or not isinstance(headers, list):
                    raise _SseResponseError("LVS SSE response has invalid ASGI metadata")
                response_headers.extend(headers)
                response_started = True
                return
            if message_type != "http.response.body" or not response_started:
                raise _SseResponseError("LVS SSE response has an invalid ASGI message")
            if response_complete:
                raise _SseResponseError("LVS SSE response continued after completion")
            chunk = message.get("body", b"")
            if not isinstance(chunk, bytes):
                raise _SseResponseError("LVS SSE response body is not bytes")
            if policy_error is None:
                if len(response_body) + len(chunk) > max_bytes:
                    set_policy_error("LVS SSE response exceeded the byte limit")
                else:
                    response_body.extend(chunk)
                    for value in chunk:
                        if previous_was_cr:
                            accept_byte(ord("\n"))
                            previous_was_cr = False
                            if value == ord("\n"):
                                continue
                        if value == ord("\r"):
                            previous_was_cr = True
                        else:
                            accept_byte(value)
                        if policy_error is not None:
                            break
            if policy_error is not None:
                raise policy_error
            if not message.get("more_body", False):
                if previous_was_cr and policy_error is None:
                    accept_byte(ord("\n"))
                    previous_was_cr = False
                response_complete = True

        self._reserve_sse_stream()
        try:
            app_task = asyncio.create_task(self._lvs_server._app(scope, receive, send))
        except BaseException:
            self._release_sse_stream()
            raise

        caller_cancelled: Optional[asyncio.CancelledError] = None
        policy_waiter = asyncio.create_task(disconnect_requested.wait())
        try:
            finished, _ = await asyncio.wait(
                {app_task, policy_waiter},
                timeout=timeout_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
        except asyncio.CancelledError as exc:
            caller_cancelled = exc
            disconnect_requested.set()
            finished = set()
        finally:
            if not policy_waiter.done():
                policy_waiter.cancel()

        app_finished = app_task in finished
        if not finished and caller_cancelled is None:
            set_policy_error("LVS SSE response exceeded the time limit")

        if caller_cancelled is not None or policy_error is not None:
            try:
                cleaned, _ = await asyncio.wait(
                    {app_task}, timeout=self._sse_disconnect_grace_seconds()
                )
            except asyncio.CancelledError:
                # A repeated caller cancellation must still propagate promptly.
                # Preserve the task and capacity until its eventual exit.
                if app_task.done():
                    self._release_sse_stream()
                    try:
                        app_task.result()
                    except BaseException:
                        pass
                else:
                    self._retain_sse_stream_task(app_task)
                raise

            if cleaned:
                self._release_sse_stream()
                try:
                    app_task.result()
                except BaseException:
                    # The initiating cancellation/policy error remains the
                    # authoritative result after terminal app cleanup.
                    pass
            else:
                self._retain_sse_stream_task(app_task)

            if caller_cancelled is not None:
                raise caller_cancelled
            if not cleaned:
                raise _SseResponseError(
                    f"{policy_error}; ASGI disconnect cleanup exceeded the grace "
                    "period and its capacity remains retained"
                )
            raise policy_error

        if not app_finished:
            self._retain_sse_stream_task(app_task)
            raise _SseResponseError(
                "LVS SSE response terminated without an app result; capacity remains retained"
            )
        self._release_sse_stream()
        try:
            app_task.result()
        except BaseException as exc:
            stream_error = _find_sse_response_error(exc)
            if stream_error is not None:
                raise stream_error from exc
            raise _SseResponseError("LVS SSE response terminated unexpectedly") from exc

        if not response_started or not response_complete or status_code is None:
            raise _SseResponseError("LVS SSE response ended before ASGI completion")
        if policy_error is not None:
            raise policy_error
        content_types = [
            value.decode("latin-1")
            for key, value in response_headers
            if key.lower() == b"content-type"
        ]
        if status_code >= 400:
            try:
                error = json.loads(
                    bytes(response_body), object_pairs_hook=_reject_duplicate_json_keys
                )
            except (json.JSONDecodeError, UnicodeDecodeError, _SseResponseError) as exc:
                raise _SseResponseError(
                    f"LVS SSE request failed with HTTP {status_code} and malformed JSON"
                ) from exc
            if isinstance(error, dict):
                detail = error.get("detail")
                if isinstance(detail, dict):
                    code = error.get("code", detail.get("code", "Error"))
                    message = error.get("message", detail.get("message", str(detail)))
                else:
                    code = error.get("code", "Error")
                    message = error.get(
                        "message", str(detail if detail is not None else error)
                    )
                raise _SseResponseError(f"{code}: {message}")
            raise _SseResponseError(f"HTTP {status_code}: {error}")
        if status_code != 200:
            raise _SseResponseError(
                f"LVS SSE request returned unexpected HTTP {status_code}"
            )
        if (
            len(content_types) != 1
            or content_types[0].split(";", 1)[0].strip().lower()
            != "text/event-stream"
        ):
            raise _SseResponseError("LVS SSE response has an unexpected content type")
        return self._validate_summarize_sse(
            bytes(response_body), request_arguments, max_events=max_events
        )

    async def _list_models(self) -> Dict[str, Any]:
        """List available models by calling the HTTP API."""
        return await self._call_http_api("GET", f"{API_PREFIX}/models")

    @staticmethod
    def _validate_arguments(
        arguments: Dict[str, Any], *, allowed: set[str], required: set[str]
    ) -> None:
        if not isinstance(arguments, dict):
            raise ValueError("tool arguments must be an object")
        unknown = sorted(set(arguments) - allowed)
        if unknown:
            raise ValueError(f"unsupported arguments: {', '.join(unknown)}")
        missing = sorted(required - set(arguments))
        if missing:
            raise ValueError(f"missing required arguments: {', '.join(missing)}")

    @staticmethod
    def _validated_uuid(value: Any, field: str) -> str:
        if not isinstance(value, str):
            raise ValueError(f"{field} must be a UUID string")
        try:
            parsed = UUID(value)
        except (ValueError, AttributeError) as exc:
            raise ValueError(f"{field} must be a valid UUID") from exc
        canonical = str(parsed)
        if value != canonical or parsed.int == 0:
            raise ValueError(f"{field} must be a canonical non-nil UUID")
        return canonical

    @classmethod
    def _validate_file_info(
        cls,
        value: Any,
        *,
        expected_id: Optional[str] = None,
        expected_filename: Optional[str] = None,
        expected_bytes: Optional[int] = None,
        require_media_type: bool,
    ) -> Dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("LVS returned invalid file metadata")
        if expected_id is not None and "id" in value:
            response_id = cls._validated_uuid(value["id"], "response id")
            if response_id != expected_id:
                raise ValueError("LVS returned an unexpected asset identity")
        required = {"id", "bytes", "filename", "purpose"}
        if require_media_type:
            required.add("media_type")
        if not required.issubset(value):
            raise ValueError("LVS returned incomplete file metadata")

        cls._validated_uuid(value["id"], "response id")
        byte_count = value["bytes"]
        if (
            isinstance(byte_count, bool)
            or not isinstance(byte_count, int)
            or not 0 <= byte_count <= _MAX_CONFIGURABLE_MEDIA_BYTES
        ):
            raise ValueError("LVS returned an invalid file size")
        if expected_bytes is not None and byte_count != expected_bytes:
            raise ValueError("LVS returned an unexpected file size")
        filename = value["filename"]
        if (
            not isinstance(filename, str)
            or not 0 < len(filename) <= 256
            or filename in {".", ".."}
            or "/" in filename
            or "\\" in filename
            or "\x00" in filename
        ):
            raise ValueError("LVS returned an invalid filename")
        if expected_filename is not None and filename != expected_filename:
            raise ValueError("LVS returned an unexpected filename")
        if value["purpose"] != "vision":
            raise ValueError("LVS returned an unexpected file purpose")
        if "media_type" in value and value["media_type"] != "video":
            raise ValueError("LVS returned an unexpected media type")
        if require_media_type and value.get("media_type") != "video":
            raise ValueError("LVS returned incomplete file metadata")
        creation_time = value.get("creation_time")
        if creation_time is not None:
            if not isinstance(
                creation_time, str
            ) or not _RFC3339_MILLISECONDS.fullmatch(creation_time):
                raise ValueError("LVS returned an invalid creation time")
            try:
                datetime.strptime(creation_time, "%Y-%m-%dT%H:%M:%S.%fZ")
            except ValueError as exc:
                raise ValueError("LVS returned an invalid creation time") from exc
        sensor_name = value.get("sensor_name", "")
        if not isinstance(sensor_name, str) or not _SENSOR_NAME.fullmatch(sensor_name):
            raise ValueError("LVS returned an invalid sensor name")
        fields = (
            "id",
            "bytes",
            "filename",
            "purpose",
            "creation_time",
            "sensor_name",
            "media_type",
        )
        return {field: value[field] for field in fields if field in value}

    @staticmethod
    def _media_size_limit() -> int:
        raw = os.environ.get("LVS_MCP_MAX_FILE_BYTES", str(_DEFAULT_MAX_MEDIA_BYTES))
        if not raw.isdecimal():
            raise ValueError("LVS_MCP_MAX_FILE_BYTES must be a positive integer")
        limit = int(raw)
        if not 0 < limit <= _MAX_CONFIGURABLE_MEDIA_BYTES:
            raise ValueError(
                "LVS_MCP_MAX_FILE_BYTES must be between 1 and 100000000000"
            )
        return limit

    @staticmethod
    def _open_media_file(path: Any) -> tuple[int, str, os.stat_result]:
        if not isinstance(path, str) or not 0 < len(path) <= 1024:
            raise ValueError(
                "path must be a non-empty string of at most 1024 characters"
            )
        relative = Path(path)
        if relative.is_absolute() or any(
            part in {"", ".", ".."} for part in relative.parts
        ):
            raise ValueError("path must be a normalized relative path")

        configured = os.environ.get("LVS_MCP_MEDIA_ROOT", "").strip()
        if not configured:
            raise ValueError("LVS_MCP_MEDIA_ROOT is required for add_file")
        root_path = Path(configured)
        try:
            root = root_path.resolve(strict=True)
        except (OSError, ValueError) as exc:
            raise ValueError(
                "LVS_MCP_MEDIA_ROOT must be an absolute non-symlink directory"
            ) from exc
        if not root_path.is_absolute() or root != root_path or not root.is_dir():
            raise ValueError(
                "LVS_MCP_MEDIA_ROOT must be an absolute non-symlink directory"
            )
        if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
            raise ValueError("secure media-root file opening is unavailable")

        directory_flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
        current_directory = os.open(root, directory_flags)
        try:
            for part in relative.parts[:-1]:
                try:
                    component = os.stat(
                        part, dir_fd=current_directory, follow_symlinks=False
                    )
                    if stat.S_ISLNK(component.st_mode):
                        raise ValueError("path cannot contain symlink components")
                    if not stat.S_ISDIR(component.st_mode):
                        raise ValueError(
                            "path must resolve to an existing file beneath the media root"
                        )
                    next_directory = os.open(
                        part, directory_flags, dir_fd=current_directory
                    )
                except ValueError:
                    raise
                except (FileNotFoundError, OSError) as exc:
                    raise ValueError(
                        "path cannot contain symlink components"
                    ) from exc
                os.close(current_directory)
                current_directory = next_directory

            filename = relative.parts[-1]
            try:
                expected = os.stat(
                    filename, dir_fd=current_directory, follow_symlinks=False
                )
            except (FileNotFoundError, OSError, ValueError) as exc:
                raise ValueError(
                    "path must resolve to an existing file beneath the media root"
                ) from exc
            if stat.S_ISLNK(expected.st_mode):
                raise ValueError("path cannot contain symlink components")
            if not stat.S_ISREG(expected.st_mode):
                raise ValueError("path must resolve to a regular file")
            if expected.st_size <= 0:
                raise ValueError("path must resolve to a non-empty regular file")
            if expected.st_size > LvsMCPServer._media_size_limit():
                raise ValueError("path exceeds LVS_MCP_MAX_FILE_BYTES")

            file_flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
            try:
                descriptor = os.open(filename, file_flags, dir_fd=current_directory)
            except OSError as exc:
                raise ValueError("path changed while opening") from exc
            try:
                opened = os.fstat(descriptor)
                if not stat.S_ISREG(opened.st_mode) or (
                    opened.st_dev,
                    opened.st_ino,
                    opened.st_size,
                ) != (expected.st_dev, expected.st_ino, expected.st_size):
                    raise ValueError("path changed while opening")
            except BaseException:
                os.close(descriptor)
                raise
            return descriptor, filename, opened
        finally:
            os.close(current_directory)

    async def _add_file(self, args: Dict[str, Any]) -> Dict[str, Any]:
        self._validate_arguments(
            args,
            allowed={"path", "creation_time", "sensor_name"},
            required={"path"},
        )
        file_id = str(uuid4())
        data = {"purpose": "vision", "media_type": "video", "id": file_id}
        if "creation_time" in args:
            creation_time = args["creation_time"]
            if not isinstance(
                creation_time, str
            ) or not _RFC3339_MILLISECONDS.fullmatch(creation_time):
                raise ValueError("creation_time must use YYYY-MM-DDTHH:MM:SS.mmmZ")
            try:
                datetime.strptime(creation_time, "%Y-%m-%dT%H:%M:%S.%fZ")
            except ValueError as exc:
                raise ValueError("creation_time must be a valid UTC timestamp") from exc
            data["creation_time"] = creation_time
        if "sensor_name" in args:
            sensor_name = args["sensor_name"]
            if not isinstance(sensor_name, str) or not _SENSOR_NAME.fullmatch(
                sensor_name
            ):
                raise ValueError("sensor_name contains unsupported characters")
            data["sensor_name"] = sensor_name

        size_limit = self._media_size_limit()
        descriptor, filename, opened = self._open_media_file(args["path"])
        try:
            try:
                with os.fdopen(descriptor, "rb") as media:
                    descriptor = -1
                    bounded_media = _BoundedMediaReader(media, size_limit)
                    result = await self._call_http_api(
                        "POST",
                        f"{API_PREFIX}/files",
                        data=data,
                        files={
                            "file": (
                                filename,
                                bounded_media,
                                "application/octet-stream",
                            )
                        },
                    )
            finally:
                if descriptor >= 0:
                    os.close(descriptor)
            return self._validate_file_info(
                result,
                expected_id=file_id,
                expected_filename=filename,
                expected_bytes=opened.st_size,
                require_media_type=True,
            )
        except Exception:
            try:
                await self._call_http_api("DELETE", f"{API_PREFIX}/files/{file_id}")
            except Exception as cleanup_error:
                logger.warning(
                    "Best-effort cleanup failed for rejected LVS file asset %s: %s",
                    file_id,
                    cleanup_error,
                )
            raise

    async def _list_files(self, args: Dict[str, Any]) -> Dict[str, Any]:
        self._validate_arguments(args, allowed=set(), required=set())
        result = await self._call_http_api(
            "GET", f"{API_PREFIX}/files", params={"purpose": "vision"}
        )
        data = result.get("data") if isinstance(result, dict) else None
        if (
            not isinstance(result, dict)
            or result.get("object") != "list"
            or not isinstance(data, list)
            or len(data) > 1_000_000
        ):
            raise ValueError("LVS list_files returned an invalid response")
        return {
            "object": "list",
            "data": [
                self._validate_file_info(item, require_media_type=True)
                for item in data
            ],
        }

    async def _get_file_info(self, args: Dict[str, Any]) -> Dict[str, Any]:
        self._validate_arguments(args, allowed={"file_id"}, required={"file_id"})
        file_id = self._validated_uuid(args["file_id"], "file_id")
        result = await self._call_http_api("GET", f"{API_PREFIX}/files/{file_id}")
        return self._validate_file_info(
            result, expected_id=file_id, require_media_type=False
        )

    async def _delete_file(self, args: Dict[str, Any]) -> Dict[str, Any]:
        self._validate_arguments(
            args,
            allowed={"file_id", "confirm_file_id"},
            required={"file_id", "confirm_file_id"},
        )
        file_id = self._validated_uuid(args["file_id"], "file_id")
        confirmation = self._validated_uuid(args["confirm_file_id"], "confirm_file_id")
        if confirmation != file_id:
            raise ValueError("confirm_file_id must exactly match file_id")
        result = await self._call_http_api("DELETE", f"{API_PREFIX}/files/{file_id}")
        if (
            not isinstance(result, dict)
            or str(result.get("id")) != file_id
            or result.get("object") != "file"
            or result.get("deleted") is not True
        ):
            raise ValueError("LVS delete_file returned an invalid confirmation")
        return result

    async def _health_ready(self) -> Dict[str, Any]:
        """Report readiness only after the LVS readiness route succeeds."""
        await self._call_http_api("GET", "/v1/ready", return_text=True)
        return {"status": "ready", "code": 200}

    async def _health_live(self) -> Dict[str, Any]:
        """Report liveness only after the LVS liveness route succeeds."""
        await self._call_http_api("GET", "/v1/live", return_text=True)
        return {"status": "alive", "code": 200}

    async def _summarize_video(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Summarize a video by calling the HTTP API."""
        if args.get("stream") is True:
            return await self._call_sse_api(
                "POST", f"{API_PREFIX}/summarize", request_arguments=args
            )
        return await self._call_http_api("POST", f"{API_PREFIX}/summarize", json=args)

    async def _generate_vlm_captions(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Generate VLM captions by calling the HTTP API."""
        return await self._call_http_api("POST", f"{API_PREFIX}/generate_vlm_captions", json=args)

    async def _generate_captions(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Start stream captioning by calling the HTTP API."""
        return await self._call_http_api("POST", "/v1/generate_captions", json=args)

    async def _stream_summarize(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Summarize a stream by calling the HTTP API."""
        return await self._call_http_api("POST", "/v1/stream_summarize", json=args)

    async def _get_recommended_config(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get recommended config by calling the HTTP API."""
        return await self._call_http_api("POST", f"{API_PREFIX}/recommended_config", json=args)

    async def _get_metrics(self) -> Dict[str, Any]:
        """Get metrics by calling the HTTP API."""
        result = await self._call_http_api("GET", f"{API_PREFIX}/metrics", return_text=True)
        return {"metrics": result["text"], "format": "prometheus"}

    async def run(self, port: Optional[int] = None):
        """Run the MCP server on stdio or SSE (if port specified).

        Args:
            port: If specified, run MCP server on SSE transport with this port.
                  If None, run on stdio transport (default).
        """
        if port is not None:
            # Run with SSE transport on specified port
            host = _mcp_bind_host()
            logger.info(f"Starting LVS MCP server on SSE (http://{host}:{port}/sse)...")

            from starlette.requests import Request

            # Create SSE transport - this manages sessions internally
            sse = SessionCleaningSseServerTransport("/messages")

            async def handle_sse(request: Request) -> None:
                """Handle SSE endpoint - establishes the event stream."""
                async with sse.connect_sse(
                    request.scope,
                    request.receive,
                    request._send,
                ) as streams:
                    # Run the MCP server protocol over these streams
                    await self._server.run(
                        streams[0],
                        streams[1],
                        self._server.create_initialization_options(),
                    )

            # Create a custom ASGI app that routes requests
            async def app_router(scope, receive, send):
                """Route requests to appropriate handlers."""
                if scope["type"] == "http":
                    path = scope["path"]
                    method = scope["method"]

                    # Handle /messages POST
                    if path == "/messages" and method == "POST":
                        await sse.handle_post_message(scope, receive, send)
                        return

                    # Handle /sse GET (for SSE connection)
                    if path == "/sse" and method == "GET":
                        # Create a Request object for the handler
                        from starlette.requests import Request

                        request = Request(scope, receive, send)
                        await handle_sse(request)
                        return

                    # 404 for other paths
                    await send(
                        {
                            "type": "http.response.start",
                            "status": 404,
                            "headers": [[b"content-type", b"text/plain"]],
                        }
                    )
                    await send(
                        {
                            "type": "http.response.body",
                            "body": b"Not Found",
                        }
                    )
                else:
                    # Handle other ASGI types if needed
                    pass

            import uvicorn

            config = uvicorn.Config(app_router, host=host, port=port, log_level="info")
            server = uvicorn.Server(config)
            await server.serve()
        else:
            # Run with stdio transport (default)
            logger.info("Starting LVS MCP server on stdio...")
            async with stdio_server() as (read_stream, write_stream):
                await self._server.run(
                    read_stream,
                    write_stream,
                    self._server.create_initialization_options(),
                )


async def run_mcp_server(lvs_server_instance):
    """Entry point to run MCP server with a LvsServer instance.

    Checks LVS_MCP_PORT environment variable:
    - If set to a port number: runs MCP server on SSE transport at that port
    - If not set or empty: runs MCP server on stdio transport (default)
    """
    mcp_port_str = os.environ.get("LVS_MCP_PORT", "").strip()
    mcp_port = None

    if mcp_port_str:
        try:
            mcp_port = int(mcp_port_str)
        except ValueError as exc:
            raise ValueError(
                "LVS_MCP_PORT must be an integer from 1 through 65535"
            ) from exc
        if not 1 <= mcp_port <= 65535:
            raise ValueError("LVS_MCP_PORT must be an integer from 1 through 65535")
        logger.info(f"LVS_MCP_PORT={mcp_port} detected, will use SSE transport")

    mcp_server = LvsMCPServer(lvs_server_instance)
    await mcp_server.run(port=mcp_port)
