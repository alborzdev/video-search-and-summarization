# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""LVS ownership cleanup for the pinned legacy MCP SSE transport.

``mcp==1.23.0`` records each SSE session in
``SseServerTransport._read_stream_writers`` but does not remove that entry when
the connection context ends.  The transport's POST handler treats membership
in that mapping as session validity, so retaining an entry also retains a stale
POST target.

This subclass deliberately relies on that pinned private contract.  It
serializes only session setup so the one mapping entry created by the parent
context can be attributed unambiguously.  Session operation remains fully
concurrent.  Cleanup removes the entry only while it still refers to the exact
writer captured by this connection, which prevents one connection from
removing another connection's replacement state.
"""

import asyncio
import sys
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from mcp.server.sse import SseServerTransport


class SessionOwnershipError(RuntimeError):
    """Raised when the pinned transport does not create exactly one session."""


class SessionCleaningSseServerTransport(SseServerTransport):
    """Pinned MCP SSE transport with connection-owned registry cleanup."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # LVS serves this transport through uvicorn's asyncio event loop.  The
        # lock is held only across the parent's context entry and ownership
        # discovery, never for the lifetime of an SSE connection.
        self._lvs_session_setup_lock = asyncio.Lock()

    @staticmethod
    def _remove_owned_session(
        writers: dict[Any, Any], session_id: Any, writer: Any
    ) -> None:
        """Remove only the mapping value captured by this connection."""

        if writers.get(session_id) is writer:
            del writers[session_id]

    @asynccontextmanager
    async def connect_sse(
        self, scope: Any, receive: Any, send: Any
    ) -> AsyncIterator[Any]:
        """Enter the parent transport and remove its exact session on exit."""

        parent_context = super().connect_sse(scope, receive, send)
        session_id: Any = None
        writer: Any = None

        async with self._lvs_session_setup_lock:
            writers = self._read_stream_writers
            before = frozenset(writers)
            try:
                streams = await parent_context.__aenter__()
            except BaseException:
                # The pinned parent inserts before yielding.  If a later part
                # of __aenter__ fails, remove only additions made while setup
                # was serialized.  Do not touch sessions present beforehand.
                additions = tuple(
                    (key, value)
                    for key, value in writers.items()
                    if key not in before
                )
                for added_id, added_writer in additions:
                    self._remove_owned_session(writers, added_id, added_writer)
                raise

            additions = tuple(
                (key, value) for key, value in writers.items() if key not in before
            )
            if len(additions) != 1:
                error = SessionOwnershipError(
                    "pinned MCP SSE transport did not create exactly one session"
                )
                try:
                    # The parent context was entered and must see the same
                    # fail-closed error that prevents this connection opening.
                    await parent_context.__aexit__(type(error), error, None)
                finally:
                    for added_id, added_writer in additions:
                        self._remove_owned_session(writers, added_id, added_writer)
                raise error

            session_id, writer = additions[0]

        try:
            try:
                yield streams
            except BaseException:
                error_type, error, traceback = sys.exc_info()
                if not await parent_context.__aexit__(error_type, error, traceback):
                    raise
            else:
                await parent_context.__aexit__(None, None, None)
        finally:
            # Synchronous, identity-checked cleanup cannot be interrupted by
            # task cancellation and cannot delete a replacement writer.
            self._remove_owned_session(writers, session_id, writer)
