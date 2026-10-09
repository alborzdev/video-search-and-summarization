#!/usr/bin/env python3
"""Replace VIOS's absolute CUDA driver lookup with the loader's soname.

JetPack injects the driver at a BSP-dependent location. Keep the ELF layout
unchanged and fail the build if the reviewed vendor string is not unique.
"""
from pathlib import Path
import sys

ABSOLUTE = b'/usr/lib/aarch64-linux-gnu/libcuda.so\0'
SONAME = b'libcuda.so.1\0'


def patch(path):
    content = path.read_bytes()
    if not content.startswith(b'\x7fELF') or content.count(ABSOLUTE) != 1:
        raise RuntimeError('Unexpected VIOS ELF or CUDA lookup; review the new vendor binary')
    replacement = SONAME.ljust(len(ABSOLUTE), b'\0')
    path.write_bytes(content.replace(ABSOLUTE, replacement))
    print('VIOS CUDA driver lookup now uses libcuda.so.1')


if __name__ == '__main__':
    patch(Path(sys.argv[1]))
