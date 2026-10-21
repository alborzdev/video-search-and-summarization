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
"""Persistent, root-confined object storage for single-node deployments."""

import asyncio
from collections.abc import AsyncGenerator
import contextlib
import json
import mimetypes
import os
from pathlib import Path
from pathlib import PurePosixPath
import tempfile

from nat.builder.builder import Builder
from nat.cli.register_workflow import register_object_store
from nat.data_models.object_store import KeyAlreadyExistsError
from nat.data_models.object_store import NoSuchKeyError
from nat.data_models.object_store import ObjectStoreBaseConfig
from nat.object_store.interfaces import ObjectStore
from nat.object_store.models import ObjectStoreItem
from nat.utils.type_utils import override
from pydantic import Field


class FilesystemObjectStoreConfig(ObjectStoreBaseConfig, name="filesystem"):
    """Configuration for a durable object store rooted at one local directory."""

    root_path: Path = Field(description="Directory used to persist objects and their metadata.")


class FilesystemObjectStore(ObjectStore):
    """Store objects atomically on a local filesystem without allowing path escape."""

    _METADATA_SUFFIX = ".vss-object.json"

    def __init__(self, root_path: Path) -> None:
        self._root = root_path.expanduser().resolve()
        self._root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    def _object_path(self, key: str) -> Path:
        if not key or "\\" in key or "\x00" in key:
            raise ValueError("Object keys must be non-empty POSIX paths")

        relative = PurePosixPath(key)
        if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
            raise ValueError("Object key must remain within the configured store root")

        target = (self._root / Path(*relative.parts)).resolve(strict=False)
        try:
            target.relative_to(self._root)
        except ValueError as exc:
            raise ValueError("Object key must remain within the configured store root") from exc
        return target

    def _metadata_path(self, object_path: Path) -> Path:
        return object_path.with_name(f".{object_path.name}{self._METADATA_SUFFIX}")

    @staticmethod
    def _atomic_write(path: Path, data: bytes, mode: int) -> None:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        file_descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(file_descriptor, "wb") as temporary_file:
                temporary_file.write(data)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.chmod(temporary_name, mode)
            os.replace(temporary_name, path)
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary_name)

    def _write_object(self, path: Path, item: ObjectStoreItem) -> None:
        metadata = json.dumps(
            {"content_type": item.content_type, "metadata": item.metadata},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        self._atomic_write(path, item.data, 0o600)
        self._atomic_write(self._metadata_path(path), metadata, 0o600)

    @override
    async def put_object(self, key: str, item: ObjectStoreItem) -> None:
        path = self._object_path(key)
        async with self._lock:
            if await asyncio.to_thread(path.exists):
                raise KeyAlreadyExistsError(key)
            await asyncio.to_thread(self._write_object, path, item)

    @override
    async def upsert_object(self, key: str, item: ObjectStoreItem) -> None:
        path = self._object_path(key)
        async with self._lock:
            await asyncio.to_thread(self._write_object, path, item)

    @override
    async def get_object(self, key: str) -> ObjectStoreItem:
        path = self._object_path(key)
        async with self._lock:
            if not await asyncio.to_thread(path.is_file):
                raise NoSuchKeyError(key)
            data = await asyncio.to_thread(path.read_bytes)
            metadata_path = self._metadata_path(path)
            if await asyncio.to_thread(metadata_path.is_file):
                metadata_record = json.loads(await asyncio.to_thread(metadata_path.read_text, encoding="utf-8"))
                content_type = metadata_record.get("content_type")
                metadata = metadata_record.get("metadata")
            else:
                content_type = mimetypes.guess_type(path.name)[0]
                metadata = None
            return ObjectStoreItem(data=data, content_type=content_type, metadata=metadata)

    @override
    async def delete_object(self, key: str) -> None:
        path = self._object_path(key)
        async with self._lock:
            if not await asyncio.to_thread(path.is_file):
                raise NoSuchKeyError(key)
            await asyncio.to_thread(path.unlink)
            metadata_path = self._metadata_path(path)
            with contextlib.suppress(FileNotFoundError):
                await asyncio.to_thread(metadata_path.unlink)


@register_object_store(config_type=FilesystemObjectStoreConfig)
async def filesystem_object_store(
    config: FilesystemObjectStoreConfig,
    _builder: Builder,
) -> AsyncGenerator[FilesystemObjectStore]:
    """Register the filesystem object store with NeMo Agent Toolkit."""

    yield FilesystemObjectStore(config.root_path)
