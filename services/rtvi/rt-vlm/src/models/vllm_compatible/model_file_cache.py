# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Optional, checkpoint-scoped file-cache advice for unified-memory hosts.

This module deliberately uses only the standard library. Advice does not delete
files or guarantee reclamation; CUDA warmup and real inference remain necessary.
"""

import logging
import os
from pathlib import Path
import stat


def _memory_gib():
    fields = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, _, value = line.partition(":")
        if key in ("MemFree", "MemAvailable", "Cached"):
            fields[key] = round(int(value.split()[0]) / 1048576, 3)
    return fields


def reclaim_loaded_model_file_cache(model_path, logger=None):
    """Advise away only active checkpoint safetensors after engine loading.

    Default off. The caller must explicitly opt in and provide the candidate
    cache root; the active checkpoint must be a directory strictly below it.
    Only top-level safetensors are considered, matching the loaded Cosmos
    checkpoint. Symlinks escaping that checkpoint are excluded, and shared
    inodes are advised once. Other model caches and application files are never
    traversed. Per-file errors are aggregated into a bounded log message.
    """
    if os.environ.get("VLM_RECLAIM_MODEL_FILE_CACHE", "").strip().lower() not in (
        "1", "true", "yes", "on"
    ):
        return None

    configured_root = os.environ.get("VLM_FILE_CACHE_RECLAIM_ROOT", "").strip()
    if not configured_root:
        raise ValueError("VLM_FILE_CACHE_RECLAIM_ROOT is required for file-cache advice")
    root = Path(configured_root).resolve(strict=True)
    checkpoint = Path(model_path).resolve(strict=True)
    if not root.is_dir() or not checkpoint.is_dir() or root not in checkpoint.parents:
        raise ValueError("File-cache advice requires a checkpoint inside the candidate cache root")
    if not hasattr(os, "posix_fadvise") or not hasattr(os, "POSIX_FADV_DONTNEED"):
        raise RuntimeError("Checkpoint file-cache advice requires POSIX_FADV_DONTNEED")

    before = _memory_gib()
    advised_files = advised_bytes = skipped_files = errors = 0
    seen = set()
    for candidate in checkpoint.glob("*.safetensors"):
        try:
            path = candidate.resolve(strict=True)
            if not path.is_relative_to(checkpoint):
                skipped_files += 1
                continue
            flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
            fd = os.open(path, flags)
            try:
                metadata = os.fstat(fd)
                inode = (metadata.st_dev, metadata.st_ino)
                if not stat.S_ISREG(metadata.st_mode) or inode in seen:
                    skipped_files += 1
                    continue
                seen.add(inode)
                os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
                advised_files += 1
                advised_bytes += metadata.st_size
            finally:
                os.close(fd)
        except OSError:
            errors += 1

    report = {
        "before_gib": before,
        "after_gib": _memory_gib(),
        "advised_files": advised_files,
        "advised_bytes": advised_bytes,
        "skipped_files": skipped_files,
        "errors": errors,
    }
    logger = logger or logging.getLogger(__name__)
    log = logger.warning if errors else logger.info
    log("Loaded checkpoint file-cache advice: %s", report)
    return report
