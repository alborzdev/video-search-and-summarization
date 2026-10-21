#!/usr/bin/env python3
"""Fail closed before installing checksum-locked public archives in an image."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit


def load_lock(path):
    lock = json.loads(Path(path).read_text())
    filenames = set()
    packages = set()
    for item in lock['packages']:
        name = item['filename']
        if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.+:%~_-]*\.deb', name)
                or name in filenames or item['package'] in packages):
            raise ValueError('Unsafe/duplicate archive identity: ' + name)
        url = urlsplit(item['url'])
        if (url.scheme != 'https' or url.netloc != 'ports.ubuntu.com'
                or not url.path.startswith('/ubuntu-ports/pool/')
                or url.query or url.fragment):
            raise ValueError('Expected an official public Ubuntu HTTPS archive URL')
        if (item['architecture'] not in ('arm64', 'all') or item['size'] <= 0
                or not re.fullmatch('[0-9a-f]{64}', item['sha256'])):
            raise ValueError('Invalid locked archive metadata: ' + name)
        filenames.add(name)
        packages.add(item['package'])
    if not filenames:
        raise ValueError('Empty dependency lock')
    return lock


def verify_archive(item, archive, identity=True):
    archive = Path(archive)
    if archive.is_symlink() or not archive.is_file():
        raise ValueError('Missing/unsafe archive: ' + item['filename'])
    if (archive.stat().st_size != item['size']
            or hashlib.sha256(archive.read_bytes()).hexdigest() != item['sha256']):
        raise ValueError('Checksum/size mismatch: ' + item['filename'])
    if identity:
        metadata = subprocess.check_output(
            ['dpkg-deb', '--show', '--showformat=${Package}\t${Version}\t${Architecture}', str(archive)], text=True)
        if metadata != '\t'.join(item[key] for key in ('package', 'version', 'architecture')):
            raise ValueError('Debian identity mismatch: ' + item['filename'])


def verify_bundle(root):
    root = Path(root)
    lock = load_lock(root / 'dev-dependencies.lock.json')
    for item in lock['packages']:
        verify_archive(item, root / item['filename'])
    if {path.name for path in root.glob('*.deb')} != {item['filename'] for item in lock['packages']}:
        raise ValueError('Unexpected .deb in bundle')
    print(f"Verified {len(lock['packages'])} locked public Ubuntu archives")


if __name__ == '__main__':
    verify_bundle(sys.argv[1])
