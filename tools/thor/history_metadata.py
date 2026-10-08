#!/usr/bin/env python3
"""Thor recording metadata bridge; the SQL/API contract is shared with Spark."""
from http.server import ThreadingHTTPServer
import importlib.util
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / '.thor'
spec = importlib.util.spec_from_file_location('shared_recording_metadata', ROOT / 'tools/spark/history_metadata.py')
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)


def unavailable_capacity():
    raise RuntimeError('Thor capacity is governed by its runtime guard and workload admission service')


def start():
    unit = Path.home() / '.config/systemd/user/vss-thor-history-metadata.service'
    unit.parent.mkdir(parents=True, exist_ok=True)
    if any(c in str(ROOT) for c in '\n"%'):
        raise RuntimeError('Unsupported systemd checkout path')
    unit.write_text(f'''[Unit]
Description=Thor VSS read-only recording metadata
[Service]
ExecStart=/usr/bin/python3 "{Path(__file__).resolve()}" serve
Restart=no
MemoryMax=128M
CPUQuota=100%
UMask=0077
''')
    subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', '--user', 'start', unit.name], check=True)


if __name__ == '__main__':
    if len(sys.argv) == 2 and sys.argv[1] == 'serve':
        ThreadingHTTPServer(('127.0.0.1', 8102), shared.handler_type(
            shared.token_value(STATE), capacity=unavailable_capacity)).serve_forever()
    elif len(sys.argv) == 2 and sys.argv[1] == 'start':
        start()
    else:
        raise SystemExit('Use serve or start')
