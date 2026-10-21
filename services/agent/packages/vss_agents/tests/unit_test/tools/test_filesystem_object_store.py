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
"""Tests for the persistent filesystem object store."""

from pathlib import Path

from nat.data_models.object_store import KeyAlreadyExistsError
from nat.data_models.object_store import NoSuchKeyError
from nat.object_store.models import ObjectStoreItem
import pytest

from vss_agents.tools.filesystem_object_store import FilesystemObjectStore


@pytest.mark.asyncio
async def test_object_survives_store_recreation(tmp_path: Path) -> None:
    """Objects and metadata remain readable after constructing a new client."""

    first = FilesystemObjectStore(tmp_path)
    item = ObjectStoreItem(data=b"# Durable report", content_type="text/markdown", metadata={"kind": "report"})
    await first.put_object("reports/example.md", item)

    second = FilesystemObjectStore(tmp_path)
    restored = await second.get_object("reports/example.md")

    assert restored == item
    assert (tmp_path / "reports/example.md").stat().st_mode & 0o777 == 0o600


@pytest.mark.asyncio
async def test_put_rejects_existing_key_and_upsert_replaces_it(tmp_path: Path) -> None:
    """Put and upsert retain the standard object-store semantics."""

    store = FilesystemObjectStore(tmp_path)
    await store.put_object("report.pdf", ObjectStoreItem(data=b"old", content_type="application/pdf"))

    with pytest.raises(KeyAlreadyExistsError):
        await store.put_object("report.pdf", ObjectStoreItem(data=b"duplicate"))

    await store.upsert_object("report.pdf", ObjectStoreItem(data=b"new", content_type="application/pdf"))
    assert (await store.get_object("report.pdf")).data == b"new"


@pytest.mark.asyncio
async def test_delete_removes_data_and_metadata(tmp_path: Path) -> None:
    """Deleting an object removes its persistent representation."""

    store = FilesystemObjectStore(tmp_path)
    await store.put_object("nested/report.md", ObjectStoreItem(data=b"content", metadata={"sensor": "pit"}))

    await store.delete_object("nested/report.md")

    assert list((tmp_path / "nested").iterdir()) == []
    with pytest.raises(NoSuchKeyError):
        await store.get_object("nested/report.md")
    with pytest.raises(NoSuchKeyError):
        await store.delete_object("nested/report.md")


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["", "/absolute", "../escape", "nested/../../escape", r"windows\\escape"])
async def test_rejects_unsafe_keys(tmp_path: Path, key: str) -> None:
    """Object keys cannot escape the configured root directory."""

    store = FilesystemObjectStore(tmp_path)
    with pytest.raises(ValueError):
        await store.upsert_object(key, ObjectStoreItem(data=b"unsafe"))
