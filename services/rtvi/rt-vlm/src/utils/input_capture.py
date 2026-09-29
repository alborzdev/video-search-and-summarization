# SPDX-License-Identifier: Apache-2.0
"""Bounded diagnostic export of engine-bound video arrays. Never enabled implicitly."""
import fcntl
import hashlib
import json
from pathlib import Path
import re
import time

import numpy as np

MAX_CAPTURE_SECONDS = 120
MAX_REQUESTS = 12
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_ARRAY_BYTES = 4 * 1024 * 1024
MAX_JSON_BYTES = 512 * 1024


def capture_input(root, request_id, frames, metadata):
    """Return a capture directory, or None when disabled, unsupported or full.

    Callers isolate exceptions from inference. Arrays are preserved losslessly;
    this function does not resize, resample, or retain GPU allocations.
    """
    if not root:
        return None
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', request_id):
        raise ValueError('Invalid capture request ID')
    if not isinstance(frames, np.ndarray) or frames.dtype != np.uint8:
        return None
    if frames.ndim != 4 or frames.shape[-1] not in (3, 4) or not frames.flags.c_contiguous:
        return None
    if not 0 < frames.nbytes <= MAX_ARRAY_BYTES:
        return None
    started = time.monotonic()
    raw = memoryview(frames).cast('B')
    payload = dict(metadata, request_id=request_id, shape=list(frames.shape), dtype=str(frames.dtype),
                   pixels_sha256=hashlib.sha256(raw).hexdigest(), captured_unix=time.time())
    encoded = json.dumps(payload, ensure_ascii=False).encode()
    if len(encoded) > MAX_JSON_BYTES:
        return None
    directory = Path(root)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory / '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        started_file = directory / '.started'
        if not started_file.exists():
            started_file.write_text(str(time.time()))
        elapsed_window = time.time() - float(started_file.read_text())
        if elapsed_window < 0 or elapsed_window >= MAX_CAPTURE_SECONDS:
            return None
        captures = [p for p in directory.iterdir() if p.is_dir()]
        used = sum(p.stat().st_size for p in directory.rglob('*') if p.is_file())
        # Reserve headers and bounded input/response JSON for every captured call.
        reserved = len(captures) * (2 * MAX_JSON_BYTES + 4096)
        if len(captures) >= MAX_REQUESTS or used + reserved + frames.nbytes + 2 * MAX_JSON_BYTES + 4096 > MAX_TOTAL_BYTES:
            return None
        target = directory / request_id
        target.mkdir(mode=0o700)  # Never overwrite another request, including partial captures.
        with (target / 'frames.npy').open('xb') as output:
            np.save(output, frames, allow_pickle=False)
        (target / 'input.json').write_bytes(encoded)
        elapsed = time.monotonic() - started
        (target / 'capture-seconds.txt').write_text(str(elapsed))
        return target


def capture_response(target, response):
    if target is None:
        return
    encoded = json.dumps(response, ensure_ascii=False).encode()
    if len(encoded) > MAX_JSON_BYTES:
        return
    with (Path(target) / 'response.json').open('xb') as output:
        output.write(encoded)
