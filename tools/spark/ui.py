#!/usr/bin/env python3
"""Switch only the Spark UI between source-mounted Turbopack and its built image."""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / '.spark'
UI = ROOT / 'services/ui'
APP = 'nv-metropolis-bp-vss-ui'
RUNTIME_UID = 65532
DEV_BUDGET_GIB = 4
spec = importlib.util.spec_from_file_location('spark_ui_bootstrap', Path(__file__).with_name('bootstrap.py'))
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


def run(args, **kwargs):
    return subprocess.run([str(value) for value in args], check=True, **kwargs)


def clean_env():
    return {key: value for key, value in os.environ.items()
            if key in ('PATH', 'HOME', 'DOCKER_HOST', 'DOCKER_CONTEXT', 'XDG_RUNTIME_DIR')}


def compose(override=None):
    command = ['docker', 'compose', '--project-name', 'vss-spark', '-f', str(STATE / 'compose.json')]
    if override:
        command += ['-f', str(override)]
    return command


def load_configuration():
    settings = json.loads((STATE / 'settings.json').read_text())
    graph = json.loads((STATE / 'compose.json').read_text())
    service = graph['services']['vss-ui']
    if not service.get('image', '').startswith('vss-spark-'):
        raise RuntimeError('Refusing UI changes outside the rendered Spark candidate.')
    return settings, service


def preflight(needs_dev_budget):
    bootstrap.doctor()  # GB10-only; never uses Thor runtime management.
    run(['systemctl', '--user', 'is-active', '--quiet', 'vss-spark-guard.service'])
    if needs_dev_budget:
        required = bootstrap.memory_reserve() + DEV_BUDGET_GIB
        if bootstrap.available() < required:
            raise RuntimeError(f'UI admission refused: need {required:g} GiB available (saved reserve + 4 GiB UI budget).')


def dependency_fingerprint():
    manifest = json.loads((UI / 'package.json').read_text())
    paths = {UI / 'package.json', UI / 'package-lock.json'}
    for workspace in manifest.get('workspaces', []):
        paths.update(folder / 'package.json' for folder in UI.glob(workspace)
                     if (folder / 'package.json').is_file())
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(str(path.relative_to(UI)).encode() + b'\0' + path.read_bytes() + b'\0')
    return digest.hexdigest()


def validate_dependencies():
    stamp = STATE / 'ui-deps.json'
    required = [UI / 'node_modules/next/dist/bin/next',
                UI / 'node_modules/@next/swc-linux-arm64-gnu/next-swc.linux-arm64-gnu.node']
    if (not all(path.is_file() for path in required) or not stamp.is_file()
            or json.loads(stamp.read_text()).get('fingerprint') != dependency_fingerprint()):
        raise RuntimeError('UI dependencies are missing or stale. Run python3 tools/spark/ui.py deps first.')


def current_mode():
    result = run(compose() + ['ps', '-q', 'vss-ui'], env=clean_env(), capture_output=True, text=True)
    container = result.stdout.strip()
    if not container:
        return 'stopped'
    result = run(['docker', 'inspect', '--format', '{{.Config.WorkingDir}}', container],
                 capture_output=True, text=True)
    return 'dev' if result.stdout.strip() == f'/workspace/apps/{APP}' else 'built'


def install_dependencies(settings, service):
    if current_mode() == 'dev':
        raise RuntimeError('Return to built mode before reinstalling dependencies used by the dev server.')
    registry = settings.get('npm_registry', 'https://registry.npmjs.org')
    parsed = urlsplit(registry)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RuntimeError('The saved npm registry must be HTTPS without credentials, query or fragment.')
    cache = STATE / 'ui-npm-cache'
    cache.mkdir(mode=0o700, exist_ok=True)
    run(['docker', 'run', '--rm', '--runtime', 'runc', '--user', f'{os.getuid()}:{os.getgid()}',
         '--memory', '4g', '--memory-swap', '4g', '--cpus', '2',
         '-v', f'{UI}:/workspace', '-v', f'{cache}:/npm-cache', '-w', '/workspace',
         '-e', 'NODE_OPTIONS=--max-old-space-size=2048', '-e', 'NEXT_TELEMETRY_DISABLED=1',
         '-e', 'NODE_ENV=development',
         '-e', 'PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1', '--entrypoint', 'npm', service['image'],
         'ci', '--include=dev', '--prefer-offline', '--no-audit', '--no-fund', '--cache', '/npm-cache', '--registry', registry],
        env=clean_env())
    bootstrap.private_write(STATE / 'ui-deps.json', json.dumps({'fingerprint': dependency_fingerprint()}))
    validate_dependencies()
    print('Lockfile-backed UI dependencies installed; the running built UI was unchanged.')


