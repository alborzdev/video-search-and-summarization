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


def halt(cid):
    try:
        result = subprocess.run(['docker', 'stop', '-t', '2', cid], capture_output=True, timeout=8)
        return {'id': cid, 'code': result.returncode}
    except subprocess.TimeoutExpired:
        return {'id': cid, 'timeout': True}
    except OSError as error:
        return {'id': cid, 'error': type(error).__name__}


def record(name, value):
    # A full disk must not prevent the memory guard from stopping workloads.
    try:
        private_write(STATE / name, json.dumps(value, indent=2))
    except OSError:
        pass


def main():
    reserve = memory_reserve()
    tripped = False
    next_retry = 0
    while not stop.wait(1):
        free = available()
        record('guard-status.json', {'time': time.time(), 'available_gib': free, 'floor_gib': reserve})
        if free < reserve and (not tripped or time.monotonic() >= next_retry):
            tripped = True
            trip = {'time': time.time(), 'available_gib': free, 'floor_gib': reserve, 'stops': []}
            record('guard-trip-in-progress.json', trip)
            try:
                ids = subprocess.run(compose('ps', '-q'), capture_output=True, text=True, timeout=15, check=True).stdout.splitlines()
                with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
                    trip['stops'] = list(pool.map(halt, ids))
            except (OSError, subprocess.SubprocessError) as error:
                trip['error'] = type(error).__name__
            record('guard-trip.json', trip)
            # Keep protecting an ongoing low-memory interval: failed stops and
            # workloads started after the first trip both need another attempt.
            next_retry = time.monotonic() + 10
        if free >= reserve:
            tripped = False

if __name__ == '__main__':
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    main()
