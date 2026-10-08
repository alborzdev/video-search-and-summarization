#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Launch the pinned Cosmos service without a second private MPS daemon.

The embedding service retains its own MPS server. Keep the vendor launcher's
model, decoder, readiness and shutdown behavior, and reject unreviewed changes
to its bytes before altering the single MPS startup function.
"""
import hashlib
import os
from pathlib import Path
import sys


VENDOR = Path('/opt/nvidia/rtvi/start_rtvi_vlm.sh')
VENDOR_SHA256 = 'e696c0a008436185451e9891dde1dd4efefb4e3409d3bca31178f46c99eac8e0'
FUNCTION = b'start_cuda_mps_server() {\n'


def without_private_mps(original: bytes) -> bytes:
    if hashlib.sha256(original).hexdigest() != VENDOR_SHA256:
        raise RuntimeError('Cosmos vendor launcher changed; review the pinned image before startup')
    if original.count(FUNCTION) != 1:
        raise RuntimeError('Cosmos vendor MPS function is ambiguous')
    return original.replace(FUNCTION, FUNCTION +
                            b'    echo "Thor: Cosmos uses CUDA without a private MPS daemon"\n'
                            b'    return\n', 1)


def main() -> None:
    script = without_private_mps(VENDOR.read_bytes())
    # An anonymous, inherited descriptor avoids modifying the image or leaving
    # generated launch scripts in a model cache or writable shared volume.
    descriptor = os.memfd_create('thor-cosmos-launcher', 0)
    with os.fdopen(os.dup(descriptor), 'wb') as stream:
        stream.write(script)
    os.lseek(descriptor, 0, os.SEEK_SET)
    os.execv('/bin/bash', ['/bin/bash', f'/proc/self/fd/{descriptor}', *sys.argv[1:]])


if __name__ == '__main__':
    main()
