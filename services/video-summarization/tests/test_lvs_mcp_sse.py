# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Networkless lifecycle tests for the LVS wrapper around MCP's legacy SSE transport."""

import asyncio
import importlib.util
import sys
import types
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4


class _Writer:
    pass


class _FakePinnedSseServerTransport:
    """Behavioral seam matching the relevant local mcp==1.23.0 source."""

    def __init__(
        self,
        _endpoint,
        *,
        new_session_count=1,
        fail_entry=False,
        suppress_exit=False,
        exit_failure=None,
    ):
        self._read_stream_writers = {}
        self.new_session_count = new_session_count
        self.fail_entry = fail_entry
        self.suppress_exit = suppress_exit
        self.exit_failure = exit_failure
        self.parent_exit_errors = []
        self.created_sessions = []

    @asynccontextmanager
    async def connect_sse(self, _scope, _receive, _send):
        sessions = []
        for _ in range(self.new_session_count):
            session_id = uuid4()
            writer = _Writer()
            self._read_stream_writers[session_id] = writer
            self.created_sessions.append((session_id, writer))
            sessions.append((session_id, writer))
        if self.fail_entry:
            raise RuntimeError("parent entry failed after inserting its session")
        try:
            yield sessions
        except BaseException as error:
            self.parent_exit_errors.append(error)
            if self.exit_failure is not None:
                raise self.exit_failure
            if not self.suppress_exit:
                raise
        else:
            self.parent_exit_errors.append(None)
            if self.exit_failure is not None:
                raise self.exit_failure

    async def handle_post_message(self, scope, _receive, send):
        session_id = scope["session_id"]
        status = 202 if session_id in self._read_stream_writers else 404
        await send({"type": "http.response.start", "status": status, "headers": []})
        await send({"type": "http.response.body", "body": b""})


