# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Offline tests for bounded on-demand terminal state and cancel races."""

from __future__ import annotations

import os
import importlib.util
import sys
import threading

import pytest


_store_path = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "alert-agent-web",
        "app",
        "service",
        "terminal_job_store.py",
    )
)
_store_spec = importlib.util.spec_from_file_location(
    "_terminal_job_store_isolated", _store_path
)
_store_module = importlib.util.module_from_spec(_store_spec)
sys.modules[_store_spec.name] = _store_module
_store_spec.loader.exec_module(_store_module)
JobCapacityError = _store_module.JobCapacityError
JobIdGenerationError = _store_module.JobIdGenerationError
TerminalJobStore = _store_module.TerminalJobStore


class FakeClock:
    def __init__(self) -> None:
        self.value = 1_800_000_000.0

    def __call__(self) -> float:
        return self.value


def fixed_store(*ids, capacity=1000, ttl_seconds=3600, clock=None):
    id_values = iter(ids)
    generations = iter(f"generation-token-{index:04d}" for index in range(100))
    kwargs = {
        "capacity": capacity,
        "ttl_seconds": ttl_seconds,
        "id_factory": lambda: next(id_values),
        "generation_factory": lambda: next(generations),
    }
    if clock is not None:
        kwargs["clock"] = clock
    return TerminalJobStore(**kwargs)


def test_register_and_terminal_receipt_are_sanitized():
    store = fixed_store("job-1", capacity=2, ttl_seconds=60)
    handle = store.register()
    created = store.get(handle.correlation_id)
    assert created["state"] == "queued"
    assert created["terminal"] is False

    assert store.mark_running(handle) is True
    assert store.begin_publish(handle) is True
    assert store.complete(
        handle,
        {
            "processingOutcome": "verified",
            "verdict": "confirmed",
            "verificationResponseCode": 200,
            "sinkDelivery": {
                "transport": "elastic",
                "outcome": "acknowledged",
                "documentId": "doc-1",
                "secret": "must-not-leak",
            },
            "rawVlmOutput": "must-not-leak",
        },
    ) is True

    status = store.get("job-1")
    assert status is not None
    assert status["state"] == "completed"
    assert status["terminal"] is True
    assert status["result"] == {
        "processingOutcome": "verified",
        "sinkDelivery": {
            "transport": "elastic",
            "outcome": "acknowledged",
            "documentId": "doc-1",
        },
        "verdict": "confirmed",
        "verificationResponseCode": 200,
    }


def test_accepted_cancellation_prevents_publish_transition():
    store = fixed_store("job-cancel")
    handle = store.register()
    assert store.mark_running(handle) is True

    cancelled = store.cancel("job-cancel")
    assert cancelled is not None
    assert cancelled["cancellationAccepted"] is True
    assert cancelled["state"] == "cancelled"
    assert store.begin_publish(handle) is False
    assert store.complete(handle, {}) is False


def test_cancel_after_publish_started_is_rejected():
    store = fixed_store("job-publishing")
    handle = store.register()
    store.mark_running(handle)
    assert store.begin_publish(handle) is True

    cancellation = store.cancel("job-publishing")
    assert cancellation is not None
    assert cancellation["cancellationAccepted"] is False
    assert cancellation["state"] == "publishing"


def test_cancel_publish_race_has_one_atomic_winner():
    for index in range(50):
        correlation_id = f"race-{index}"
        store = fixed_store(correlation_id)
        handle = store.register()
        store.mark_running(handle)
        barrier = threading.Barrier(3)
        results = {}

        def publish() -> None:
            barrier.wait()
            results["publish"] = store.begin_publish(handle)

        def cancel() -> None:
            barrier.wait()
            results["cancel"] = store.cancel(correlation_id)

        publish_thread = threading.Thread(target=publish)
        cancel_thread = threading.Thread(target=cancel)
        publish_thread.start()
        cancel_thread.start()
        barrier.wait()
        publish_thread.join()
        cancel_thread.join()

        cancellation_accepted = results["cancel"]["cancellationAccepted"]
        assert (results["publish"], cancellation_accepted) in {
            (True, False),
            (False, True),
        }


