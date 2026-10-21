#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Stage the small 3.3 RT-VLM codec supplement; install only inside an image.

Only the explicit stage command can download. Verify and install are offline;
no command operates Docker or the host package manager.
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import urllib.parse
import urllib.request

SCRIPT = Path(__file__).resolve()
REPO = SCRIPT.parents[4] if len(SCRIPT.parents) > 4 else Path('/')
DEFAULT_LOCK = REPO / 'deploy/docker/thor-current/rtvi-vlm33-codecs.lock.json'
DEFAULT_BUNDLE = REPO / 'deploy/docker/thor-current/rtvi-vlm33-codecs/bundle'


def load_lock(path):
    lock = json.loads(Path(path).read_text())
    if lock.get('architecture') != 'arm64' or len(lock.get('packages', [])) != 1:
        raise ValueError('Expected the separate one-package ARM64 runtime supplement')
    package = lock['packages'][0]
    if package['package'] != 'libsodium23' or package['architecture'] != 'arm64':
        raise ValueError('Unexpected runtime supplement package')
    if Path(package['filename']).name != package['filename'] or not package['filename'].endswith('_arm64.deb'):
        raise ValueError('Unsafe supplement filename')
    url = urllib.parse.urlsplit(package['url'])
    if url.scheme != 'https' or url.netloc != 'ports.ubuntu.com' or url.username or url.password:
        raise ValueError('Supplement URL must be the public Ubuntu HTTPS origin')
    return lock, package


def verify_archive(path, package):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size != package['size']:
        raise ValueError('Supplement archive must be a regular file of the locked size')
    if hashlib.sha256(path.read_bytes()).hexdigest() != package['sha256']:
        raise ValueError('Supplement archive checksum does not match its lock')
    for field in ('Package', 'Version', 'Architecture'):
        result = subprocess.run(['dpkg-deb', '--field', str(path), field], check=True,
                                capture_output=True, text=True, timeout=15)
        if result.stdout.strip() != package[field.lower()]:
            raise ValueError(f'Supplement Debian {field} does not match its lock')


def verify_bundle(bundle, lock_path):
    lock, package = load_lock(lock_path)
    bundle = Path(bundle)
    if bundle.is_symlink() or not bundle.is_dir():
        raise ValueError('Missing regular supplement bundle directory')
    if {p.name for p in bundle.iterdir()} != {package['filename'], 'manifest.json'}:
        raise ValueError('Unexpected supplement bundle contents')
    manifest = bundle / 'manifest.json'
    if manifest.is_symlink() or manifest.read_bytes() != Path(lock_path).read_bytes():
        raise ValueError('Supplement manifest does not match its canonical lock')
    verify_archive(bundle / package['filename'], package)
    return lock, package


def stage(bundle, lock_path, archive=None):
    _, package = load_lock(lock_path)
    bundle = Path(bundle)
    if bundle.exists():
        verify_bundle(bundle, lock_path)
        return
    bundle.parent.mkdir(parents=True, exist_ok=True)
    temporary = bundle.with_name(bundle.name + '.partial')
    temporary.mkdir()
    try:
        target = temporary / package['filename']
        if archive:
            verify_archive(archive, package)
            shutil.copyfile(archive, target)
        else:
            with urllib.request.urlopen(package['url'], timeout=30) as response:
                if urllib.parse.urlsplit(response.geturl()).netloc != 'ports.ubuntu.com':
                    raise ValueError('Unexpected supplement download origin')
                target.write_bytes(response.read(package['size'] + 1))
        verify_archive(target, package)
        shutil.copyfile(lock_path, temporary / 'manifest.json')
        verify_bundle(temporary, lock_path)
        temporary.rename(bundle)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def install(bundle, lock_path):
    if not Path('/.dockerenv').is_file() and os.environ.get('VSS_CODEC_IMAGE_BUILD') != '1':
        raise RuntimeError('Install is permitted only inside the container image build')
    _, package = verify_bundle(bundle, lock_path)
    subprocess.run(['dpkg-deb', '--extract', str(Path(bundle) / package['filename']), '/'], check=True)
    # dpkg-deb extraction does not run Debian update-alternatives. Its BLAS
    # and LAPACK libraries remain in package subdirectories on the new base.
    Path('/etc/ld.so.conf.d/vss-codec-linear-algebra.conf').write_text(
        '/usr/lib/aarch64-linux-gnu/blas\n/usr/lib/aarch64-linux-gnu/lapack\n')
    subprocess.run(['/usr/sbin/ldconfig'], check=True, timeout=30)
    ctypes.CDLL('/usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstlibav.so', mode=os.RTLD_NOW)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('stage', 'verify', 'install'))
    parser.add_argument('--bundle', type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument('--lock', type=Path, default=DEFAULT_LOCK)
    parser.add_argument('--archive', type=Path, help='Already downloaded, checksum-locked local archive for stage')
    args = parser.parse_args()
    if args.command == 'stage':
        stage(args.bundle, args.lock, args.archive)
    elif args.command == 'verify':
        verify_bundle(args.bundle, args.lock)
    else:
        install(args.bundle, args.lock)
    print(f'RT-VLM 3.3 codec supplement {args.command} passed')


if __name__ == '__main__':
    main()