def _load_wrapper_module():
    """Load the production module against a local SDK seam without installing MCP."""

    module_path = Path(__file__).parents[1] / "src" / "lvs_mcp_sse.py"
    module_name = "_lvs_mcp_sse_lifecycle_test"
    mcp_module = types.ModuleType("mcp")
    server_module = types.ModuleType("mcp.server")
    sse_module = types.ModuleType("mcp.server.sse")
    sse_module.SseServerTransport = _FakePinnedSseServerTransport
    mcp_module.server = server_module
    server_module.sse = sse_module

    names = ("mcp", "mcp.server", "mcp.server.sse")
    prior = {name: sys.modules.get(name) for name in names}
    sys.modules.update(
        {"mcp": mcp_module, "mcp.server": server_module, "mcp.server.sse": sse_module}
    )
    try:
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("could not load lvs_mcp_sse.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for name, value in prior.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value


WRAPPER = _load_wrapper_module()
SessionCleaningSseServerTransport = WRAPPER.SessionCleaningSseServerTransport
SessionOwnershipError = WRAPPER.SessionOwnershipError


async def _receive():
    return {"type": "http.disconnect"}


async def _send(_message):
    return None


class TestSessionCleaningSseServerTransport(unittest.TestCase):
    def test_normal_exit_removes_only_the_owned_session(self):
        async def scenario():
            transport = SessionCleaningSseServerTransport("/messages")
            existing_id = uuid4()
            existing_writer = _Writer()
            transport._read_stream_writers[existing_id] = existing_writer

            async with transport.connect_sse({}, _receive, _send) as sessions:
                owned_id, owned_writer = sessions[0]
                self.assertIs(transport._read_stream_writers[owned_id], owned_writer)
                self.assertIs(
                    transport._read_stream_writers[existing_id], existing_writer
                )

            self.assertNotIn(owned_id, transport._read_stream_writers)
            self.assertIs(transport._read_stream_writers[existing_id], existing_writer)
            self.assertEqual(transport.parent_exit_errors, [None])

        asyncio.run(scenario())

    def test_replacement_writer_is_not_removed(self):
        async def scenario():
            transport = SessionCleaningSseServerTransport("/messages")
            replacement = _Writer()
            async with transport.connect_sse({}, _receive, _send) as sessions:
                owned_id, _owned_writer = sessions[0]
                transport._read_stream_writers[owned_id] = replacement

            self.assertIs(transport._read_stream_writers[owned_id], replacement)

        asyncio.run(scenario())

    def test_body_exception_is_passed_to_parent_exit_and_propagated(self):
        async def scenario():
            transport = SessionCleaningSseServerTransport("/messages")
            failure = ValueError("body failed")
            with self.assertRaisesRegex(ValueError, "body failed") as raised:
                async with transport.connect_sse({}, _receive, _send):
                    raise failure
            self.assertIs(raised.exception, failure)
            self.assertIs(transport.parent_exit_errors[0], failure)
            self.assertEqual(transport._read_stream_writers, {})

        asyncio.run(scenario())

    def test_parent_entry_failure_cleans_exact_additions(self):
        async def scenario():
            transport = SessionCleaningSseServerTransport(
                "/messages", fail_entry=True
            )
            existing_id = uuid4()
            existing_writer = _Writer()
            transport._read_stream_writers[existing_id] = existing_writer
            with self.assertRaisesRegex(RuntimeError, "parent entry failed"):
                async with transport.connect_sse({}, _receive, _send):
                    self.fail("parent entry failure must prevent body entry")
            self.assertEqual(
                transport._read_stream_writers, {existing_id: existing_writer}
            )

        asyncio.run(scenario())

    def test_parent_exit_suppression_is_preserved(self):
        async def scenario():
            transport = SessionCleaningSseServerTransport(
                "/messages", suppress_exit=True
            )
            failure = ValueError("parent should suppress this")
            async with transport.connect_sse({}, _receive, _send):
                raise failure
            self.assertIs(transport.parent_exit_errors[0], failure)
            self.assertEqual(transport._read_stream_writers, {})

        asyncio.run(scenario())

    def test_parent_exit_failure_propagates_after_cleanup(self):
        async def scenario():
            exit_failure = LookupError("parent exit failed")
            transport = SessionCleaningSseServerTransport(
                "/messages", exit_failure=exit_failure
            )
            with self.assertRaisesRegex(LookupError, "parent exit failed") as raised:
                async with transport.connect_sse({}, _receive, _send):
                    pass
            self.assertIs(raised.exception, exit_failure)
            self.assertEqual(transport._read_stream_writers, {})

        asyncio.run(scenario())

    def test_zero_or_multiple_new_sessions_fail_closed_and_cleanup(self):
        async def scenario(count):
            transport = SessionCleaningSseServerTransport(
                "/messages", new_session_count=count
            )
            with self.assertRaisesRegex(SessionOwnershipError, "exactly one"):
                async with transport.connect_sse({}, _receive, _send):
                    self.fail("ownership invariant failure must prevent body entry")
            self.assertEqual(transport._read_stream_writers, {})
            self.assertIsInstance(
                transport.parent_exit_errors[0], SessionOwnershipError
            )

        asyncio.run(scenario(0))
        asyncio.run(scenario(2))

    def test_concurrent_connections_keep_independent_live_sessions(self):
        async def scenario():
            transport = SessionCleaningSseServerTransport("/messages")
            first_ready = asyncio.Event()
            second_ready = asyncio.Event()
            release_first = asyncio.Event()
            release_second = asyncio.Event()
            observed = {}

            async def connection(name, ready, release):
                async with transport.connect_sse({}, _receive, _send) as sessions:
                    observed[name] = sessions[0][0]
                    ready.set()
                    await release.wait()

            first = asyncio.create_task(
                connection("first", first_ready, release_first)
            )
            second = asyncio.create_task(
                connection("second", second_ready, release_second)
            )
            await asyncio.wait_for(
                asyncio.gather(first_ready.wait(), second_ready.wait()), timeout=1
            )
            self.assertEqual(len(transport._read_stream_writers), 2)

            release_first.set()
            await asyncio.wait_for(first, timeout=1)
            self.assertNotIn(observed["first"], transport._read_stream_writers)
            self.assertIn(observed["second"], transport._read_stream_writers)

            release_second.set()
            await asyncio.wait_for(second, timeout=1)
            self.assertEqual(transport._read_stream_writers, {})

        asyncio.run(scenario())

    def test_cancellation_reaches_parent_and_cleans_session(self):
        async def scenario():
            transport = SessionCleaningSseServerTransport("/messages")
            ready = asyncio.Event()
            never = asyncio.Event()

            async def connection():
                async with transport.connect_sse({}, _receive, _send):
                    ready.set()
                    await never.wait()

            task = asyncio.create_task(connection())
            await asyncio.wait_for(ready.wait(), timeout=1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(transport._read_stream_writers, {})
            self.assertIsInstance(
                transport.parent_exit_errors[0], asyncio.CancelledError
            )

        asyncio.run(scenario())

    def test_stale_post_lookup_returns_404_after_context_exit(self):
        async def scenario():
            transport = SessionCleaningSseServerTransport("/messages")
            async with transport.connect_sse({}, _receive, _send) as sessions:
                session_id = sessions[0][0]

            messages = []

            async def capture(message):
                messages.append(message)

            await transport.handle_post_message(
                {"session_id": session_id}, _receive, capture
            )
            self.assertEqual(messages[0]["status"], 404)

        asyncio.run(scenario())


class TestSessionCleaningSseIntegration(unittest.TestCase):
    def test_lvs_uses_the_cleaning_transport(self):
        service_root = Path(__file__).parents[1]
        source = (service_root / "src" / "lvs_mcp.py").read_text()
        self.assertIn(
            "from lvs_mcp_sse import SessionCleaningSseServerTransport", source
        )
        self.assertIn(
            'sse = SessionCleaningSseServerTransport("/messages")', source
        )
        self.assertNotIn("from mcp.server.sse import SseServerTransport", source)

    def test_both_image_builds_package_the_wrapper(self):
        service_root = Path(__file__).parents[1]
        repository_root = service_root.parents[1]
        package_files = (
            service_root / "docker" / "package_file_list.txt"
        ).read_text().splitlines()
        self.assertEqual(package_files.count("lvs_mcp_sse.py"), 1)

        thor_dockerfile = (
            repository_root / "deploy/docker/thor-local/Dockerfile.video-summarization"
        ).read_text()
        self.assertEqual(
            thor_dockerfile.count(
                "COPY services/video-summarization/src/lvs_mcp_sse.py "
                "/opt/nvidia/via/via-engine/lvs_mcp_sse.py"
            ),
            1,
        )

    def test_thor_overlay_offline_installs_and_verifies_exact_mcp_wheel(self):
        service_root = Path(__file__).parents[1]
        repository_root = service_root.parents[1]
        thor_dockerfile = (
            repository_root / "deploy/docker/thor-local/Dockerfile.video-summarization"
        ).read_text()
        required = (
            "mcp-1.23.0-py3-none-any.whl",
            "231427",
            "5a645cf111ed329f4619f2629a3f15d9aabd7adc2ea09d600d31467b51ecb64f",
            "UV_OFFLINE=1",
            "--no-index",
            "--no-deps",
            "--reinstall",
            "pip check --system",
            'version("mcp") == "1.23.0"',
            "SseServerTransport",
            "_read_stream_writers",
            "CallToolResult",
            ".unlink()",
        )
        for literal in required:
            with self.subTest(literal=literal):
                self.assertIn(literal, thor_dockerfile)

        pyproject = (
            service_root / "docker" / "base" / "py_deps" / "pyproject.toml"
        ).read_text()
        self.assertNotIn('"mcp==1.23.0"', pyproject)


if __name__ == "__main__":
    unittest.main()
