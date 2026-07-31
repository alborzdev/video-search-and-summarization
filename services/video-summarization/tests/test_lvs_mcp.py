# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import asyncio
import logging
import sys
import types
import unittest

from fastapi import Body, FastAPI, Response
from fastapi.responses import JSONResponse

# The source distribution intentionally has no runtime dependency list; the
# released LVS image supplies MCP. Keep these dispatch tests runnable from a
# plain checkout by stubbing only the registration types when MCP is absent.
# HTTP behavior still uses the real FastAPI/httpx stack, while an image-hosted
# run retains coverage of the real MCP registration classes.
try:
    __import__("mcp.server")
except ModuleNotFoundError:
    mcp_module = types.ModuleType("mcp")
    mcp_server_module = types.ModuleType("mcp.server")
    mcp_sse_module = types.ModuleType("mcp.server.sse")
    mcp_stdio_module = types.ModuleType("mcp.server.stdio")
    mcp_types_module = types.ModuleType("mcp.types")

    class StubServer:
        def __init__(self, _name):
            pass

        @staticmethod
        def list_tools():
            return lambda function: function

        @staticmethod
        def call_tool():
            return lambda function: function

    class StubRecord:
        def __init__(self, *_args, **values):
            self.__dict__.update(values)

    mcp_server_module.Server = StubServer
    mcp_sse_module.SseServerTransport = StubRecord
    mcp_stdio_module.stdio_server = StubRecord
    mcp_types_module.TextContent = StubRecord
    mcp_types_module.Tool = StubRecord
    mcp_module.server = mcp_server_module
    sys.modules.update(
        {
            "mcp": mcp_module,
            "mcp.server": mcp_server_module,
            "mcp.server.sse": mcp_sse_module,
            "mcp.server.stdio": mcp_stdio_module,
            "mcp.types": mcp_types_module,
        }
    )

via_logger_module = types.ModuleType("via_logger")
via_logger_module.logger = logging.getLogger("lvs-mcp-test")
sys.modules["via_logger"] = via_logger_module

from lvs_mcp import LvsMCPServer  # noqa: E402


class FakeLvsServer:
    def __init__(self):
        self._app = FastAPI()


class TestLvsMcpHealth(unittest.TestCase):
    def test_ready_and_live_tools_probe_the_real_routes(self):
        lvs = FakeLvsServer()

        @lvs._app.get("/v1/ready")
        async def ready():
            return Response(status_code=200)

        @lvs._app.get("/v1/live")
        async def live():
            return Response(status_code=200)

        mcp = LvsMCPServer(lvs)

        self.assertEqual(
            asyncio.run(mcp._handle_tool_call("health_ready", {})),
            {"status": "ready", "code": 200},
        )
        self.assertEqual(
            asyncio.run(mcp._handle_tool_call("health_live", {})),
            {"status": "alive", "code": 200},
        )

    def test_ready_tool_propagates_dependency_failure(self):
        lvs = FakeLvsServer()

        @lvs._app.get("/v1/ready")
        async def ready():
            return JSONResponse(
                status_code=503,
                content={
                    "code": "DependencyUnavailable",
                    "message": "RTVI VLM service is not ready",
                },
            )

        mcp = LvsMCPServer(lvs)

        with self.assertRaisesRegex(ValueError, "RTVI VLM service is not ready"):
            asyncio.run(mcp._handle_tool_call("health_ready", {}))

    def test_generate_vlm_captions_tool_reaches_the_advertised_dev_route(self):
        lvs = FakeLvsServer()

        @lvs._app.post("/generate_vlm_captions")
        async def generate(payload: dict = Body()):
            return {"accepted": True, "prompt": payload["prompt"]}

        mcp = LvsMCPServer(lvs)
        result = asyncio.run(
            mcp._handle_tool_call(
                "generate_vlm_captions",
                {"url": "file:///tmp/test.mp4", "prompt": "Describe it", "model": "local"},
            )
        )

        self.assertEqual(result, {"accepted": True, "prompt": "Describe it"})