def dev_override(service):
    port = int(service.get('environment', {}).get('PORT', '3001'))
    if not 1 <= port <= 65535:
        raise RuntimeError('The rendered UI port is invalid.')
    return {'services': {'vss-ui': {
        'user': f'{RUNTIME_UID}:{os.getgid()}',
        'working_dir': f'/workspace/apps/{APP}',
        'runtime': 'runc',
        'entrypoint': ['/bin/sh', '-ec'],
        'command': [f'umask 0002; exec node ../../node_modules/next/dist/bin/next dev --turbopack -H 0.0.0.0 -p {port}'],
        'volumes': [
            {'type': 'bind', 'source': str(UI), 'target': '/workspace'},
            {'type': 'bind', 'source': str(STATE / 'ui-next'), 'target': f'/workspace/apps/{APP}/.next'},
        ],
        'environment': {'NODE_ENV': 'development', 'NODE_OPTIONS': '--max-old-space-size=2048',
                        'NEXT_TELEMETRY_DISABLED': '1'},
        'mem_limit': '4g', 'memswap_limit': '4g',
    }}}


def prepare_cache(service):
    cache = STATE / 'ui-next'
    target = UI / 'apps' / APP / '.next'
    if cache.is_symlink() or target.is_symlink():
        raise RuntimeError('Generated UI cache paths must not be symlinks.')
    cache.mkdir(mode=0o775, exist_ok=True)
    target.mkdir(exist_ok=True)
    # Only this isolated generated cache is chowned. Source, dependencies and
    # private saved reports/history/rules keep their existing ownership.
    script = '''const fs=require('fs');function fix(p){const s=fs.lstatSync(p);if(s.isSymbolicLink())return;fs.chownSync(p,65532,Number(process.argv[1]));fs.chmodSync(p,s.isDirectory()?0o2775:0o664);if(s.isDirectory())for(const n of fs.readdirSync(p))fix(p+'/'+n)}fix('/cache');'''
    run(['docker', 'run', '--rm', '--runtime', 'runc', '--network', 'none', '--user', '0:0',
         '--memory', '256m', '--memory-swap', '256m', '--cpus', '1', '-v', f'{cache}:/cache',
         '--entrypoint', 'node', service['image'], '-e', script, str(os.getgid())], env=clean_env())


def switch(mode, service):
    override = None
    if mode == 'dev':
        validate_dependencies()
        override = STATE / 'compose-ui-dev.json'
        bootstrap.private_write(override, json.dumps(dev_override(service), indent=2) + '\n')
    command = compose(override)
    run(command + ['config', '--quiet'], env=clean_env())
    run(compose() + ['stop', '-t', '5', 'vss-ui'], env=clean_env())
    try:
        if mode == 'dev':
            prepare_cache(service)
        run(command + ['up', '-d', '--no-deps', '--force-recreate', '--no-build', '--pull', 'never', 'vss-ui'],
            env=clean_env())
    except (RuntimeError, OSError, subprocess.CalledProcessError):
        if mode == 'dev':
            run(compose() + ['up', '-d', '--no-deps', '--force-recreate', '--no-build', '--pull', 'never', 'vss-ui'],
                env=clean_env())
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['deps', 'dev', 'built', 'status'])
    args = parser.parse_args()
    settings, service = load_configuration()
    if args.mode == 'status':
        print(f'UI mode: {current_mode()}')
        return
    preflight(args.mode in ('deps', 'dev'))
    if args.mode == 'deps':
        install_dependencies(settings, service)
        return
    switch(args.mode, service)
    print(f"UI mode: {args.mode}; http://{settings['host_ip']}:7777/")
    if args.mode == 'dev':
        print('First visit compiles the page; subsequent source edits hot reload. The Spark guard remains active.')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        sys.exit(1)
