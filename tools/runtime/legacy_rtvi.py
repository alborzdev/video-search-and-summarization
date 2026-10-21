#!/usr/bin/env python3
"""Recover the custom 3.2.1 source from immutable local Git objects, offline.

This is an explicit legacy build preparation tool, never a render/start hook.
No current application files, refs, index, images or services are modified.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile

SCRIPT_PATH = Path(__file__).resolve()
# Container verification needs no repository. Discover a checkout only for the
# explicitly invoked staging command, without assuming the helper's copy depth.
ROOT = (SCRIPT_PATH.parents[2]
        if SCRIPT_PATH.parent.name == 'runtime' and SCRIPT_PATH.parent.parent.name == 'tools'
        else None)
REVISION = 'c4a44c4d956a8c039483f8f392544b8f999dc62c'
SOURCE_PREFIX = 'services/rtvi/rt-vlm/src/'
CODEC_INSTALLER = 'services/rtvi/rt-embed/src/scripts/install_codecs_nonroot.sh'
FILE_TABLE_SHA256 = '8c4e5ee95903847f9f900411578b951eef4deece9c167ecc8303ed694f8b1a36'
DEFAULT_CONTEXT = ROOT / 'deploy/docker/thor-local/audio/legacy-rtvi-src' if ROOT else None


def git_read(repo, *arguments):
    try:
        return subprocess.check_output(['git', '-C', str(repo), *arguments],
                                       stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as error:
        raise RuntimeError(f'Frozen legacy Git objects at {REVISION} are unavailable; '
                           'fetch the complete repository history before staging. '
                           'Current 3.3 source cannot substitute for them.') from error


def read_frozen_blob(repo, path):
    relative = PurePosixPath(path)
    if (relative.is_absolute() or '..' in relative.parts
            or not (path.startswith(SOURCE_PREFIX) or path == CODEC_INSTALLER)):
        raise RuntimeError('Only the pinned legacy RTVI source paths may be read')
    return git_read(repo, 'show', f'{REVISION}:{path}')


def table_digest(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def reject_symlinks(path):
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise RuntimeError('Legacy source paths cannot traverse symlinks')


def verify(context):
    context = Path(context).absolute()
    reject_symlinks(context)
    manifest_path = context / 'manifest.json'
    if manifest_path.is_symlink() or not manifest_path.is_file() or manifest_path.stat().st_size > 65536:
        raise RuntimeError('Legacy source manifest must be a bounded regular file')
    manifest = json.loads(manifest_path.read_text())
    files = manifest.get('files')
    if (set(manifest) != {'revision', 'source_prefix', 'files'}
            or manifest['revision'] != REVISION or manifest['source_prefix'] != SOURCE_PREFIX
            or not isinstance(files, list) or table_digest(files) != FILE_TABLE_SHA256):
        raise RuntimeError('Legacy source manifest differs from the pinned custom 3.2.1 tree')
    expected = {'manifest.json', *(entry['path'] for entry in files)}
    actual = set()
    for path in context.rglob('*'):
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise RuntimeError('Legacy source context contains a symlink or special file')
        if path.is_file():
            actual.add(path.relative_to(context).as_posix())
    if actual != expected:
        raise RuntimeError('Legacy source context contains missing or unexpected files')
    for entry in files:
        path = context / entry['path']
        if (path.stat().st_size != entry['size']
                or hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']):
            raise RuntimeError(f'Frozen legacy source bytes changed: {entry["path"]}')
    return manifest


def stage(repo=ROOT, context=DEFAULT_CONTEXT):
    if repo is None or context is None:
        raise RuntimeError('Legacy source staging requires the checked-out tools/runtime helper')
    context = Path(context).absolute()
    reject_symlinks(context)
    if context.exists():
        return verify(context)
    # Only regular Git blobs from the fixed subtree are eligible; no worktree,
    # LFS downloads, submodules or link extraction are involved.
    entries = git_read(repo, 'ls-tree', '-rz', REVISION, '--', SOURCE_PREFIX)
    contents = []
    for record in entries.split(b'\0'):
        if not record:
            continue
        metadata, raw_path = record.split(b'\t', 1)
        mode, kind, _oid = metadata.split()
        path = raw_path.decode()
        if mode != b'100644' or kind != b'blob' or not path.startswith(SOURCE_PREFIX):
            raise RuntimeError('Legacy tree contains an unexpected path or file mode')
        contents.append(('src/' + path.removeprefix(SOURCE_PREFIX), read_frozen_blob(repo, path)))
    files = [{'path': path, 'size': len(body), 'sha256': hashlib.sha256(body).hexdigest()}
             for path, body in contents]
    if table_digest(files) != FILE_TABLE_SHA256:
        raise RuntimeError('Git tree differs from the pinned custom 3.2.1 source')
    manifest = dict(revision=REVISION, source_prefix=SOURCE_PREFIX, files=files)
    context.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.legacy-rtvi-', dir=context.parent))
    try:
        for path, body in contents:
            target = temporary / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
            target.chmod(0o644)
        (temporary / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        verify(temporary)
        os.rename(temporary, context)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('stage', 'verify'))
    parser.add_argument('--context', type=Path, default=DEFAULT_CONTEXT)
    args = parser.parse_args()
    if args.context is None:
        parser.error('--context is required when verifying outside the checkout')
    manifest = stage(context=args.context) if args.command == 'stage' else verify(args.context)
    print(f'Verified {len(manifest["files"])} custom 3.2.1 source files from {REVISION}; no build or startup.')


if __name__ == '__main__':
    main()
