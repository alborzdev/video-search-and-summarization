#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Retain encoded camera footage plus a separate read-only evaluation reference.

The existing capture tool performs H264 copy only. Simulator poses are never
sent to a detector, tracker, gateway or UI. No scene or runtime changes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time
import urllib.request

from capture_mv3dt_pair import SAFE
from isaac_workspace import runtime_root

ROOT = Path(__file__).resolve().parents[2]


def read_reference(runtime):
    payload = dict(action='script', path='scripts/tools/inspect_workspace.py', defines={'TRACKING_REFERENCE': True})
    request = urllib.request.Request('http://127.0.0.1:8766/control', data=json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json',
                 'X-City-Token': (runtime/'logs/vss-integration/bridge-token').read_text().strip()})
    with urllib.request.urlopen(request, timeout=3) as response:
        result = json.load(response)
    if result.get('ok') is not True:
        raise RuntimeError('Simulator read-only diagnostic failed')
    reference = result['data']['result']['trackingReference']
    if (reference['errors'] or reference['readOnly'] is not True or not reference['playing']
            or reference['scenario']['active'] or reference['scenario']['state'] != 'idle'
            or any(obj.get('controllerToActualErrorM', 0) > 1e-5 for obj in reference['objects'])):
        raise RuntimeError('Reference is not an unstaged, playing, actual-pose sample')
    return reference


def capture(name, seconds):
    if not SAFE.fullmatch(name) or not 30 <= seconds <= 180:
        raise ValueError('Use a unique plain capture name and 30..180 seconds')
    destination = ROOT/'.spark/city/runtime'/name
    destination.mkdir()
    runtime = runtime_root()
    profile_path = ROOT/'.spark/city/state/native/mv3dt-demo/active.json'
    profile_bytes = profile_path.read_bytes()
    profile = json.loads(profile_bytes)
    tuning_path = ROOT/'.spark/city/state/runtime-tuning.json'
    tuning_bytes = tuning_path.read_bytes()
    process_args = json.loads(subprocess.check_output(['docker', 'inspect', 'vss-city-detector', '--format', '{{json .Args}}']))
    inputs = [process_args[index+1] for index, value in enumerate(process_args) if value == '--source']
    if len(inputs) != 2 or [value.split('=', 1)[0] for value in inputs] != profile['cameraOrder']:
        raise RuntimeError('Running source order differs from pinned camera profile')
    command = ['docker', 'run', '--rm', '--name', 'vss-city-reference-copy', '--runtime', 'runc',
        '--network', 'host', '--cpus', '2', '--memory', '1g', '--memory-swap', '1g', '--user', '1000:1000',
        '-e', 'NVIDIA_VISIBLE_DEVICES=void', '-v', str(ROOT)+':/work:rw', '--entrypoint', '/usr/bin/python3',
        profile['imageId'], '/work/tools/smart-city/capture_mv3dt_pair.py', '--name', name, '--seconds', str(seconds)]
    for value in inputs:
        command.extend(['--source', value])
    manifest = dict(schemaVersion='city.tracking-reference-capture.v1', result='running', name=name,
        referenceUse='Offline evaluation only. Actual vehicle USD transforms and native person-agent translations; exposure delay is unmeasured.',
        nativeProfileSha256=hashlib.sha256(profile_bytes).hexdigest(), startedAtNs=str(time.time_ns()),
        runtimeTuningSha256=hashlib.sha256(tuning_bytes).hexdigest(),
        workerArgsSha256=hashlib.sha256(json.dumps(process_args).encode()).hexdigest(),
        cameraOrder=profile['cameraOrder'], command=command)
    initial_epoch = None
    references = 0
    with (destination/'copy.log').open('x') as log, (destination/'reference.ndjson').open('x') as output:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        start = time.monotonic()
        try:
            while process.poll() is None:
                iteration = time.monotonic()
                if iteration-start > seconds+30:
                    raise RuntimeError('Encoded-copy deadline exceeded')
                sample = read_reference(runtime)
                epoch = tuple(sample[key] for key in ('stageId', 'vehicleGeneration', 'trafficGeneration', 'peopleGeneration'))
                if initial_epoch is not None and epoch != initial_epoch:
                    raise RuntimeError('Reference actor/stage generation changed')
                initial_epoch = epoch
                output.write(json.dumps(sample)+'\n')
                output.flush()
                references += 1
                time.sleep(max(0, 1/3-(time.monotonic()-iteration)))
            if process.returncode:
                raise RuntimeError('Encoded copy failed; inspect copy.log')
            final = read_reference(runtime)
            output.write(json.dumps(final)+'\n')
            references += 1
            if profile_path.read_bytes() != profile_bytes:
                raise RuntimeError('Native profile changed during capture')
            if tuning_path.read_bytes() != tuning_bytes:
                raise RuntimeError('Runtime tuning changed during capture')
            manifest.update(result='complete', referenceSamples=references, referenceEpoch=initial_epoch,
                finishedAtNs=str(time.time_ns()), mediaDirectory=str(ROOT/'.spark/city/media'/name))
        except Exception as error:
            manifest.update(result='failed', error=str(error), referenceSamples=references)
            raise
        finally:
            if process.poll() is None:
                subprocess.run(['docker', 'stop', '-t', '3', 'vss-city-reference-copy'], capture_output=True)
                process.wait(timeout=8)
            manifest['referenceSha256'] = hashlib.sha256((destination/'reference.ndjson').read_bytes()).hexdigest()
            (destination/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name', required=True)
    parser.add_argument('--seconds', type=int, default=60)
    options = parser.parse_args()
    capture(options.name, options.seconds)
