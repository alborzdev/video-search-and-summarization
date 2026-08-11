# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from typing import Any

import pytest


PACKAGE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "search_semantic_current_runtime_executor", PACKAGE / "executor.py"
)
assert SPEC is not None and SPEC.loader is not None
executor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = executor
SPEC.loader.exec_module(executor)


def test_default_plan_is_inert_and_source_locked() -> None:
    contract = executor._contract()
    result = executor._plan(contract)
    assert result == {
        "schema_version": 1,
        "package_id": "thor-search-semantic-current-runtime-successor-v1",
        "mode": "plan",
        "status": "ready_inert",
        "network_requests": 0,
        "persistent_mutations": 0,
        "authorization_required": True,
        "source_lock_count": 8,
        "warehouse_sample_bundle": "excluded",
    }


def test_wrong_ack_fails_before_runtime_or_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    contract = executor._contract()

    def forbidden(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("runtime admission must not occur")

    monkeypatch.setattr(executor, "_validate_source_locks", forbidden)
    monkeypatch.setattr(executor, "_runtime_snapshot", forbidden)
    with pytest.raises(executor.QualificationError) as caught:
        executor._execute(contract, "testrun", "wrong")
    assert caught.value.code == "authorization_required"


def test_frame_envelope_normalization_is_exact() -> None:
    assert executor._frame_rows({"frames": [{"objects": []}]}) == [{"objects": []}]
    assert executor._frame_rows([{"objects": []}]) == [{"objects": []}]
    with pytest.raises(executor.QualificationError):
        executor._frame_rows({"unexpected": []})
    with pytest.raises(executor.QualificationError):
        executor._frame_rows({"frames": ["not-an-object"]})


def test_owned_index_delete_requires_uuid_and_exact_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    class FakeHttp:
        def call(self, **kwargs: Any) -> tuple[int, Any, bytes]:
            calls.append(kwargs)
            return 200, {"acknowledged": True}, b"{}"

    monkeypatch.setattr(executor, "_index_uuid", lambda *_args: "owned-uuid")
    monkeypatch.setattr(
        executor,
        "_index_document_ids",
        lambda *_args: {"doc-a", "doc-b"},
    )
    result = executor._cleanup_index(
        FakeHttp(),
        executor.OwnedIndex(
            name=executor.BEHAVIOR_INDEX,
            uuid="owned-uuid",
            document_ids={"doc-a", "doc-b"},
        ),
    )
    assert result == {
        "created": True,
        "deleted": True,
        "foreign_documents_observed": False,
    }
    assert len(calls) == 1
    assert calls[0]["method"] == "DELETE"
    assert calls[0]["mutation"] is True


def test_foreign_inventory_uses_exact_document_fallback_and_never_index_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    inventories = iter(({"doc-a", "foreign"}, {"foreign"}))

    class FakeHttp:
        def call(self, **kwargs: Any) -> tuple[int, Any, bytes]:
            calls.append(kwargs)
            return 200, {"errors": False}, b"{}"

    monkeypatch.setattr(executor, "_index_uuid", lambda *_args: "owned-uuid")
    monkeypatch.setattr(executor, "_index_document_ids", lambda *_args: next(inventories))
    result = executor._cleanup_index(
        FakeHttp(),
        executor.OwnedIndex(
            name=executor.RAW_INDEX,
            uuid="owned-uuid",
            document_ids={"doc-a"},
        ),
    )
    assert result == {
        "created": True,
        "deleted": False,
        "foreign_documents_observed": True,
    }
    assert [row["path"] for row in calls] == ["/_bulk?refresh=wait_for"]
    assert all(row["method"] != "DELETE" for row in calls)


def test_uuid_mismatch_refuses_all_cleanup_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeHttp:
        def call(self, **_kwargs: Any) -> tuple[int, Any, bytes]:
            raise AssertionError("cleanup mutation must not occur")

    monkeypatch.setattr(executor, "_index_uuid", lambda *_args: "foreign-uuid")
    with pytest.raises(executor.QualificationError) as caught:
        executor._cleanup_index(
            FakeHttp(),
            executor.OwnedIndex(
                name=executor.RAW_INDEX,
                uuid="owned-uuid",
                document_ids={"doc-a"},
            ),
        )
    assert caught.value.code == "cleanup_failed"


def test_vectors_are_finite_and_exact_dimension() -> None:
    value = {"data": [[0.25, -0.5]]}
    assert executor._vector(value, 2) == [0.25, -0.5]
    with pytest.raises(executor.QualificationError):
        executor._vector({"data": [[0.0, 0.0]]}, 2)
    with pytest.raises(executor.QualificationError):
        executor._vector({"data": [[float("nan"), 1.0]]}, 2)
