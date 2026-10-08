#!/usr/bin/env python3
"""Install UI dependencies and run Thor source HMR with bounded CPU memory."""
import argparse
import json
import os
from pathlib import Path
import sys

import bootstrap

ROOT = bootstrap.ROOT
STATE = bootstrap.STATE
UI = ROOT / 'services/ui'
IMAGE = 'node:22.22.3-bookworm-slim'


def preflight():
    bootstrap.doctor()
    bootstrap.require_guard()
    if bootstrap.shared.available() < bootstrap.RESERVE + 4:
        raise RuntimeError('Thor UI requires the diagnostic reserve plus 4 GiB')


def dependencies():
    preflight()
    active = bootstrap.run(bootstrap.compose('ps', '-q', 'vss-ui'), capture_output=True, text=True).stdout.strip()
    if active:
        raise RuntimeError('Stop only vss-ui before replacing its active dependencies')
    cache = STATE / 'ui-npm-cache'
    cache.mkdir(parents=True, exist_ok=True)
    bootstrap.run(['docker', 'run', '--rm', '--runtime', 'runc', '--user', f'{os.getuid()}:{os.getgid()}',
        '--memory', '4g', '--memory-swap', '4g', '--cpus', '2',
        '-v', f'{UI}:/workspace', '-v', f'{cache}:/npm-cache', '-w', '/workspace',
        '-e', 'NODE_OPTIONS=--max-old-space-size=2048', '-e', 'NEXT_TELEMETRY_DISABLED=1',
        '-e', 'NODE_ENV=development', '-e', 'PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1',
        '--entrypoint', 'npm', IMAGE, 'ci', '--include=dev', '--prefer-offline',
        '--no-audit', '--no-fund', '--cache', '/npm-cache', '--registry', 'https://registry.npmmirror.com'])


def dev():
    preflight()
    if not (UI / 'node_modules/next/dist/bin/next').is_file():
        raise RuntimeError('Run python3 tools/thor/ui.py deps first')
    cache = STATE / 'ui-next'
    if cache.is_symlink():
        raise RuntimeError('Generated cache cannot be a symlink')
    cache.mkdir(exist_ok=True)
    bootstrap.run(['docker', 'run', '--rm', '--network', 'none', '--runtime', 'runc', '--user', '0:0',
        '--memory', '256m', '--memory-swap', '256m', '--cpus', '1',
        '-v', f'{cache}:/cache', '--entrypoint', 'node', IMAGE, '-e',
        "const fs=require('fs'); function fix(p){const s=fs.lstatSync(p); if(s.isSymbolicLink())return; "
        "fs.chownSync(p,65532,Number(process.argv[1])); fs.chmodSync(p,s.isDirectory()?0o2775:0o664); "
        "if(s.isDirectory()) for(const n of fs.readdirSync(p))fix(p+'/'+n)} fix('/cache');", str(os.getgid())])
    bootstrap.run(bootstrap.compose('up', '-d', '--no-deps', '--no-build', '--pull', 'never', 'vss-ui'))
    print(f'Thor source UI: http://{bootstrap.settings()["host_ip"]}:3001/')
    print('Gateway :7777 becomes available after the app stage is started.')


def status():
    bootstrap.run(bootstrap.compose('ps', '-a', 'vss-ui'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['deps', 'dev', 'status'])
    args = parser.parse_args()
    try:
        {'deps': dependencies, 'dev': dev, 'status': status}[args.action]()
    except (RuntimeError, OSError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        sys.exit(1)
