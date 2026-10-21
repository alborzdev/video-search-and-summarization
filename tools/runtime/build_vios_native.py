#!/usr/bin/env python3
"""Stage the bounded offline ARM64 VIOS build. Never install host packages or run containers."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess

REPO = Path(__file__).resolve().parents[2]
RECIPES = REPO / 'deploy/docker/vios-native33'
BUILDER_BASE = 'ghcr.io/nvidia-ai-blueprints/vss/vss-rt-vlm@sha256:23f844c9715e2d98ac01260b085fd1f9c7523d748dd594995c4ec952b7f4f65d'
PUBLIC_BASE = 'ghcr.io/nvidia-ai-blueprints/vss/vss-vios-streamprocessing@sha256:426f48add56f5ba95b0a70eb8036f4b0590da9fb3228d2065f539d6f9721723a'
SOURCE_PATHS = ('src', 'include', 'prebuilts/aarch64', 'configs', 'Makefile', 'Makefile.dep')
LOCK_PATHS = {
    'dev': RECIPES / 'dev-dependencies.lock.json',
    'native': RECIPES / 'native-libs.lock.json',
    'historical': REPO / 'deploy/docker/thor-current/codecs.lock.json',
    'sodium': REPO / 'deploy/docker/thor-current/rtvi-vlm33-codecs.lock.json',
}
_spec = importlib.util.spec_from_file_location('vios_native_verify', RECIPES / 'verify-bundle.py')
VERIFY = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(VERIFY)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + '\n')


def owned(path):
    path = Path(path).absolute()
    if not path.resolve().is_relative_to((REPO / 'work').resolve()):
        raise ValueError('Generated files must stay under the repository ignored work/ directory')
    if path.is_symlink():
        raise ValueError('Generated directory must not be a symlink')
    return path


def new_directory(path):
    path = owned(path)
    path.mkdir(parents=True, exist_ok=False)
    return path


def manifest_files(source):
    source = Path(source).resolve()
    files = {}
    ignore = shutil.ignore_patterns('*.o', '*.d', '__pycache__', '*.bak', '*~')
    for name in SOURCE_PATHS:
        root = source / name
        if root.is_symlink():
            raise ValueError('Source root must not be a symlink: ' + name)
        candidates = sorted(root.rglob('*')) if root.is_dir() else [root]
        for path in candidates:
            if path.is_dir() and not path.is_symlink():
                continue
            if path.name in ignore(str(path.parent), [path.name]):
                continue
            rel = str(path.relative_to(source))
            if path.is_symlink():
                target = path.readlink()
                if target.is_absolute() or not path.resolve().is_relative_to(source):
                    raise ValueError('Source symlink escapes public tree: ' + rel)
                files[rel] = {'symlink': str(target)}
            elif path.is_file():
                files[rel] = {'sha256': digest(path)}
            else:
                raise ValueError('Missing or special source input: ' + rel)
    return files


def snapshot(work):
    work = owned(work)
    work.mkdir(parents=True, exist_ok=True)
    source = REPO / 'services/vios'
    files = manifest_files(source)
    tree = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    target = new_directory(work / ('source-' + tree[:16]))
    for name in SOURCE_PATHS:
        root = source / name
        if root.is_dir():
            (target / name).mkdir(parents=True, exist_ok=True)
            for directory in root.rglob('*'):
                if directory.is_dir() and not directory.is_symlink() and '__pycache__' not in directory.parts:
                    (target / directory.relative_to(source)).mkdir(parents=True, exist_ok=True)
    for name, entry in files.items():
        src, dst = source / name, target / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        if 'symlink' in entry:
            dst.symlink_to(entry['symlink'])
        else:
            shutil.copy2(src, dst)
    # Re-read the copy to catch source changes during staging.
    if manifest_files(target) != files:
        raise ValueError('Source changed while freezing; use a fresh work directory')
    write_json(target / 'source-manifest.json', {'tree_sha256': tree, 'files': files})
    return {'source': str(target), 'tree_sha256': tree, 'files': len(files)}


def stage_bundle(kind, cache, target):
    lock_path = LOCK_PATHS[kind]
    lock = VERIFY.load_lock(lock_path)
    target.mkdir()
    for item in lock['packages']:
        archive = Path(cache) / item['filename']
        VERIFY.verify_archive(item, archive)
        shutil.copyfile(archive, target / item['filename'])
    return lock


def builder(work, cache):
    lock = VERIFY.load_lock(LOCK_PATHS['dev'])
    if lock['base_image'] != BUILDER_BASE:
        raise ValueError('Builder lock/base mismatch')
    context = new_directory(Path(work) / 'builder-context')
    stage_bundle('dev', cache, context / 'dev-bundle')
    shutil.copyfile(LOCK_PATHS['dev'], context / 'dev-bundle/dev-dependencies.lock.json')
    for name in ('verify-bundle.py', 'build-native.sh'):
        shutil.copyfile(RECIPES / name, context / name)
    shutil.copyfile(RECIPES / 'Dockerfile.builder', context / 'Dockerfile')
    (context / '.dockerignore').write_text('*\n!Dockerfile\n!verify-bundle.py\n!build-native.sh\n!dev-bundle/\n!dev-bundle/**\n')
    return {'context': str(context), 'packages': len(lock['packages']), 'builder_base': BUILDER_BASE,
            'lock_sha256': digest(LOCK_PATHS['dev'])}


def stage_codecs(context, native_cache, historical_cache, sodium_cache):
    native = stage_bundle('native', native_cache, context / 'native-bundle')
    bundle = context / 'native-bundle'
    (bundle / 'checksums.sha256').write_text(''.join(item['sha256'] + '  ' + item['filename'] + '\n' for item in native['packages']))
    (bundle / 'metadata.tsv').write_text(''.join('\t'.join(item[key] for key in ('filename', 'package', 'version', 'architecture')) + '\n' for item in native['packages']))
    stage_bundle('historical', historical_cache, context / 'codec-bundle')
    shutil.copyfile(LOCK_PATHS['historical'], context / 'codec-bundle/manifest.json')
    shutil.copyfile(LOCK_PATHS['historical'], context / 'codecs.lock.json')
    shutil.copyfile(REPO / 'deploy/docker/thor-local/vios-codecs/install-codec-bundle.sh', context / 'install-codec-bundle.sh')
    sodium = VERIFY.load_lock(LOCK_PATHS['sodium'])['packages']
    if len(sodium) != 1 or sodium[0]['package'] != 'libsodium23':
        raise ValueError('Unexpected sodium supplement')
    item = sodium[0]
    archive = Path(sodium_cache) / item['filename']
    VERIFY.verify_archive(item, archive)
    shutil.copyfile(archive, context / 'libsodium23.deb')
    (context / 'libsodium23.sha256').write_text(item['sha256'] + '  libsodium23.deb\n')
    shutil.copyfile(RECIPES / 'Dockerfile.codecs', context / 'Dockerfile')
    (context / '.dockerignore').write_text('*\n!Dockerfile\n!native-bundle/\n!native-bundle/**\n!codec-bundle/\n!codec-bundle/**\n!codecs.lock.json\n!install-codec-bundle.sh\n!libsodium23.deb\n!libsodium23.sha256\n')
    receipt = {'context': str(context), 'base': PUBLIC_BASE,
               'locks': {kind: digest(LOCK_PATHS[kind]) for kind in ('native', 'historical', 'sodium')}}
    write_json(context / 'codec-source-receipt.json', receipt)
    return receipt


def codecs(work, native_cache, historical_cache, sodium_cache):
    context = new_directory(Path(work) / 'codec-context')
    return stage_codecs(context, native_cache, historical_cache, sodium_cache)


def verify_output(output, source):
    output, source = owned(output).resolve(), owned(source).resolve()
    frozen = json.loads((source / 'source-manifest.json').read_text())
    actual = manifest_files(source)
    if (actual != frozen['files'] or hashlib.sha256(json.dumps(actual, sort_keys=True).encode()).hexdigest() != frozen['tree_sha256']):
        raise ValueError('Frozen source snapshot has changed')
    if json.loads((output / 'source-manifest.json').read_text()) != frozen:
        raise ValueError('Native output source receipt differs from frozen snapshot')
    expected = json.loads((output / 'output-checksums.json').read_text())
    if 'launch_vst' not in expected or 'not found' in (output / 'builder-linker.txt').read_text():
        raise ValueError('Missing executable or unresolved builder ELF closure')
    for name, expected_digest in expected.items():
        path = output / name
        if (not path.resolve().is_relative_to(output) or path.is_symlink()
                or not re.fullmatch('[0-9a-f]{64}', expected_digest)
                or digest(path) != expected_digest):
            raise ValueError('Altered/unsafe native output: ' + name)
    return frozen, expected


def runtime(work, output, source, native_cache, historical_cache, sodium_cache):
    frozen, expected = verify_output(output, source)
    output = Path(output).resolve()
    context = new_directory(Path(work) / ('runtime-context-' + output.name))
    codec_receipt = stage_codecs(context, native_cache, historical_cache, sodium_cache)
    target_root = context / 'runtime'
    target_root.mkdir()
    # Use the public immutable manifest digest, never a local config ID as FROM.
    # The codec closure and native overlay share one offline build context.
    overlay = (RECIPES / 'Dockerfile.runtime').read_text()
    overlay = overlay[overlay.index('USER root'): ]
    (context / 'Dockerfile').write_text((RECIPES / 'Dockerfile.codecs').read_text() + '\n' + overlay)
    checksums, copied, skipped = [], 0, 0
    for path in [output / 'launch_vst', *sorted((output / 'prebuilts/aarch64').rglob('*'))]:
        if path.is_dir():
            continue
        name = str(path.relative_to(output))
        if not path.resolve().is_relative_to(output):
            raise ValueError('Native symlink escapes output: ' + name)
        if path.suffix == '.a':
            if path.is_file() and not path.is_symlink():
                skipped += path.stat().st_size
            continue
        with path.open('rb') as stream:
            if stream.read(4) != b'\x7fELF':
                continue
        target = target_root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            if path.readlink().is_absolute():
                raise ValueError('Absolute native symlink: ' + name)
            target.symlink_to(path.readlink())
        else:
            if name not in expected:
                raise ValueError('Unrecorded ELF output: ' + name)
            shutil.copy2(path, target)
            copied += target.stat().st_size
            checksums.append(expected[name] + '  ' + name)
    # Every exported symlink must resolve inside the filtered runtime too.
    for path in target_root.rglob('*'):
        if path.is_symlink() and (not path.resolve().is_relative_to(target_root) or not path.exists()):
            raise ValueError('Filtered native symlink target was not retained: ' + str(path))
    shutil.copyfile(output / 'source-manifest.json', target_root / 'build-source-manifest.json')
    checksums.append(digest(target_root / 'build-source-manifest.json') + '  build-source-manifest.json')
    (context / 'checksums.sha256').write_text('\n'.join(checksums) + '\n')
    with (context / '.dockerignore').open('a') as stream:
        stream.write('!checksums.sha256\n!runtime/\n!runtime/**\n')
    receipt = {'context': str(context), 'source_tree_sha256': frozen['tree_sha256'],
               'runtime_base_manifest': PUBLIC_BASE, 'codec_locks': codec_receipt['locks'],
               'copied_elf_bytes': copied, 'skipped_static_bytes': skipped,
               'scope': 'streamprocessing only; separate sensor-management source is not compiled'}
    write_json(context / 'runtime-overlay-receipt.json', receipt)
    return receipt


def fetch(kind, cache):
    """Explicit operator action; fetch only checksum-locked public archives."""
    cache = owned(cache)
    cache.mkdir(parents=True, exist_ok=True)
    lock = VERIFY.load_lock(LOCK_PATHS[kind])
    for item in lock['packages']:
        archive = cache / item['filename']
        if archive.exists() or archive.is_symlink():
            VERIFY.verify_archive(item, archive)
            continue
        partial = archive.with_name(archive.name + '.partial')
        if partial.exists() or partial.is_symlink():
            raise ValueError('Refusing existing partial download: ' + str(partial))
        try:
            subprocess.run(['curl', '--fail', '--location', '--silent', '--show-error',
                            '--proto', '=https', '--proto-redir', '=https', '--connect-timeout', '15',
                            '--max-time', '180', '--retry', '1', '--max-filesize', str(item['size']),
                            '--output', str(partial), item['url']], check=True)
            VERIFY.verify_archive(item, partial)
            partial.rename(archive)
        finally:
            partial.unlink(missing_ok=True)
    return {'cache': str(cache), 'packages': len(lock['packages']), 'lock_sha256': digest(LOCK_PATHS[kind])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, default=REPO / 'work/vios-native33')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('snapshot')
    p = commands.add_parser('builder')
    p.add_argument('--cache', type=Path, required=True)
    p = commands.add_parser('codecs')
    for name in ('native-cache', 'historical-cache', 'sodium-cache'):
        p.add_argument('--' + name, type=Path, required=True)
    p = commands.add_parser('runtime')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--source', type=Path, required=True)
    for name in ('native-cache', 'historical-cache', 'sodium-cache'):
        p.add_argument('--' + name, type=Path, required=True)
    p = commands.add_parser('fetch')
    p.add_argument('--kind', choices=tuple(LOCK_PATHS), required=True)
    p.add_argument('--cache', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'snapshot':
        result = snapshot(args.work)
    elif args.command == 'builder':
        result = builder(args.work, args.cache)
    elif args.command == 'codecs':
        result = codecs(args.work, args.native_cache, args.historical_cache, args.sodium_cache)
    elif args.command == 'runtime':
        result = runtime(args.work, args.output, args.source, args.native_cache, args.historical_cache, args.sodium_cache)
    else:
        result = fetch(args.kind, args.cache)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
