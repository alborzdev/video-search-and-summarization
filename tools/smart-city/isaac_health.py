#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Bounded read-only check of the two stream products and real encoder progress."""
import argparse
import hashlib
import json
import shutil
import signal
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path

from isaac_demo import (
    CAMERA_IDS,
    CITY,
    bridge,
    configured_backend,
    json_request,
    selected_scene_stage,
    script,
    sources,
    stream_progress,
)

SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def delivery_sample(state, actual, backend):
    """Validate one real writer/runtime sample with backend-specific bounds."""
    stream = state.get('streams') or {}
    if not (state.get('loaded') and state.get('playing') and state.get('streaming')
            and not state.get('streamBusy') and state.get('stage') == selected_scene_stage()):
        raise RuntimeError('Isaac stage/two-camera lifecycle mismatch')
    result = stream_progress(stream, expected_backend=backend)
    if actual.get('backend') != backend or actual.get('streamRenderProductCount') != 2:
        raise RuntimeError('Actual render products/backend do not match the configured pair')
    counts = actual.get('frameCounts')
    if not isinstance(counts, dict) or set(counts) != set(CAMERA_IDS) or any(type(v) is not int or v < 1 for v in counts.values()):
        raise RuntimeError('Actual camera delivery counters are unavailable')
    if backend == 'native':
        # Native Kit exposes handoff counters, not its internal encoder queue.
        # Do not recycle the software one-frame bound as a native claim.
        native_stream = {**stream, 'streams': actual.get('nativeStreams') or {}}
        result = stream_progress(native_stream, expected_backend=backend)
        if actual.get('pendingFrames') is not None or actual.get('maximumQueuedFramesPerCamera') is not None:
            raise RuntimeError('Native encoder queue bounds must remain explicitly unavailable')
    else:
        pending = actual.get('pendingFrames')
        if (not isinstance(pending, dict) or set(pending) != set(CAMERA_IDS)
                or any(type(v) is not int or not 0 <= v <= 1 for v in pending.values())
                or actual.get('maximumQueuedFramesPerCamera') != 1):
            raise RuntimeError('Software encoder exceeded its one-frame queue or its queue is unavailable')
    return {**result, 'frameCounts': counts}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=1200)
    args = parser.parse_args()
    if not 60 <= args.seconds <= 3600:
        parser.error('Use a bounded 60–3600 second run')
    args.output.mkdir(parents=True, exist_ok=False)
    backend = configured_backend()
    policy_file = CITY / 'config/vss_runtime_policy.json'
    memory_floor = json.loads(policy_file.read_text()).get('isaacAvailableMemoryStopGiB', 23) if policy_file.exists() else 23
    start = time.monotonic()
    windows = {name: deque() for name in ('cam_SW', 'cam_NE')}
    minimum_fps = {name: None for name in windows}
    previous_sim = None
    previous_generation = None
    previous_counts = None
    minimum_memory = minimum_disk = None
    error = None
    count = 0
    def interrupted(*_):
        raise RuntimeError('Monitor deliberately interrupted')
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, interrupted)
    try:
        with (args.output / 'samples.ndjson').open('w', buffering=1) as handle:
            while time.monotonic() - start < args.seconds:
                now = time.monotonic()
                state = bridge()
                actual = script('scripts/rtsp/check_vss_runtime.py', CHECK_NATIVE=count == 0)['result']
                stream = state.get('streams') or {}
                recordings = {source['id']: json_request('http://127.0.0.1:7782/api/vision/live-capture?streamId=' +
                    source['id'] + '&lookbackSeconds=5') for source in sources()}
                if not all(row.get('recordingStatus') == 'on' and row.get('questionReady') is True for row in recordings.values()):
                    raise RuntimeError('Current five-second recorded evidence is unavailable')
                mem = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
                available = int(mem['MemAvailable'].split()[0]) / 1024**2
                disk = shutil.disk_usage(args.output).free / 1024**3
                minimum_memory = min(minimum_memory or available, available)
                minimum_disk = min(minimum_disk or disk, disk)
                delivery = delivery_sample(state, actual, backend)
                channels = delivery['channels']
                if previous_generation is not None and stream.get('generation') != previous_generation:
                    raise RuntimeError('The stream generation changed during qualification')
                previous_generation = stream.get('generation')
                counts = delivery['frameCounts']
                if previous_counts is not None and any(counts[name] < previous_counts[name] for name in windows):
                    raise RuntimeError('A camera delivery counter went backward')
                previous_counts = counts
                if (memory_floor is not None and available < memory_floor) or disk < 14:
                    raise RuntimeError('Isaac memory/disk admission floor crossed')
                if previous_sim is not None and state['simTime'] <= previous_sim:
                    raise RuntimeError('Simulation time stopped or went backward')
                previous_sim = state['simTime']
                fps = {}
                for name in channels:
                    window = windows[name]
                    window.append((now, counts[name]))
                    while len(window) > 1 and now - window[1][0] >= 30:
                        window.popleft()
                    if now - window[0][0] >= 25:
                        value = (counts[name] - window[0][1]) / (now - window[0][0])
                        minimum_fps[name] = min(minimum_fps[name] or value, value)
                        fps[name] = value
                        if value < 5:
                            raise RuntimeError('Camera delivery below the declared 5 FPS minimum')
                count += 1
                handle.write(json.dumps({'at': datetime.now(UTC).isoformat(), 'elapsedSeconds': now-start,
                    'availableGiB': available, 'diskFreeGiB': disk, 'simTime': state['simTime'],
                    'streamGeneration': stream['generation'], 'cameraCount': stream['n_cameras'],
                    'actualRenderProductsAndQueues': actual,
                    'recordings': recordings,
                    'backend': backend, 'counterBasis': delivery['counterBasis'],
                    'frameCounts': counts, 'queueBoundStatus': delivery['queueBoundStatus'],
                    'streams': {name: {k: row.get(k) for k in (
                        ('pushed', 'frames', 'attached', 'server', 'failed', 'first_error', 'swizzle_error')
                        if backend == 'native' else ('frame_id', 'queued', 'dropped', 'encoderAlive', 'error'))}
                        for name, row in channels.items()}, 'rollingFps': fps}) + '\n')
                time.sleep(min(5, max(0, args.seconds - (time.monotonic() - start))))
            if any(value is None for value in minimum_fps.values()):
                raise RuntimeError('Insufficient camera samples to verify the rolling delivery rate')
    except Exception as exc:
        error = str(exc)
    result = {'passed': error is None, 'failure': error, 'requestedSeconds': args.seconds,
        'wallSeconds': time.monotonic()-start, 'samples': count, 'minimumAvailableGiB': minimum_memory,
        'minimumDiskFreeGiB': minimum_disk, 'minimumRollingFps': minimum_fps,
        'criteria': {'twoStreamRenderProducts': True, 'backend': backend,
                     'memoryFloorGiB': memory_floor, 'diskFloorGiB': 14, 'minimumCameraFps': 5,
                     'counterBasis': 'native-server-handoffs' if backend == 'native' else 'software-encoded-frames',
                     'maximumQueuedFramesPerCamera': None if backend == 'native' else 1,
                     'queueBoundStatus': 'unavailable-native-api' if backend == 'native' else 'bounded-software-queue'},
        'sourceSha256': SOURCE_SHA256,
        'scope': 'Actual simulator lifecycle and writer progress plus recorded footage; native encoder queues are unavailable. Not cross-camera identity accuracy or decoded inference throughput.'}
    (args.output / 'receipt.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2), flush=True)
    raise SystemExit(0 if result['passed'] else 1)


if __name__ == '__main__':
    main()
