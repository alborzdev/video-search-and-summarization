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

from unittest.mock import Mock, patch

import asyncio
import pytest
import threading
import time

from vlm.vlm_client import AsyncVLMRuntime


def test_concurrent_starters_share_startup_barrier():
    runtime = AsyncVLMRuntime({})
    entered = threading.Event()
    release = threading.Event()
    finished = []
    errors = []

    def delayed_start():
        entered.set()
        assert release.wait(timeout=2)
        with runtime._lock:
            runtime._loop = Mock()
            runtime._client = Mock()
        runtime._started_event.set()

    runtime._run_event_loop = delayed_start

    def start(label):
        try:
            runtime._ensure_started()
            finished.append(label)
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    first = threading.Thread(target=start, args=("first",))
    second = threading.Thread(target=start, args=("second",))
    first.start()
    assert entered.wait(timeout=2)
    second.start()
    time.sleep(0.05)

    # The second caller sees an alive startup thread, but it must not return
    # until that thread publishes the loop/client and sets the shared barrier.
    assert finished == []

    release.set()
    first.join(timeout=2)
    second.join(timeout=2)
    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []
    assert sorted(finished) == ["first", "second"]


def test_submit_coroutine_uses_stable_loop_reference():
    runtime = AsyncVLMRuntime({})
    runtime._ensure_started = Mock()
    runtime._stopping = False

    loop = Mock()
    thread = Mock()
    thread.is_alive.return_value = True
    runtime._loop = loop
    runtime._thread = thread

    coro = asyncio.sleep(0)
    marker = object()
    with patch(
        "vlm.vlm_client.asyncio.run_coroutine_threadsafe",
        return_value=marker,
    ) as submit_mock:
        result = runtime.submit_coroutine(coro)

    assert result is marker
    submit_mock.assert_called_once_with(coro, loop)
    coro.close()


def test_submit_coroutine_closes_coroutine_when_runtime_unavailable():
    runtime = AsyncVLMRuntime({})
    runtime._ensure_started = Mock()
    runtime._stopping = False
    runtime._loop = None
    runtime._thread = None

    closed = {"value": False}

    class DummyCoroutine:
        def close(self):
            closed["value"] = True

    with pytest.raises(RuntimeError):
        runtime.submit_coroutine(DummyCoroutine())

    assert closed["value"] is True


def test_submit_coroutine_closes_coroutine_on_submit_error():
    runtime = AsyncVLMRuntime({})
    runtime._ensure_started = Mock()
    runtime._stopping = False

    loop = Mock()
    thread = Mock()
    thread.is_alive.return_value = True
    runtime._loop = loop
    runtime._thread = thread

    closed = {"value": False}

    class DummyCoroutine:
        def close(self):
            closed["value"] = True

    with patch(
        "vlm.vlm_client.asyncio.run_coroutine_threadsafe",
        side_effect=RuntimeError("loop is closed"),
    ):
        with pytest.raises(RuntimeError):
            runtime.submit_coroutine(DummyCoroutine())

    assert closed["value"] is True
