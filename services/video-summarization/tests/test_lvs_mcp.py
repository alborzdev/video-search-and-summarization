# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import asyncio
import io
import json
import logging
import os
import socket
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock
from uuid import UUID

from fastapi import Body, FastAPI, Request, Response
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
from lvs_mcp import _BoundedMediaReader  # noqa: E402
from lvs_mcp import _mcp_bind_host  # noqa: E402
from lvs_mcp import run_mcp_server  # noqa: E402
from rtvi_vlm_client import RTVI_HEALTH_TIMEOUT  # noqa: E402
from rtvi_vlm_client import RtviError  # noqa: E402
from rtvi_vlm_client import RtviVlmClient  # noqa: E402


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
                {
                    "url": "file:///tmp/test.mp4",
                    "prompt": "Describe it",
                    "model": "local",
                },
            )
        )

        self.assertEqual(result, {"accepted": True, "prompt": "Describe it"})


class TestLvsMcpFileManagement(unittest.TestCase):
    FILE_ID = "12345678-1234-4678-9234-567812345678"

    def test_exact_thirteen_tools_and_fail_closed_file_schemas(self):
        mcp = LvsMCPServer(FakeLvsServer())
        tools = asyncio.run(mcp._list_tools_handler())
        by_name = {tool.name: tool.inputSchema for tool in tools}
        self.assertEqual(len(tools), 13)
        self.assertEqual(len(by_name), 13)
        self.assertEqual(
            set(by_name),
            {
                "health_ready",
                "health_live",
                "list_models",
                "add_file",
                "list_files",
                "get_file_info",
                "delete_file",
                "summarize_video",
                "generate_vlm_captions",
                "generate_captions",
                "stream_summarize",
                "get_recommended_config",
                "get_metrics",
            },
        )
        for name in ("add_file", "list_files", "get_file_info", "delete_file"):
            self.assertIs(by_name[name]["additionalProperties"], False)
        self.assertEqual(
            set(by_name["add_file"]["properties"]),
            {"path", "creation_time", "sensor_name"},
        )
        self.assertEqual(by_name["list_files"]["properties"], {})
        self.assertEqual(
            set(by_name["delete_file"]["required"]),
            {"file_id", "confirm_file_id"},
        )

    def test_add_list_info_delete_dispatches_through_lvs_app(self):
        lvs = FakeLvsServer()
        assets = {}

        @lvs._app.post("/files")
        async def add(request: Request):
            form = await request.form()
            upload = form["file"]
            content = await upload.read()
            await upload.close()
            file_id = str(form["id"])
            self.assertEqual(form["purpose"], "vision")
            self.assertEqual(form["media_type"], "video")
            self.assertEqual(upload.filename, "clip.mp4")
            assets[file_id] = {
                "id": file_id,
                "bytes": len(content),
                "filename": upload.filename,
                "purpose": "vision",
                "media_type": "video",
                "creation_time": form.get("creation_time"),
                "sensor_name": form.get("sensor_name", ""),
            }
            return assets[file_id]

        @lvs._app.get("/files")
        async def listing(request: Request):
            self.assertEqual(request.query_params.get("purpose"), "vision")
            return {"object": "list", "data": list(assets.values())}

        @lvs._app.get("/files/{file_id}")
        async def info(file_id: str):
            return assets[file_id]

        @lvs._app.delete("/files/{file_id}")
        async def delete(file_id: str):
            assets.pop(file_id)
            return {"id": file_id, "object": "file", "deleted": True}

        mcp = LvsMCPServer(lvs)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "clip.mp4").write_bytes(b"video-bytes")
            environment = {
                "LVS_MCP_MEDIA_ROOT": str(root),
                "LVS_MCP_MAX_FILE_BYTES": "1024",
            }
            with (
                mock.patch.dict(os.environ, environment),
                mock.patch("lvs_mcp.uuid4", return_value=UUID(self.FILE_ID)),
            ):
                added = asyncio.run(
                    mcp._handle_tool_call(
                        "add_file",
                        {
                            "path": "clip.mp4",
                            "creation_time": "2026-08-01T12:30:45.123Z",
                            "sensor_name": "camera-1",
                        },
                    )
                )
                self.assertEqual(added["id"], self.FILE_ID)
                listed = asyncio.run(mcp._handle_tool_call("list_files", {}))
                self.assertEqual(
                    [item["id"] for item in listed["data"]], [self.FILE_ID]
                )
                inspected = asyncio.run(
                    mcp._handle_tool_call("get_file_info", {"file_id": self.FILE_ID})
                )
                self.assertEqual(inspected["filename"], "clip.mp4")
                deleted = asyncio.run(
                    mcp._handle_tool_call(
                        "delete_file",
                        {"file_id": self.FILE_ID, "confirm_file_id": self.FILE_ID},
                    )
                )
                self.assertIs(deleted["deleted"], True)
                self.assertEqual(assets, {})

    def test_add_file_rejects_unconfigured_escape_symlinks_empty_and_oversize(self):
        mcp = LvsMCPServer(FakeLvsServer())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "empty.mp4").write_bytes(b"")
            (root / "large.mp4").write_bytes(b"12")
            outside = root.parent / f"{root.name}-outside.mp4"
            outside.write_bytes(b"x")
            (root / "link.mp4").symlink_to(outside)
            try:
                with mock.patch.dict(os.environ, {"LVS_MCP_MEDIA_ROOT": ""}):
                    with self.assertRaisesRegex(
                        ValueError, "LVS_MCP_MEDIA_ROOT is required"
                    ):
                        asyncio.run(
                            mcp._handle_tool_call("add_file", {"path": "large.mp4"})
                        )
                with mock.patch.dict(
                    os.environ,
                    {"LVS_MCP_MEDIA_ROOT": str(root), "LVS_MCP_MAX_FILE_BYTES": "1"},
                ):
                    for path, message in (
                        ("../escape.mp4", "normalized relative path"),
                        (str(outside), "normalized relative path"),
                        ("link.mp4", "symlink"),
                        ("empty.mp4", "non-empty"),
                        ("large.mp4", "exceeds"),
                    ):
                        with (
                            self.subTest(path=path),
                            self.assertRaisesRegex(ValueError, message),
                        ):
                            asyncio.run(
                                mcp._handle_tool_call("add_file", {"path": path})
                            )
            finally:
                outside.unlink(missing_ok=True)

    def test_add_file_rejects_non_object_remote_and_inline_sources(self):
        mcp = LvsMCPServer(FakeLvsServer())
        for arguments, message in (
            (None, "arguments must be an object"),
            ([], "arguments must be an object"),
            ({}, "missing required arguments"),
            (
                {"path": "clip.mp4", "url": "https://example.com/clip.mp4"},
                "unsupported",
            ),
            ({"path": "clip.mp4", "content": "base64-data"}, "unsupported"),
            (
                {"path": "clip.mp4", "headers": {"Authorization": "secret"}},
                "unsupported",
            ),
            ({"path": "clip.mp4", "backend_url": "http://127.0.0.1"}, "unsupported"),
        ):
            with (
                self.subTest(arguments=arguments),
                self.assertRaisesRegex(ValueError, message),
            ):
                asyncio.run(mcp._handle_tool_call("add_file", arguments))

    def test_add_file_rejects_unsafe_root_components_and_metadata(self):
        mcp = LvsMCPServer(FakeLvsServer())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            media = root / "media"
            media.mkdir()
            nested = media / "nested"
            nested.mkdir()
            (nested / "clip.mp4").write_bytes(b"x")
            (media / "directory.mp4").mkdir()
            fifo = media / "fifo.mp4"
            os.mkfifo(fifo)
            linked_directory = media / "linked-directory"
            linked_directory.symlink_to(nested, target_is_directory=True)
            root_link = root / "media-link"
            root_link.symlink_to(media, target_is_directory=True)

            for configured, path, message in (
                ("relative/root", "clip.mp4", "absolute non-symlink"),
                (str(root / "missing"), "clip.mp4", "absolute non-symlink"),
                (str(root_link), "nested/clip.mp4", "absolute non-symlink"),
                (str(media), "linked-directory/clip.mp4", "symlink"),
                (str(media), "directory.mp4", "regular file"),
                (str(media), "fifo.mp4", "regular file"),
                (str(media), "missing.mp4", "existing file"),
                (str(media), "bad\x00name.mp4", "existing file"),
            ):
                with (
                    self.subTest(configured=configured, path=path),
                    mock.patch.dict(os.environ, {"LVS_MCP_MEDIA_ROOT": configured}),
                    self.assertRaisesRegex(ValueError, message),
                ):
                    asyncio.run(mcp._handle_tool_call("add_file", {"path": path}))

            for arguments, message in (
                (
                    {"path": "nested/clip.mp4", "sensor_name": "camera\nforged"},
                    "sensor_name",
                ),
                ({"path": "nested/clip.mp4", "sensor_name": True}, "sensor_name"),
                (
                    {
                        "path": "nested/clip.mp4",
                        "creation_time": "2026-08-01T12:30:45Z",
                    },
                    "creation_time",
                ),
                (
                    {
                        "path": "nested/clip.mp4",
                        "creation_time": "2026-08-01T12:30:45.123+00:00",
                    },
                    "creation_time",
                ),
            ):
                with (
                    self.subTest(arguments=arguments),
                    mock.patch.dict(os.environ, {"LVS_MCP_MEDIA_ROOT": str(media)}),
                    self.assertRaisesRegex(ValueError, message),
                ):
                    asyncio.run(mcp._handle_tool_call("add_file", arguments))

    def test_add_file_size_limit_configuration_fails_closed(self):
        mcp = LvsMCPServer(FakeLvsServer())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "clip.mp4").write_bytes(b"x")
            for value in ("", "0", "-1", "1.5", "100000000001"):
                with (
                    self.subTest(value=value),
                    mock.patch.dict(
                        os.environ,
                        {
                            "LVS_MCP_MEDIA_ROOT": str(root),
                            "LVS_MCP_MAX_FILE_BYTES": value,
                        },
                    ),
                    self.assertRaisesRegex(ValueError, "LVS_MCP_MAX_FILE_BYTES"),
                ):
                    asyncio.run(mcp._handle_tool_call("add_file", {"path": "clip.mp4"}))

    def test_add_file_uses_only_in_process_asgi_dispatch(self):
        lvs = FakeLvsServer()

        @lvs._app.post("/files")
        async def add(request: Request):
            form = await request.form()
            upload = form["file"]
            content = await upload.read()
            await upload.close()
            return {
                "id": str(form["id"]),
                "bytes": len(content),
                "filename": upload.filename,
                "purpose": "vision",
                "media_type": "video",
            }

        mcp = LvsMCPServer(lvs)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "clip.mp4").write_bytes(b"video")
            with (
                mock.patch.dict(os.environ, {"LVS_MCP_MEDIA_ROOT": str(root)}),
                mock.patch("lvs_mcp.uuid4", return_value=UUID(self.FILE_ID)),
                mock.patch.object(
                    socket,
                    "create_connection",
                    side_effect=AssertionError("network used"),
                ),
            ):
                result = asyncio.run(
                    mcp._handle_tool_call("add_file", {"path": "clip.mp4"})
                )
        self.assertEqual(result["id"], self.FILE_ID)

    def test_arguments_uuid_timestamp_and_delete_confirmation_are_strict(self):
        mcp = LvsMCPServer(FakeLvsServer())
        with self.assertRaisesRegex(ValueError, "unsupported arguments"):
            asyncio.run(mcp._handle_tool_call("list_files", {"purpose": "vision"}))
        for file_id in (
            "00000000-0000-0000-0000-000000000000",
            "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA",
            "not-a-uuid",
        ):
            with self.subTest(file_id=file_id), self.assertRaises(ValueError):
                asyncio.run(
                    mcp._handle_tool_call("get_file_info", {"file_id": file_id})
                )
        with self.assertRaisesRegex(ValueError, "exactly match"):
            asyncio.run(
                mcp._handle_tool_call(
                    "delete_file",
                    {
                        "file_id": self.FILE_ID,
                        "confirm_file_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                    },
                )
            )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "clip.mp4").write_bytes(b"x")
            with mock.patch.dict(os.environ, {"LVS_MCP_MEDIA_ROOT": str(root)}):
                with self.assertRaisesRegex(ValueError, "valid UTC timestamp"):
                    asyncio.run(
                        mcp._handle_tool_call(
                            "add_file",
                            {
                                "path": "clip.mp4",
                                "creation_time": "2026-99-99T12:30:45.123Z",
                            },
                        )
                    )

    def test_malformed_backend_identity_and_envelopes_fail_closed(self):
        mcp = LvsMCPServer(FakeLvsServer())
        mcp._call_http_api = mock.AsyncMock(return_value={"object": "list", "data": {}})
        with self.assertRaisesRegex(ValueError, "invalid response"):
            asyncio.run(mcp._handle_tool_call("list_files", {}))

        mcp._call_http_api = mock.AsyncMock(return_value={"id": str(UUID(int=1))})
        with self.assertRaisesRegex(ValueError, "unexpected asset identity"):
            asyncio.run(
                mcp._handle_tool_call("get_file_info", {"file_id": self.FILE_ID})
            )

        mcp._call_http_api = mock.AsyncMock(
            return_value={"id": self.FILE_ID, "object": "file", "deleted": False}
        )
        with self.assertRaisesRegex(ValueError, "invalid confirmation"):
            asyncio.run(
                mcp._handle_tool_call(
                    "delete_file",
                    {"file_id": self.FILE_ID, "confirm_file_id": self.FILE_ID},
                )
            )

    def test_file_metadata_response_contract_is_strict(self):
        valid = {
            "id": self.FILE_ID,
            "bytes": 5,
            "filename": "clip.mp4",
            "purpose": "vision",
            "media_type": "video",
            "creation_time": "2026-08-01T12:30:45.123Z",
            "sensor_name": "camera-1",
        }
        self.assertEqual(
            LvsMCPServer._validate_file_info(
                valid,
                expected_id=self.FILE_ID,
                expected_filename="clip.mp4",
                expected_bytes=5,
                require_media_type=True,
            ),
            valid,
        )
        invalid_mutations = (
            ("missing id", lambda value: value.pop("id")),
            ("boolean bytes", lambda value: value.__setitem__("bytes", True)),
            ("negative bytes", lambda value: value.__setitem__("bytes", -1)),
            (
                "path filename",
                lambda value: value.__setitem__("filename", "../clip.mp4"),
            ),
            ("wrong purpose", lambda value: value.__setitem__("purpose", "assistants")),
            ("wrong media", lambda value: value.__setitem__("media_type", "image")),
            ("missing media", lambda value: value.pop("media_type")),
            ("bad creation type", lambda value: value.__setitem__("creation_time", [])),
            (
                "bad creation format",
                lambda value: value.__setitem__(
                    "creation_time", "2026-08-01T12:30:45Z"
                ),
            ),
            (
                "impossible creation time",
                lambda value: value.__setitem__(
                    "creation_time", "2026-99-99T12:30:45.123Z"
                ),
            ),
            (
                "log injection",
                lambda value: value.__setitem__("sensor_name", "camera\nforged"),
            ),
        )
        for name, mutate in invalid_mutations:
            candidate = dict(valid)
            mutate(candidate)
            with self.subTest(name=name), self.assertRaises(ValueError):
                LvsMCPServer._validate_file_info(
                    candidate,
                    expected_id=self.FILE_ID,
                    require_media_type=True,
                )

        with self.assertRaisesRegex(ValueError, "unexpected file size"):
            LvsMCPServer._validate_file_info(
                valid,
                expected_bytes=6,
                require_media_type=True,
            )
        with self.assertRaisesRegex(ValueError, "unexpected filename"):
            LvsMCPServer._validate_file_info(
                valid,
                expected_filename="other.mp4",
                require_media_type=True,
            )

        with_extra_backend_field = {**valid, "backend_internal": "must-not-escape"}
        self.assertEqual(
            LvsMCPServer._validate_file_info(
                with_extra_backend_field,
                require_media_type=True,
            ),
            valid,
        )

    def test_bounded_media_reader_rejects_growth_past_limit(self):
        exact = _BoundedMediaReader(io.BytesIO(b"12"), 2)
        self.assertEqual(exact.read(1), b"1")
        self.assertEqual(exact.read(), b"2")
        self.assertEqual(exact.read(), b"")

        growing = _BoundedMediaReader(io.BytesIO(b"123"), 2)
        self.assertEqual(growing.read(2), b"12")
        with self.assertRaisesRegex(ValueError, "grew beyond"):
            growing.read()

    def test_add_file_rejects_identity_change_between_resolution_and_open(self):
        mcp = LvsMCPServer(FakeLvsServer())
        mcp._call_http_api = mock.AsyncMock()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "clip.mp4"
            path.write_bytes(b"x")
            actual = path.stat()
            changed = types.SimpleNamespace(
                st_mode=actual.st_mode,
                st_dev=actual.st_dev,
                st_ino=actual.st_ino + 1,
                st_size=actual.st_size,
            )
            with (
                mock.patch.dict(os.environ, {"LVS_MCP_MEDIA_ROOT": str(root)}),
                mock.patch("lvs_mcp.os.fstat", return_value=changed),
                self.assertRaisesRegex(ValueError, "path changed while opening"),
            ):
                asyncio.run(mcp._handle_tool_call("add_file", {"path": path.name}))
        mcp._call_http_api.assert_not_awaited()

    def test_fstat_failure_closes_the_final_media_descriptor(self):
        real_open = os.open
        real_close = os.close
        opened_descriptors = []
        closed_descriptors = []

        def tracking_open(*args, **kwargs):
            descriptor = real_open(*args, **kwargs)
            opened_descriptors.append(descriptor)
            return descriptor

        def tracking_close(descriptor):
            closed_descriptors.append(descriptor)
            return real_close(descriptor)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "clip.mp4").write_bytes(b"x")
            with (
                mock.patch.dict(os.environ, {"LVS_MCP_MEDIA_ROOT": str(root)}),
                mock.patch("lvs_mcp.os.open", side_effect=tracking_open),
                mock.patch("lvs_mcp.os.close", side_effect=tracking_close),
                mock.patch(
                    "lvs_mcp.os.fstat", side_effect=OSError("synthetic fstat failure")
                ),
                self.assertRaisesRegex(OSError, "synthetic fstat failure"),
            ):
                LvsMCPServer._open_media_file("clip.mp4")

        self.assertEqual(len(opened_descriptors), 2)
        self.assertCountEqual(closed_descriptors, opened_descriptors)

    def test_add_file_failure_rolls_back_without_masking_the_original_error(self):
        malformed_response = {
            "id": self.FILE_ID,
            "bytes": 1,
            "filename": "wrong.mp4",
            "purpose": "vision",
            "media_type": "video",
        }
        scenarios = (
            (
                "upload failure",
                RuntimeError("upload failed"),
                None,
                RuntimeError,
                "upload failed",
            ),
            (
                "validation failure",
                malformed_response,
                None,
                ValueError,
                "LVS returned an unexpected filename",
            ),
            (
                "cleanup failure",
                malformed_response,
                RuntimeError("cleanup failed"),
                ValueError,
                "LVS returned an unexpected filename",
            ),
        )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "clip.mp4").write_bytes(b"x")
            for (
                name,
                post_outcome,
                cleanup_error,
                expected_type,
                expected_error,
            ) in scenarios:
                calls = []

                async def call_api(method, path, **kwargs):
                    calls.append((method, path))
                    if method == "POST":
                        if isinstance(post_outcome, Exception):
                            raise post_outcome
                        return post_outcome
                    if cleanup_error is not None:
                        raise cleanup_error
                    return {"id": self.FILE_ID, "object": "file", "deleted": True}

                mcp = LvsMCPServer(FakeLvsServer())
                mcp._call_http_api = mock.AsyncMock(side_effect=call_api)
                with (
                    self.subTest(name=name),
                    mock.patch.dict(os.environ, {"LVS_MCP_MEDIA_ROOT": str(root)}),
                    mock.patch("lvs_mcp.uuid4", return_value=UUID(self.FILE_ID)),
                    mock.patch("lvs_mcp.logger.warning") as warning,
                    self.assertRaisesRegex(expected_type, expected_error) as raised,
                ):
                    asyncio.run(mcp._handle_tool_call("add_file", {"path": "clip.mp4"}))

                self.assertEqual(str(raised.exception), expected_error)
                post_path = calls[0][1]
                self.assertEqual(
                    calls,
                    [("POST", post_path), ("DELETE", f"{post_path}/{self.FILE_ID}")],
                )
                self.assertEqual(warning.called, cleanup_error is not None)

    def test_original_tool_errors_retain_type_while_file_errors_are_sanitized(self):
        mcp = LvsMCPServer(FakeLvsServer())
        original_tools = {
            "health_ready",
            "health_live",
            "list_models",
            "summarize_video",
            "generate_vlm_captions",
            "generate_captions",
            "stream_summarize",
            "get_recommended_config",
            "get_metrics",
        }
        file_tools = {"add_file", "list_files", "get_file_info", "delete_file"}
        secret = "/sensitive/operator/path.mp4"
        mcp._handle_tool_call = mock.AsyncMock(side_effect=ValueError(secret))

        with mock.patch("lvs_mcp.logger.error"):
            for name in original_tools:
                with self.subTest(name=name):
                    content = asyncio.run(mcp._invoke_call_tool(name, {}))
                    self.assertEqual(
                        json.loads(content[0].text),
                        {"error": secret, "type": "ValueError"},
                    )
            for name in file_tools:
                with self.subTest(name=name):
                    content = asyncio.run(mcp._invoke_call_tool(name, {}))
                    payload = json.loads(content[0].text)
                    self.assertEqual(
                        payload,
                        {"error": f"{name} failed; see the LVS service log for details"},
                    )
                    self.assertNotIn(secret, content[0].text)
                    self.assertNotIn("ValueError", content[0].text)

        self.assertEqual(
            mcp._handle_tool_call.await_count,
            len(original_tools) + len(file_tools),
        )

    def test_sse_bind_and_port_configuration_fail_closed(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(_mcp_bind_host(), "127.0.0.1")
        for host in ("127.0.0.2", "::1"):
            with (
                self.subTest(host=host),
                mock.patch.dict(os.environ, {"LVS_MCP_HOST": host}),
            ):
                self.assertEqual(_mcp_bind_host(), host)
        for host in ("0.0.0.0", "localhost", "192.168.1.10", "example.com"):
            with (
                self.subTest(host=host),
                mock.patch.dict(os.environ, {"LVS_MCP_HOST": host}),
                self.assertRaisesRegex(ValueError, "loopback"),
            ):
                _mcp_bind_host()
        for invalid in ("-1", "0", "65536", "not-a-port"):
            with (
                self.subTest(port=invalid),
                mock.patch.dict(os.environ, {"LVS_MCP_PORT": invalid}),
            ):
                with self.assertRaisesRegex(ValueError, "1 through 65535"):
                    asyncio.run(run_mcp_server(FakeLvsServer()))

    def test_sse_server_passes_the_loopback_host_to_uvicorn(self):
        mcp = LvsMCPServer(FakeLvsServer())
        fake_server = mock.Mock()
        fake_server.serve = mock.AsyncMock()
        with (
            mock.patch.dict(os.environ, {"LVS_MCP_HOST": "127.0.0.1"}),
            mock.patch("uvicorn.Config") as config,
            mock.patch("uvicorn.Server", return_value=fake_server),
        ):
            asyncio.run(mcp.run(port=38112))
        self.assertEqual(config.call_args.kwargs["host"], "127.0.0.1")
        self.assertEqual(config.call_args.kwargs["port"], 38112)
        fake_server.serve.assert_awaited_once_with()


class TestRtviFileManagementProxy(unittest.TestCase):
    FILE_ID = TestLvsMcpFileManagement.FILE_ID

    @staticmethod
    def _client(response):
        client = object.__new__(RtviVlmClient)
        client._base_url = "http://rtvi.invalid"
        client._session = mock.Mock()
        client._session.get.return_value = response
        client._session.post.return_value = response
        return client

    def test_get_file_info_is_sticky_and_bounded(self):
        payload = {
            "id": self.FILE_ID,
            "bytes": 5,
            "filename": "clip.mp4",
            "purpose": "vision",
        }
        response = mock.Mock(status_code=200)
        response.json.return_value = payload
        client = self._client(response)

        self.assertEqual(client.get_file_info(self.FILE_ID), payload)
        client._session.get.assert_called_once_with(
            f"http://rtvi.invalid/v1/files/{self.FILE_ID}",
            timeout=RTVI_HEALTH_TIMEOUT,
            headers={"x-stream-id": self.FILE_ID},
        )

    def test_get_file_info_preserves_rtvi_error_status(self):
        response = mock.Mock(
            status_code=404,
            text='{"code":"NotFound","message":"asset missing"}',
        )
        client = self._client(response)
        with self.assertRaises(RtviError) as raised:
            client.get_file_info(self.FILE_ID)
        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(raised.exception.code, "NotFound")
        self.assertEqual(raised.exception.message, "asset missing")

    def test_upload_preserves_filename_and_sticky_identity(self):
        payload = {
            "id": self.FILE_ID,
            "bytes": 5,
            "filename": "clip.mp4",
            "purpose": "vision",
            "media_type": "video",
        }
        response = mock.Mock(status_code=200)
        response.json.return_value = payload
        client = self._client(response)
        stream = io.BytesIO(b"video")

        self.assertEqual(
            client.upload_file(
                stream,
                file_id=self.FILE_ID,
                upload_filename="clip.mp4",
            ),
            payload,
        )
        client._session.post.assert_called_once_with(
            "http://rtvi.invalid/v1/files",
            files={"file": ("clip.mp4", stream)},
            data={"purpose": "vision", "media_type": "video", "id": self.FILE_ID},
            timeout=300,
            headers={"x-stream-id": self.FILE_ID},
        )
