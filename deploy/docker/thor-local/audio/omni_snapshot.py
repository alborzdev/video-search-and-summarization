#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Create and verify an immutable inventory for a local Omni checkpoint.

This tool never downloads a model.  It records the exact bytes that an
operator staged out of band, so the offline launch lane cannot silently switch
to a different checkpoint on a later restart.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path


SCHEMA_VERSION = 1
SUPPORTED_REPOSITORIES = {
    "nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-FP8",
    "nvidia/Nemotron-Nano-V3-Omni-GA0420-FP8",
}
REQUIRED_METADATA = {"config.json", "tokenizer_config.json"}
SUPPORTED_ARCHITECTURES = {"NemotronH_Nano_VL_V2", "NemotronH_Nano_Omni_Reasoning_V3"}


class SnapshotError(RuntimeError):
    """Raised when a model snapshot cannot be trusted for offline launch."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_hf_symlink(root: Path, path: Path, repository: str, revision: str) -> None:
    target = os.readlink(path)
    match = re.fullmatch(r"\.\./\.\./blobs/([0-9a-f]{40}|[0-9a-f]{64})", target)
    if match is None:
        raise SnapshotError(f"model snapshot has a non-canonical Hugging Face symlink: {path}")
    repository_root = root.parent.parent
    expected_root_name = f"models--{repository.replace('/', '--')}"
    if (
        root.name != revision
        or root.parent.name != "snapshots"
        or repository_root.name != expected_root_name
    ):
        raise SnapshotError("symlink-backed snapshot is outside its exact Hugging Face cache layout")
    try:
        resolved = path.resolve(strict=True)
        blob_root = (repository_root / "blobs").resolve(strict=True)
    except OSError as exc:
        raise SnapshotError(f"model snapshot contains a broken symlink: {path}: {exc}") from exc
    if resolved.parent != blob_root or resolved.name != match.group(1):
        raise SnapshotError(f"model snapshot symlink escapes its Hugging Face blob store: {path}")


def _safe_files(root: Path, repository: str, revision: str) -> list[Path]:
    if not root.is_absolute():
        raise SnapshotError("model directory must be an absolute path")
    if not root.is_dir():
        raise SnapshotError(f"model directory does not exist: {root}")

    files: list[Path] = []
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(directory)
        for name in dirnames:
            candidate = current / name
            if candidate.is_symlink():
                raise SnapshotError(f"model snapshot contains a linked directory: {candidate}")
        for name in filenames:
            candidate = current / name
            if candidate.is_symlink():
                _validate_hf_symlink(root, candidate, repository, revision)
            mode = candidate.stat().st_mode
            if not stat.S_ISREG(mode):
                raise SnapshotError(f"model snapshot contains a non-regular file: {candidate}")
            files.append(candidate)

    if not files:
        raise SnapshotError("model snapshot is empty")
    return sorted(files, key=lambda value: value.relative_to(root).as_posix())


def validate_snapshot_shape(root: Path, files: list[Path]) -> dict[str, object]:
    relatives = {path.relative_to(root).as_posix() for path in files}
    missing = sorted(REQUIRED_METADATA - relatives)
    if missing:
        raise SnapshotError(f"model snapshot is missing required metadata: {', '.join(missing)}")
    if not any(name.endswith(".safetensors") for name in relatives):
        raise SnapshotError("model snapshot contains no .safetensors weights")
    if not any(name.endswith(".py") for name in relatives):
        raise SnapshotError(
            "model snapshot contains no Python implementation files, but the pinned Omni lane "
            "requires VLM_TRUST_REMOTE_CODE=true"
        )

    try:
        config = json.loads((root / "config.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SnapshotError(f"config.json is not valid JSON: {exc}") from exc
    if not isinstance(config, dict):
        raise SnapshotError("config.json must contain a JSON object")
    architectures = config.get("architectures")
    model_type = config.get("model_type")
    if not isinstance(architectures, list) or not architectures or not all(
        isinstance(value, str) and value.strip() for value in architectures
    ):
        raise SnapshotError("config.json must define at least one architecture")
    if not isinstance(model_type, str) or not model_type.strip():
        raise SnapshotError("config.json must define a non-empty model_type")
    if not set(architectures).issubset(SUPPORTED_ARCHITECTURES):
        raise SnapshotError(
            "config.json architecture is not one of the RT-VLM Nemotron Omni executors"
        )
    return {"architectures": architectures, "model_type": model_type}


def build_manifest(root: Path, repository: str, revision: str) -> dict[str, object]:
    if repository not in SUPPORTED_REPOSITORIES:
        supported = ", ".join(sorted(SUPPORTED_REPOSITORIES))
        raise SnapshotError(f"unsupported repository {repository!r}; supported: {supported}")
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise SnapshotError("model revision must be a full lowercase 40-character Git commit")
    files = _safe_files(root, repository, revision)
    config = validate_snapshot_shape(root, files)
    entries = []
    total_bytes = 0
    for path in files:
        size = path.stat().st_size
        total_bytes += size
        entry = {
            "path": path.relative_to(root).as_posix(),
            "sha256": sha256_file(path),
            "size": size,
        }
        if path.is_symlink():
            target = os.readlink(path)
            entry.update({"type": "symlink", "target": target, "blob": Path(target).name})
        entries.append(entry)
    return {
        "schema_version": SCHEMA_VERSION,
        "repository": repository,
        "revision": revision,
        "config": config,
        "file_count": len(entries),
        "total_bytes": total_bytes,
        "files": entries,
    }


def load_manifest(path: Path) -> dict[str, object]:
    if path.is_symlink():
        raise SnapshotError(f"snapshot manifest must not be a symlink: {path}")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SnapshotError(f"cannot read snapshot manifest {path}: {exc}") from exc
    if not isinstance(document, dict) or document.get("schema_version") != SCHEMA_VERSION:
        raise SnapshotError(f"unsupported snapshot manifest schema in {path}")
    if document.get("repository") not in SUPPORTED_REPOSITORIES:
        raise SnapshotError(f"snapshot manifest has an unsupported repository: {document.get('repository')!r}")
    if not isinstance(document.get("revision"), str) or not re.fullmatch(
        r"[0-9a-f]{40}", document["revision"]
    ):
        raise SnapshotError("snapshot manifest has an invalid pinned revision")
    return document


def verify_manifest(root: Path, manifest_path: Path) -> dict[str, object]:
    expected = load_manifest(manifest_path)
    actual = build_manifest(root, str(expected["repository"]), str(expected["revision"]))
    if actual != expected:
        expected_entries = {entry["path"]: entry for entry in expected.get("files", [])}
        actual_entries = {entry["path"]: entry for entry in actual.get("files", [])}
        missing = sorted(set(expected_entries) - set(actual_entries))
        extra = sorted(set(actual_entries) - set(expected_entries))
        changed = sorted(
            name
            for name in set(expected_entries) & set(actual_entries)
            if expected_entries[name] != actual_entries[name]
        )
        details = []
        if missing:
            details.append(f"missing={missing}")
        if extra:
            details.append(f"extra={extra}")
        if changed:
            details.append(f"changed={changed}")
        raise SnapshotError("model snapshot does not match its manifest" + (f": {'; '.join(details)}" if details else ""))
    return actual


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    lock = subparsers.add_parser("lock", help="write a new immutable snapshot inventory")
    lock.add_argument("--model-dir", required=True, type=Path)
    lock.add_argument("--repository", required=True, choices=sorted(SUPPORTED_REPOSITORIES))
    lock.add_argument("--revision", required=True, help="full 40-character Hugging Face Git commit")
    lock.add_argument("--output", required=True, type=Path)

    verify = subparsers.add_parser("verify", help="verify a snapshot against an inventory")
    verify.add_argument("--model-dir", required=True, type=Path)
    verify.add_argument("--manifest", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        if args.command == "lock":
            if not args.output.is_absolute():
                raise SnapshotError("manifest output must be an absolute path")
            if not args.output.parent.is_dir():
                raise SnapshotError(f"manifest parent directory does not exist: {args.output.parent}")
            if args.output.is_symlink():
                raise SnapshotError(f"manifest output must not be a symlink: {args.output}")
            model_dir = args.model_dir.resolve()
            output = args.output.parent.resolve() / args.output.name
            if output == model_dir or model_dir in output.parents:
                raise SnapshotError("manifest output must be outside the model snapshot")
            document = build_manifest(model_dir, args.repository, args.revision)
            payload = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()
            try:
                descriptor = os.open(
                    output,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                )
            except OSError as exc:
                raise SnapshotError(f"cannot create new manifest {output}: {exc}") from exc
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
            print(
                f"locked {document['file_count']} files / {document['total_bytes']} bytes "
                f"for {document['repository']} at {document['revision']}"
            )
        else:
            document = verify_manifest(args.model_dir.resolve(), args.manifest.resolve())
            print(
                f"verified {document['file_count']} files / {document['total_bytes']} bytes "
                f"for {document['repository']}"
            )
    except SnapshotError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