def test_capacity_never_evicts_active_cancellation_gate():
    store = fixed_store("active", "rejected", capacity=1)
    store.register()
    with pytest.raises(JobCapacityError):
        store.register()
    assert store.get("active")["state"] == "queued"


def test_capacity_reuses_oldest_terminal_slot():
    store = fixed_store("done", "replacement", capacity=1)
    handle = store.register()
    store.mark_running(handle)
    store.begin_publish(handle)
    store.complete(handle, {})

    replacement = store.register()
    assert store.get("done") is None
    assert store.get(replacement.correlation_id)["state"] == "queued"


def test_terminal_ttl_and_server_id_collision_are_bounded():
    clock = FakeClock()
    store = TerminalJobStore(
        capacity=2,
        ttl_seconds=10,
        clock=clock,
        id_factory=lambda: "expiring",
        generation_factory=lambda: "generation-token-0001",
    )
    store.register()
    with pytest.raises(JobIdGenerationError):
        store.register()

    store.cancel("expiring")
    clock.value += 9
    assert store.get("expiring") is not None
    clock.value += 1
    assert store.get("expiring") is None


@pytest.mark.parametrize(
    "correlation_id",
    ["", "contains space", "/path", "x" * 257, "line\nbreak"],
)
def test_invalid_server_generated_ids_fail_closed(correlation_id):
    store = TerminalJobStore(id_factory=lambda: correlation_id)
    with pytest.raises(JobIdGenerationError):
        store.register()


def test_failure_stores_only_bounded_error_code():
    store = fixed_store("failed")
    handle = store.register()
    store.mark_running(handle)
    assert store.fail(handle, "unsafe details: https://secret") is True
    assert store.get("failed")["error"] == {"code": "processing_failed"}


def test_aba_old_worker_cannot_mutate_reused_public_id():
    clock = FakeClock()
    generations = iter(("generation-token-old1", "generation-token-new2"))
    store = TerminalJobStore(
        capacity=1,
        ttl_seconds=1,
        clock=clock,
        id_factory=lambda: "job-reused",
        generation_factory=lambda: next(generations),
    )
    old_handle = store.register()
    assert store.mark_running(old_handle) is True
    assert store.cancel("job-reused")["cancellationAccepted"] is True
    clock.value += 1
    assert store.get("job-reused") is None

    new_handle = store.register()
    assert new_handle.correlation_id == old_handle.correlation_id
    assert new_handle.generation != old_handle.generation

    assert store.mark_running(old_handle) is False
    assert store.begin_publish(old_handle) is False
    assert store.complete(old_handle, {}) is False
    assert store.fail(old_handle, "old_worker") is False
    assert store.get("job-reused")["state"] == "queued"

    assert store.mark_running(new_handle) is True
    assert store.begin_publish(new_handle) is True


def test_server_generated_keys_are_distinct_from_event_ids_and_each_other():
    store = TerminalJobStore()
    first = store.register()
    second = store.register()
    assert first.correlation_id.startswith("job-")
    assert second.correlation_id.startswith("job-")
    assert first.correlation_id != "caller-event-id"
    assert first.correlation_id != second.correlation_id


def test_allocator_failure_does_not_evict_retained_terminal_receipt():
    ids = iter(("retained", "invalid id"))
    generations = iter(("generation-token-0001", "generation-token-0002"))
    store = TerminalJobStore(
        capacity=1,
        id_factory=lambda: next(ids),
        generation_factory=lambda: next(generations),
    )
    handle = store.register()
    store.mark_running(handle)
    store.begin_publish(handle)
    store.complete(handle, {})

    with pytest.raises(JobIdGenerationError):
        store.register()
    assert store.get("retained")["state"] == "completed"
