#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Fail-closed verification for Thor-local model snapshots and volume trees."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tarfile
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO


class VerificationError(RuntimeError):
    """An artifact differs from its reviewed lock."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise VerificationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _json_bytes(data: bytes, label: str) -> Any:
    try:
        return json.loads(data, object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerificationError(f"invalid JSON in {label}: {exc}") from exc


def load_lock(path: Path) -> dict[str, Any]:
    try:
        lock = _json_bytes(path.read_bytes(), str(path))
    except OSError as exc:
        raise VerificationError(f"cannot read artifact lock {path}: {exc}") from exc
    if not isinstance(lock, dict) or lock.get("schema_version") != 1:
        raise VerificationError("artifact lock schema_version must be exactly 1")
    artifacts = lock.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        raise VerificationError("artifact lock must contain a non-empty artifacts object")
    return lock


def _artifact(lock: Mapping[str, Any], name: str, kind: str) -> dict[str, Any]:
    artifacts = lock.get("artifacts")
    value = artifacts.get(name) if isinstance(artifacts, dict) else None
    if not isinstance(value, dict):
        raise VerificationError(f"artifact is absent from lock: {name}")
    if value.get("kind") != kind:
        raise VerificationError(f"artifact {name} is not kind {kind}")
    return value


def _safe_relative(value: str, *, allow_dot: bool = False) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise VerificationError(f"unsafe relative path: {value!r}")
    pure = PurePosixPath(value)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        if not (allow_dot and value == "."):
            raise VerificationError(f"unsafe relative path: {value!r}")
    normalized = pure.as_posix()
    if normalized != value:
        raise VerificationError(f"non-canonical relative path: {value!r}")
    return normalized


def _sha256_stream(stream: BinaryIO, first: bytes = b"") -> str:
    digest = hashlib.sha256(first)
    while True:
        chunk = stream.read(8 * 1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
    return digest.hexdigest()


def _safe_tensor_header(stream: BinaryIO, size: int, label: str) -> tuple[str, dict[str, Any]]:
    prefix = stream.read(8)
    if len(prefix) != 8:
        raise VerificationError(f"truncated SafeTensors prefix: {label}")
    header_size = int.from_bytes(prefix, "little")
    if header_size <= 1 or header_size > 128 * 1024 * 1024 or header_size + 8 > size:
        raise VerificationError(f"invalid SafeTensors header length: {label}")
    header_bytes = stream.read(header_size)
    if len(header_bytes) != header_size:
        raise VerificationError(f"truncated SafeTensors header: {label}")
    header = _json_bytes(header_bytes, label)
    if not isinstance(header, dict):
        raise VerificationError(f"SafeTensors header must be an object: {label}")
    payload_size = size - 8 - header_size
    tensors: dict[str, Any] = {}
    intervals: list[tuple[int, int, str]] = []
    for tensor, metadata in header.items():
        if tensor == "__metadata__":
            if not isinstance(metadata, dict):
                raise VerificationError(f"invalid SafeTensors metadata: {label}")
            continue
        if not isinstance(tensor, str) or not tensor or not isinstance(metadata, dict):
            raise VerificationError(f"invalid SafeTensors tensor entry: {label}")
        dtype = metadata.get("dtype")
        shape = metadata.get("shape")
        offsets = metadata.get("data_offsets")
        if not isinstance(dtype, str) or not dtype:
            raise VerificationError(f"invalid tensor dtype for {tensor}: {label}")
        if not isinstance(shape, list) or any(not isinstance(dim, int) or dim < 0 for dim in shape):
            raise VerificationError(f"invalid tensor shape for {tensor}: {label}")
        if (
            not isinstance(offsets, list)
            or len(offsets) != 2
            or any(not isinstance(item, int) for item in offsets)
            or not (0 <= offsets[0] <= offsets[1] <= payload_size)
        ):
            raise VerificationError(f"invalid tensor offsets for {tensor}: {label}")
        intervals.append((offsets[0], offsets[1], tensor))
        tensors[tensor] = metadata
    if not tensors:
        raise VerificationError(f"SafeTensors file contains no tensors: {label}")
    ordered_intervals = sorted(intervals)
    cursor = 0
    for start, end, tensor in ordered_intervals:
        if start != cursor:
            raise VerificationError(f"non-contiguous tensor data before {tensor}: {label}")
        cursor = end
    if cursor != payload_size:
        raise VerificationError(f"unclaimed SafeTensors payload bytes: {label}")
    for previous, current in zip(ordered_intervals, ordered_intervals[1:], strict=False):
        if current[0] < previous[1]:
            raise VerificationError(
                f"overlapping tensors {previous[2]} and {current[2]}: {label}"
            )
    return _sha256_stream(stream, prefix + header_bytes), tensors


def _hash_file(stream: BinaryIO, size: int, label: str) -> tuple[str, dict[str, Any] | None]:
    if label.endswith(".safetensors"):
        return _safe_tensor_header(stream, size, label)
    return _sha256_stream(stream), None


def _locked_tree(artifact: Mapping[str, Any]) -> tuple[dict[str, dict[str, Any]], set[str]]:
    tree = artifact.get("tree")
    if not isinstance(tree, dict):
        raise VerificationError("artifact tree must be an object")
    entries = tree.get("files")
    directories = tree.get("directories")
    if not isinstance(entries, list) or not isinstance(directories, list):
        raise VerificationError("artifact tree requires files and directories arrays")
    files: dict[str, dict[str, Any]] = {}
    for raw in entries:
        if not isinstance(raw, dict):
            raise VerificationError("locked file entry must be an object")
        name = _safe_relative(raw.get("path"))
        if name in files:
            raise VerificationError(f"duplicate locked file: {name}")
        kind = raw.get("type")
        if kind not in {"file", "symlink"}:
            raise VerificationError(f"unsupported locked file type for {name}: {kind}")
        size = raw.get("size")
        sha256 = raw.get("sha256")
        mode = raw.get("mode")
        if not isinstance(size, int) or size < 0:
            raise VerificationError(f"invalid locked size for {name}")
        if not isinstance(sha256, str) or re.fullmatch(r"[0-9a-f]{64}", sha256) is None:
            raise VerificationError(f"invalid locked sha256 for {name}")
        if not isinstance(mode, int) or not 0 <= mode <= 0o7777:
            raise VerificationError(f"invalid locked mode for {name}")
        if kind == "symlink":
            target = raw.get("target")
            if not isinstance(target, str) or not target:
                raise VerificationError(f"locked symlink lacks a target: {name}")
            blob = raw.get("blob")
            if not isinstance(blob, str) or re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", blob) is None:
                raise VerificationError(f"locked symlink lacks a valid blob identity: {name}")
        files[name] = raw
    dirs: set[str] = set()
    for raw in directories:
        name = _safe_relative(raw)
        if name in dirs:
            raise VerificationError(f"duplicate locked directory: {name}")
        dirs.add(name)
    overlap = set(files) & dirs
    if overlap:
        raise VerificationError(f"paths locked as both file and directory: {sorted(overlap)}")
    return files, dirs


def _walk_nodes(root: Path) -> tuple[dict[str, os.DirEntry[str]], set[str]]:
    files: dict[str, os.DirEntry[str]] = {}
    directories: set[str] = set()

    def walk(directory: Path, relative: PurePosixPath | None = None) -> None:
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name)
        except OSError as exc:
            raise VerificationError(f"cannot enumerate {directory}: {exc}") from exc
        for entry in entries:
            path = PurePosixPath(entry.name) if relative is None else relative / entry.name
            name = _safe_relative(path.as_posix())
            if entry.is_dir(follow_symlinks=False):
                directories.add(name)
                walk(Path(entry.path), path)
            elif entry.is_file(follow_symlinks=False) or entry.is_symlink():
                files[name] = entry
            else:
                raise VerificationError(f"unsupported filesystem node: {name}")

    walk(root)
    return files, directories


def _read_symlink_blob(
    entry: os.DirEntry[str],
    locked: Mapping[str, Any],
    repository_root: Path,
) -> tuple[bytes | None, dict[str, Any] | None]:
    name = locked["path"]
    try:
        target = os.readlink(entry.path)
    except OSError as exc:
        raise VerificationError(f"cannot read symlink {name}: {exc}") from exc
    if target != locked["target"]:
        raise VerificationError(f"symlink target differs for {name}")
    if target != f"../../blobs/{locked['blob']}":
        raise VerificationError(f"symlink target is not canonical Hugging Face layout: {name}")
    target_pure = PurePosixPath(target)
    if target_pure.is_absolute() or "\\" in target or "\x00" in target:
        raise VerificationError(f"unsafe symlink target for {name}")
    lexical_target = Path(entry.path).parent.joinpath(*target_pure.parts)
    try:
        resolved = lexical_target.resolve(strict=True)
        resolved_repo = repository_root.resolve(strict=True)
    except OSError as exc:
        raise VerificationError(f"broken symlink target for {name}: {exc}") from exc
    expected_blob_root = resolved_repo / "blobs"
    if resolved.parent != expected_blob_root or resolved.name != locked["blob"]:
        raise VerificationError(f"symlink escapes the repository blob store: {name}")
    try:
        target_stat = os.lstat(resolved)
    except OSError as exc:
        raise VerificationError(f"cannot inspect blob for {name}: {exc}") from exc
    if not stat.S_ISREG(target_stat.st_mode):
        raise VerificationError(f"symlink does not resolve to a regular blob: {name}")
    if stat.S_IMODE(target_stat.st_mode) != locked["mode"]:
        raise VerificationError(f"blob mode differs for {name}")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(resolved, flags)
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            before = os.fstat(stream.fileno())
            if name.endswith(".json") and before.st_size <= 64 * 1024 * 1024:
                capture = stream.read()
                if len(capture) != before.st_size:
                    raise VerificationError(f"truncated blob while reading {name}")
                digest = hashlib.sha256(capture).hexdigest()
                tensor_header = None
            else:
                capture = None
                digest, tensor_header = _hash_file(stream, before.st_size, name)
            after = os.fstat(stream.fileno())
    except OSError as exc:
        raise VerificationError(f"cannot hash blob for {name}: {exc}") from exc
    identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if identity_before != identity_after:
        raise VerificationError(f"blob changed while it was verified: {name}")
    if before.st_size != locked["size"] or digest != locked["sha256"]:
        raise VerificationError(f"blob size or sha256 differs for {name}")
    return capture, tensor_header


def verify_hf_snapshot(
    lock: Mapping[str, Any],
    artifact_name: str,
    snapshot: Path,
    repository_root: Path,
    repository: str,
    revision: str,
) -> None:
    artifact = _artifact(lock, artifact_name, "huggingface_snapshot")
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) is None:
        raise VerificationError("Hugging Face repository identity is unsafe")
    if re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        raise VerificationError("Hugging Face revision must be an immutable 40-hex commit")
    provenance = artifact.get("provenance")
    if not isinstance(provenance, dict):
        raise VerificationError(f"artifact {artifact_name} lacks provenance")
    expected = {
        "repository": repository,
        "revision": revision,
        "source_url": f"https://huggingface.co/{repository}",
        "cache_layout": "huggingface_hub_v1",
    }
    for key, value in expected.items():
        if provenance.get(key) != value:
            raise VerificationError(f"{artifact_name} provenance differs for {key}")
    if snapshot.name != revision:
        raise VerificationError(f"snapshot directory does not match revision {revision}")
    expected_repo_name = f"models--{repository.replace('/', '--')}"
    if repository_root.name != expected_repo_name or snapshot.parent.name != "snapshots":
        raise VerificationError("snapshot is outside the expected Hugging Face repository layout")
    for directory in (
        repository_root,
        repository_root / "blobs",
        repository_root / "snapshots",
        snapshot,
    ):
        try:
            directory_stat = os.lstat(directory)
        except OSError as exc:
            raise VerificationError(f"snapshot layout is unavailable at {directory}: {exc}") from exc
        if not stat.S_ISDIR(directory_stat.st_mode):
            raise VerificationError(f"snapshot layout path is not a real directory: {directory}")
    try:
        snapshot_resolved = snapshot.resolve(strict=True)
        repository_resolved = repository_root.resolve(strict=True)
    except OSError as exc:
        raise VerificationError(f"snapshot path is unavailable: {exc}") from exc
    if snapshot_resolved.parent != repository_resolved / "snapshots":
        raise VerificationError("snapshot does not belong to the expected repository root")

    locked_files, locked_dirs = _locked_tree(artifact)
    actual_files, actual_dirs = _walk_nodes(snapshot)
    if set(actual_files) != set(locked_files):
        missing = sorted(set(locked_files) - set(actual_files))
        extra = sorted(set(actual_files) - set(locked_files))
        raise VerificationError(f"snapshot file membership differs; missing={missing}, extra={extra}")
    if actual_dirs != locked_dirs:
        raise VerificationError(
            "snapshot directory membership differs; "
            f"missing={sorted(locked_dirs - actual_dirs)}, extra={sorted(actual_dirs - locked_dirs)}"
        )

    captured: dict[str, bytes] = {}
    tensor_headers: dict[str, dict[str, Any]] = {}
    for name in sorted(locked_files):
        locked = locked_files[name]
        entry = actual_files[name]
        if locked["type"] != "symlink" or not entry.is_symlink():
            raise VerificationError(f"snapshot member is not the locked symlink: {name}")
        data, header = _read_symlink_blob(entry, locked, repository_root)
        if data is not None:
            captured[name] = data
        if header is not None:
            tensor_headers[name] = header
    _verify_model_semantics(artifact, captured, tensor_headers)


def _json_path(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise VerificationError(f"required config path is absent: {path}")
        current = current[part]
    return current


def _verify_model_semantics(
    artifact: Mapping[str, Any],
    captured: Mapping[str, bytes],
    tensor_headers: Mapping[str, Mapping[str, Any]],
) -> None:
    semantics = artifact.get("semantics")
    if not isinstance(semantics, dict) or semantics.get("type") != "indexed_safetensors_model":
        raise VerificationError("model artifact lacks indexed SafeTensors semantics")
    config_path = semantics.get("config_path")
    index_path = semantics.get("index_path")
    if config_path not in captured or index_path not in captured:
        raise VerificationError("model config or SafeTensors index was not captured")
    config = _json_bytes(captured[config_path], config_path)
    index = _json_bytes(captured[index_path], index_path)
    if not isinstance(config, dict) or not isinstance(index, dict):
        raise VerificationError("model config and index must be JSON objects")
    expected_config = semantics.get("expected_config")
    if not isinstance(expected_config, dict) or not expected_config:
        raise VerificationError("model semantic lock lacks expected_config")
    for path, expected in expected_config.items():
        if _json_path(config, path) != expected:
            raise VerificationError(f"model config semantic differs at {path}")
    if set(index) != {"metadata", "weight_map"}:
        raise VerificationError("SafeTensors index keys must be exactly metadata and weight_map")
    metadata = index["metadata"]
    weight_map = index["weight_map"]
    if not isinstance(metadata, dict) or not isinstance(weight_map, dict) or not weight_map:
        raise VerificationError("SafeTensors index metadata/weight_map is invalid")
    expected_total = semantics.get("metadata_total_size")
    if expected_total is None:
        if metadata:
            raise VerificationError("SafeTensors index metadata unexpectedly differs")
    elif metadata != {"total_size": expected_total}:
        raise VerificationError("SafeTensors index total_size differs")
    expected_weight_count = semantics.get("weight_count")
    if len(weight_map) != expected_weight_count:
        raise VerificationError("SafeTensors index weight count differs")

    indexed_shards: set[str] = set()
    for tensor, shard in weight_map.items():
        if not isinstance(tensor, str) or not tensor:
            raise VerificationError("SafeTensors index has an invalid tensor name")
        if not isinstance(shard, str) or PurePosixPath(shard).name != shard:
            raise VerificationError(f"SafeTensors index has an unsafe shard name: {shard!r}")
        indexed_shards.add(shard)
    if len(indexed_shards) != semantics.get("shard_count"):
        raise VerificationError("SafeTensors index shard count differs")
    if indexed_shards != set(tensor_headers):
        raise VerificationError("SafeTensors index and staged shard membership differ")

    header_tensor_count = 0
    total_tensor_bytes = 0
    for shard, header in tensor_headers.items():
        header_tensor_count += len(header)
        for tensor, tensor_metadata in header.items():
            if weight_map.get(tensor) != shard:
                raise VerificationError(f"SafeTensors index maps tensor to the wrong shard: {tensor}")
            offsets = tensor_metadata["data_offsets"]
            total_tensor_bytes += offsets[1] - offsets[0]
    if header_tensor_count != len(weight_map):
        raise VerificationError("SafeTensors headers and index tensor membership differ")
    if expected_total is not None and total_tensor_bytes != expected_total:
        raise VerificationError("SafeTensors tensor bytes differ from index total_size")
    download_revision = semantics.get("download_metadata_revision")
    if download_revision is not None:
        metadata_files = {
            name: data for name, data in captured.items() if name.endswith(".metadata")
        }
        if not metadata_files:
            raise VerificationError("Hugging Face download provenance metadata is absent")
        for name, data in metadata_files.items():
            try:
                lines = data.decode("utf-8").splitlines()
            except UnicodeDecodeError as exc:
                raise VerificationError(f"download metadata is not UTF-8: {name}") from exc
            if len(lines) != 3 or lines[0] != download_revision:
                raise VerificationError(f"download provenance revision differs for {name}")


def _normalize_archive_member(name: str, archive_root: str) -> tuple[str, bool]:
    candidate = name.rstrip("/")
    if not candidate or candidate.startswith("/") or "\\" in candidate or "\x00" in candidate:
        raise VerificationError(f"unsafe archive member: {name!r}")
    pure = PurePosixPath(candidate)
    if any(part in {"", ".", ".."} for part in pure.parts):
        raise VerificationError(f"unsafe archive member: {name!r}")
    if pure.parts[0] != archive_root:
        raise VerificationError(f"archive member is outside locked root {archive_root}: {name!r}")
    if len(pure.parts) == 1:
        return ".", True
    relative = PurePosixPath(*pure.parts[1:]).as_posix()
    return _safe_relative(relative), False


def verify_tar_tree(
    lock: Mapping[str, Any],
    artifact_name: str,
    stream: BinaryIO,
    *,
    source_spec: str,
    image: str,
    container_path: str,
    batch_size: int,
) -> None:
    artifact = _artifact(lock, artifact_name, "docker_volume_tree")
    provenance = artifact.get("provenance")
    if not isinstance(provenance, dict):
        raise VerificationError(f"artifact {artifact_name} lacks provenance")
    expected_values = {
        "source_spec": source_spec,
        "service_image": image,
        "container_path": container_path,
    }
    for key, value in expected_values.items():
        if provenance.get(key) != value:
            raise VerificationError(f"{artifact_name} provenance differs for {key}")
    derived_from = provenance.get("derived_from_artifact")
    if derived_from is not None:
        artifacts = lock.get("artifacts")
        source_artifact = artifacts.get(derived_from) if isinstance(artifacts, dict) else None
        source_provenance = (
            source_artifact.get("provenance") if isinstance(source_artifact, dict) else None
        )
        if (
            not isinstance(source_provenance, dict)
            or provenance.get("derived_from_revision") != source_provenance.get("revision")
        ):
            raise VerificationError(f"{artifact_name} derived-model provenance is inconsistent")
    archive_root = artifact.get("archive_root")
    _safe_relative(archive_root)
    locked_files, locked_dirs = _locked_tree(artifact)
    seen_files: set[str] = set()
    seen_dirs: set[str] = set()
    root_seen = False
    captured: dict[str, bytes] = {}
    tensor_headers: dict[str, dict[str, Any]] = {}

    try:
        archive = tarfile.open(fileobj=stream, mode="r|*")
        for member in archive:
            name, is_root = _normalize_archive_member(member.name, archive_root)
            if is_root:
                if root_seen or not member.isdir():
                    raise VerificationError("archive root must occur once as a directory")
                root_seen = True
                continue
            if member.isdir():
                if name in seen_dirs or name in seen_files:
                    raise VerificationError(f"duplicate archive member: {name}")
                seen_dirs.add(name)
                continue
            if not member.isfile():
                raise VerificationError(f"archive member is not a regular file: {name}")
            if name in seen_files or name in seen_dirs:
                raise VerificationError(f"duplicate archive member: {name}")
            seen_files.add(name)
            locked = locked_files.get(name)
            if locked is None:
                raise VerificationError(f"unexpected archive file: {name}")
            if locked["type"] != "file":
                raise VerificationError(f"archive member type differs for {name}")
            if member.size != locked["size"] or member.mode != locked["mode"]:
                raise VerificationError(f"archive member size or mode differs for {name}")
            extracted = archive.extractfile(member)
            if extracted is None:
                raise VerificationError(f"cannot stream archive member: {name}")
            if (
                name.endswith((".json", ".pbtxt", ".metadata"))
                and member.size <= 64 * 1024 * 1024
            ):
                data = extracted.read()
                if len(data) != member.size:
                    raise VerificationError(f"truncated archive member: {name}")
                digest = hashlib.sha256(data).hexdigest()
                header = None
                captured[name] = data
            else:
                digest, header = _hash_file(extracted, member.size, name)
            if digest != locked["sha256"]:
                raise VerificationError(f"archive member sha256 differs for {name}")
            if header is not None:
                tensor_headers[name] = header
    except (tarfile.TarError, OSError) as exc:
        raise VerificationError(f"cannot read artifact archive: {exc}") from exc

    if not root_seen:
        raise VerificationError("archive does not contain its locked root directory")
    if seen_files != set(locked_files):
        raise VerificationError(
            "archive file membership differs; "
            f"missing={sorted(set(locked_files) - seen_files)}, "
            f"extra={sorted(seen_files - set(locked_files))}"
        )
    if seen_dirs != locked_dirs:
        raise VerificationError(
            "archive directory membership differs; "
            f"missing={sorted(locked_dirs - seen_dirs)}, extra={sorted(seen_dirs - locked_dirs)}"
        )
    semantic_type = artifact.get("semantics", {}).get("type")
    if semantic_type == "indexed_safetensors_model":
        _verify_model_semantics(artifact, captured, tensor_headers)
    elif semantic_type == "triton_tensorrt_repository":
        _verify_triton_semantics(artifact, captured, locked_files, batch_size)
    else:
        raise VerificationError(f"unsupported artifact semantic type: {semantic_type}")


def _pbtxt_scalar(text: str, key: str) -> str:
    matches = re.findall(
        rf"(?m)^([ \t]*){re.escape(key)}\s*:\s*(?:\"([^\"]+)\"|([^\s#]+))\s*$",
        text,
    )
    if not matches:
        raise VerificationError(f"Triton config must contain exactly one {key}")
    minimum_indent = min(len(indent.expandtabs(8)) for indent, _, _ in matches)
    outermost = [
        (quoted, bare)
        for indent, quoted, bare in matches
        if len(indent.expandtabs(8)) == minimum_indent
    ]
    if len(outermost) != 1:
        raise VerificationError(f"Triton config must contain exactly one outermost {key}")
    quoted, bare = outermost[0]
    return quoted or bare


def _verify_triton_semantics(
    artifact: Mapping[str, Any],
    captured: Mapping[str, bytes],
    locked_files: Mapping[str, Mapping[str, Any]],
    batch_size: int,
) -> None:
    semantics = artifact.get("semantics")
    models = semantics.get("models") if isinstance(semantics, dict) else None
    if not isinstance(models, list) or not models:
        raise VerificationError("Triton semantic lock lacks models")
    if batch_size <= 0:
        raise VerificationError("Triton batch size must be positive")
    for model in models:
        if not isinstance(model, dict):
            raise VerificationError("invalid Triton model semantic entry")
        name = model.get("name")
        config_path = model.get("config_path")
        if not isinstance(name, str) or not isinstance(config_path, str) or config_path not in captured:
            raise VerificationError("Triton config was not captured")
        try:
            text = captured[config_path].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise VerificationError(f"Triton config is not UTF-8: {config_path}") from exc
        expected_filename = model.get("default_model_filename")
        expected = {
            "name": name,
            "platform": "tensorrt_plan",
            "max_batch_size": str(batch_size),
            "default_model_filename": expected_filename,
        }
        for key, value in expected.items():
            if _pbtxt_scalar(text, key) != value:
                raise VerificationError(f"Triton {name} semantic differs for {key}")
        required_tokens = model.get("required_tokens")
        if not isinstance(required_tokens, list) or any(
            not isinstance(token, str) or not token or token not in text for token in required_tokens
        ):
            raise VerificationError(f"Triton {name} required input/output semantics differ")
        engine_path = f"{name}/1/{expected_filename}"
        if engine_path not in locked_files:
            raise VerificationError(f"Triton default engine is absent from lock: {engine_path}")
        expected_pattern = rf"^cosmos_embed1_(?:text|video)_NVIDIA_Thor_{batch_size}_fp16\.engine$"
        if not isinstance(expected_filename, str) or re.fullmatch(expected_pattern, expected_filename) is None:
            raise VerificationError(f"Triton default engine is not the locked Thor batch: {name}")


def capture_hf_tree(snapshot: Path, repository_root: Path) -> dict[str, Any]:
    actual_files, actual_dirs = _walk_nodes(snapshot)
    files: list[dict[str, Any]] = []
    for name, entry in sorted(actual_files.items()):
        if not entry.is_symlink():
            raise VerificationError(f"Hugging Face snapshot member is not a symlink: {name}")
        target = os.readlink(entry.path)
        target_path = Path(entry.path).parent / target
        resolved = target_path.resolve(strict=True)
        if resolved.parent != repository_root.resolve(strict=True) / "blobs":
            raise VerificationError(f"snapshot symlink escapes blob store: {name}")
        target_stat = os.lstat(resolved)
        if not stat.S_ISREG(target_stat.st_mode):
            raise VerificationError(f"snapshot target is not a regular file: {name}")
        with resolved.open("rb") as stream:
            digest, _ = _hash_file(stream, target_stat.st_size, name)
        files.append(
            {
                "path": name,
                "type": "symlink",
                "target": target,
                "blob": resolved.name,
                "size": target_stat.st_size,
                "sha256": digest,
                "mode": stat.S_IMODE(target_stat.st_mode),
            }
        )
    return {"directories": sorted(actual_dirs), "files": files}


def capture_tar_tree(stream: BinaryIO, archive_root: str) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    directories: list[str] = []
    seen: set[str] = set()
    root_seen = False
    try:
        archive = tarfile.open(fileobj=stream, mode="r|*")
        for member in archive:
            name, is_root = _normalize_archive_member(member.name, archive_root)
            if is_root:
                if root_seen or not member.isdir():
                    raise VerificationError("archive root must occur once as a directory")
                root_seen = True
                continue
            if name in seen:
                raise VerificationError(f"duplicate archive member: {name}")
            seen.add(name)
            if member.isdir():
                directories.append(name)
                continue
            if not member.isfile():
                raise VerificationError(f"archive member is not a regular file: {name}")
            extracted = archive.extractfile(member)
            if extracted is None:
                raise VerificationError(f"cannot stream archive member: {name}")
            digest, _ = _hash_file(extracted, member.size, name)
            files.append(
                {
                    "path": name,
                    "type": "file",
                    "size": member.size,
                    "sha256": digest,
                    "mode": member.mode,
                }
            )
    except (tarfile.TarError, OSError) as exc:
        raise VerificationError(f"cannot read artifact archive: {exc}") from exc
    if not root_seen:
        raise VerificationError("archive does not contain its root directory")
    return {"directories": sorted(directories), "files": sorted(files, key=lambda item: item["path"])}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    hf = subparsers.add_parser("verify-hf", help="verify one locked Hugging Face snapshot")
    hf.add_argument("--lock", type=Path, required=True)
    hf.add_argument("--artifact", required=True)
    hf.add_argument("--snapshot", type=Path, required=True)
    hf.add_argument("--repository-root", type=Path, required=True)
    hf.add_argument("--repository", required=True)
    hf.add_argument("--revision", required=True)
    volume = subparsers.add_parser(
        "verify-tar", help="verify one Docker-volume subtree archive on stdin"
    )
    volume.add_argument("--lock", type=Path, required=True)
    volume.add_argument("--artifact", required=True)
    volume.add_argument("--source-spec", required=True)
    volume.add_argument("--image", required=True)
    volume.add_argument("--container-path", required=True)
    volume.add_argument("--batch-size", type=int, required=True)
    capture_hf = subparsers.add_parser("capture-hf", help="emit a reviewable snapshot tree")
    capture_hf.add_argument("--snapshot", type=Path, required=True)
    capture_hf.add_argument("--repository-root", type=Path, required=True)
    capture_tar = subparsers.add_parser("capture-tar", help="emit a reviewable archive tree")
    capture_tar.add_argument("--archive-root", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "verify-hf":
            verify_hf_snapshot(
                load_lock(args.lock),
                args.artifact,
                args.snapshot,
                args.repository_root,
                args.repository,
                args.revision,
            )
            print(f"[OK] Exact locked artifact verified: {args.artifact}")
        elif args.command == "verify-tar":
            verify_tar_tree(
                load_lock(args.lock),
                args.artifact,
                sys.stdin.buffer,
                source_spec=args.source_spec,
                image=args.image,
                container_path=args.container_path,
                batch_size=args.batch_size,
            )
            print(f"[OK] Exact locked artifact verified: {args.artifact}")
        elif args.command == "capture-hf":
            print(
                json.dumps(
                    capture_hf_tree(args.snapshot, args.repository_root),
                    indent=2,
                    sort_keys=True,
                )
            )
        elif args.command == "capture-tar":
            print(json.dumps(capture_tar_tree(sys.stdin.buffer, args.archive_root), indent=2, sort_keys=True))
        else:  # pragma: no cover - argparse makes this unreachable
            raise VerificationError(f"unsupported command: {args.command}")
    except (VerificationError, OSError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
