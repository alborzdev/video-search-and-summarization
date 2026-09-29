#!/usr/bin/env python3
"""Switch only the Thor UI between source-mounted HMR and its built image."""
import argparse
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / 'artifacts/thor-memory-2026-09-09'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('mode', choices=['dev', 'built'])
args = parser.parse_args()
cmd = json.loads((STATE / 'lvs-compose-command.json').read_text())
env = dict(os.environ, **json.loads((STATE / 'lvs-compose-public-env.json').read_text()))
ui = ROOT / 'services/ui'
if args.mode == 'dev' and not (ui / 'node_modules/next/dist/bin/next').exists():
    parser.error('Install UI dependencies first: cd services/ui && npm ci')
subprocess.run(cmd + ['stop', '-t', '5', 'vss-ui'], env=env, cwd=ROOT, check=True)
cache = ui / 'apps/nv-metropolis-bp-vss-ui/.next'
cache.mkdir(exist_ok=True)
# Keep generated cache writable by both the host developer and runtime UID.
subprocess.run(['docker', 'run', '--rm', '--network', 'none', '--user', '0:0',
    '-v', f'{cache}:/cache', '--entrypoint', 'node', 'vss-agent-ui:thor-local', '-e',
    "const fs=require('fs'); function fix(p){const s=fs.lstatSync(p); if(s.isSymbolicLink())return; fs.chownSync(p, Number(process.argv[1]), Number(process.argv[2])); fs.chmodSync(p,s.isDirectory()?0o2775:0o664); if(s.isDirectory()) for(const n of fs.readdirSync(p))fix(p+'/'+n)} fix('/cache');",
    str(65532 if args.mode == 'dev' else os.getuid()), str(os.getgid())], check=True)
if args.mode == 'dev':
    override = STATE / 'compose-ui-dev.json'
    override.write_text(json.dumps({'services': {'vss-ui': {
        'user': f'65532:{os.getgid()}',
        'working_dir': '/workspace/apps/nv-metropolis-bp-vss-ui',
        'entrypoint': [],
        'command': ['node', '../../node_modules/next/dist/bin/next', 'dev', '--turbopack', '-H', '0.0.0.0', '-p', '3001'],
        'volumes': [f'{ui}:/workspace'],
        'environment': {'NODE_ENV': 'development', 'NODE_OPTIONS': '--max-old-space-size=2048', 'NEXT_TELEMETRY_DISABLED': '1'},
        'mem_limit': '4g', 'memswap_limit': '4g',
    }}}, indent=2))
    cmd += ['-f', str(override)]
subprocess.run(cmd + ['up', '-d', '--no-deps', '--force-recreate', '--no-build', '--pull', 'never', 'vss-ui'], env=env, cwd=ROOT, check=True)
public_env = dict(line.split('=', 1) for line in (ROOT / 'deploy/docker/thor-local/generated.env').read_text().splitlines() if '=' in line and not line.lstrip().startswith('#'))
public_env.update(env)
print(f"UI mode: {args.mode}; http://{public_env.get('VSS_PUBLIC_HOST', public_env.get('HOST_IP', 'localhost'))}:{public_env.get('VSS_PUBLIC_PORT', '7777')}")
if args.mode == 'dev':
    print('Initial compilation happens on first visit; subsequent source edits hot reload.')
