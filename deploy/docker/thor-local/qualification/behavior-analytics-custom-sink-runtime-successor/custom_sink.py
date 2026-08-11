"""Minimal lossless JSONL implementation of the Behavior Analytics Sink interface."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from collections.abc import Callable, Mapping
from typing import Any, TextIO

from mdx.analytics.core.stream.sink.sink_base import Sink


def _wire_value(value: str | bytes | None) -> dict[str, str] | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return {"encoding": "base64", "value": base64.b64encode(value).decode("ascii")}
    if isinstance(value, str):
        return {"encoding": "utf-8", "value": value}
    raise TypeError(f"serializer returned unsupported type: {type(value).__name__}")


class JsonlFileSink(Sink):
    """Write serialized sink records to a configured JSONL file per destination key."""

    def __init__(self, destinations: Mapping[str, str | Path]) -> None:
        if not destinations:
            raise ValueError("at least one destination is required")
        self._destinations = {key: Path(path) for key, path in destinations.items()}
        self._writers: dict[str, TextIO] = {}
        self._closed = False

    def _writer(self, dest_key: str) -> TextIO:
        if self._closed:
            raise RuntimeError("sink is closed")
        path = self._destinations.get(dest_key)
        if path is None:
            raise ValueError(f"unknown destination key: {dest_key}")
        writer = self._writers.get(dest_key)
        if writer is None:
            path.parent.mkdir(parents=True, exist_ok=True)
            writer = path.open("a", encoding="utf-8")
            self._writers[dest_key] = writer
        return writer

    def _append(
        self,
        dest_key: str,
        message: str | bytes,
        key: str | bytes | None,
        headers: Mapping[str, str | bytes] | None,
    ) -> None:
        record = {
            "dest_key": dest_key,
            "key": _wire_value(key),
            "value": _wire_value(message),
            "headers": {
                name: _wire_value(value)
                for name, value in sorted((headers or {}).items())
            },
        }
        writer = self._writer(dest_key)
        writer.write(json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n")
        writer.flush()

    def write(
        self,
        dest_key: str,
        messages: list[Any],
        value_serializer: Callable,
        key_extractor: Callable | None = None,
        key_serializer: Callable | None = None,
        headers: Mapping[str, str | bytes] | None = None,
    ) -> None:
        for message in messages:
            key = key_extractor(message) if key_extractor else None
            if key is not None and key_serializer:
                key = key_serializer(key)
            self._append(dest_key, value_serializer(message), key, headers)

    def write_msg(
        self,
        dest_key: str,
        message: bytes,
        key: bytes | None,
        headers: Mapping[str, str | bytes] | None = None,
    ) -> None:
        self._append(dest_key, message, key, headers)

    def close(self) -> None:
        if self._closed:
            return
        for writer in self._writers.values():
            writer.flush()
            writer.close()
        self._writers.clear()
        self._closed = True
