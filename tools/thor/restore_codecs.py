#!/usr/bin/env python3
"""Restore previously reviewed archive bytes without resolving newer packages.

The current Ubuntu package index may select newer versions than the committed
October lock. This downloader accepts only that reviewed lock's exact URL,
size, SHA-256, ARM64 package metadata and complete membership; it cannot refresh it.
"""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('locked_thor_codecs', ROOT / 'deploy/docker/thor-local/audio/codec_bundle.py')
codecs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(codecs)
BUNDLE = ROOT / 'deploy/docker/thor-current/vios-codecs/bundle'
LOCK = ROOT / 'deploy/docker/thor-current/codecs.lock.json'


def restore():
    codecs.bundle_packages()
    lock = codecs.load_canonical_lock(LOCK)
    if BUNDLE.exists():
        codecs.verify_bundle(BUNDLE, lock_path=LOCK)
        print('Existing exact codec bundle verified.')
        return
    BUNDLE.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.locked-restore-', dir=BUNDLE.parent))
    try:
        for package in lock['packages']:
            destination = staging / package['filename']
            codecs.validate_url(package['url'])
            print(f'Restoring pinned codec archive: {package["filename"]}', flush=True)
            subprocess.run(['curl', '--fail', '--location', '--silent', '--show-error', '--retry', '3',
                            '--connect-timeout', '15', '--max-time', '120',
                            '--output', str(destination), package['url']], check=True)
            if destination.stat().st_size != package['size'] or codecs.sha256_file(destination) != package['sha256']:
                raise RuntimeError(f'Pinned codec checksum mismatch: {package["filename"]}')
        shutil.copyfile(LOCK, staging / 'manifest.json')
        codecs.verify_bundle(staging, lock_path=LOCK)
        os.rename(staging, BUNDLE)
        print('Restored all 63 reviewed October codec archives; historical locks are unchanged.')
    finally:
        if staging.exists():
            shutil.rmtree(staging)


if __name__ == '__main__':
    restore()
