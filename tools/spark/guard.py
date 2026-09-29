#!/usr/bin/env python3
"""Spark-specific reserve guard; no tegrastats or Thor service dependencies."""
import concurrent.futures
import json
import signal
import subprocess
import threading
import time
from bootstrap import STATE, available, compose, memory_reserve, private_write

stop = threading.Event()
for sig in (signal.SIGTERM, signal.SIGINT):
    signal.signal(sig, lambda *_: stop.set())


def halt(cid):
    try:
        result = subprocess.run(['docker', 'stop', '-t', '2', cid], capture_output=True, timeout=8)
        return {'id': cid, 'code': result.returncode}
    except subprocess.TimeoutExpired:
        return {'id': cid, 'timeout': True}


def main():
    reserve = memory_reserve()
    tripped = False
    while not stop.wait(1):
        free = available()
        private_write(STATE / 'guard-status.json', json.dumps({'time': time.time(), 'available_gib': free, 'floor_gib': reserve}))
        if free < reserve and not tripped:
            tripped = True
            ids = subprocess.run(compose('ps', '-q'), capture_output=True, text=True, timeout=15, check=True).stdout.splitlines()
            with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
                results = list(pool.map(halt, ids))
            private_write(STATE / 'guard-trip.json', json.dumps({'time': time.time(), 'available_gib': free, 'floor_gib': reserve, 'stops': results}, indent=2))
        if free >= reserve:
            tripped = False

if __name__ == '__main__':
    main()
