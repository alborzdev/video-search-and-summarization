#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run one bounded native MV3DT comparison, restoring the live detector.

Inference sees only encoded files, static calibration/priors and model weights.
Reference traces and scores are not mounted or sent to the worker.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import statistics
import subprocess
import time
import urllib.request
import uuid

import yaml

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT/'.spark/city/state'
GOAL = ROOT/'.spark/city/runtime/tracking-quality-20261027'


def detections(action=None):
    request = urllib.request.Request('http://127.0.0.1:9190/api/v1/detections',
        data=None if action is None else json.dumps(dict(action=action)).encode(), headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.load(response)


def available_gib():
    return int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:')))/2**20


def run(name, cohort, image, variant, *, frames=0, unpaced=False, engine_cache=None):
    if not name.replace('-', '').isalnum() or cohort not in ('train', 'holdout'):
        raise ValueError('Use a unique plain run name and train/holdout cohort')
    path = GOAL/'runs'/name
    path.mkdir(parents=True)
    bus_area = variant == 'family-pose-moderate-bus-area'
    balanced = variant == 'family-pose-balanced'
    mux_pairing = variant == 'family-pose-moderate-mux50'
    selected_variant = 'family-pose-moderate' if bus_area or balanced or mux_pairing else variant
    manifest = json.loads((ROOT/f'.spark/city/runtime/tracking-quality-{cohort}-20261027/manifest.json').read_text())
    if manifest['result'] != 'complete':
        raise ValueError('Reference capture did not complete')
    baseline_bytes = (GOAL/'active.before.json').read_bytes()
    if hashlib.sha256(baseline_bytes).hexdigest() != manifest['nativeProfileSha256']:
        raise ValueError('Cohort and frozen pre-change profile differ')
    profile = json.loads(baseline_bytes)
    for relative, expected in profile['fileHashes'].items():
        if hashlib.sha256((STATE/relative).read_bytes()).hexdigest() != expected:
            raise ValueError('Frozen baseline configuration changed')
    original = STATE/Path(profile['trackerConfig']).parent
    tracker = yaml.safe_load((STATE/profile['trackerConfig']).read_text())
    package = json.loads((original/'package.json').read_text())
    for index in range(2):
        camera = yaml.safe_load((original/f'camera-{index}.yml').read_text())
        if variant in ('footprint-area', 'bus-area') or bus_area:
            for model in camera['modelInfo']:
                if model['classID'] == 0 or ((variant == 'bus-area' or bus_area) and model['classID'] != 4):
                    continue
                geometry = package['classGeometry'][model['classID']]
                model['radius'] = statistics.median(math.sqrt(dimensions[0]*dimensions[1]/math.pi) for _, dimensions in geometry['measurements'])
        (path/f'camera-{index}.yml').write_text(yaml.safe_dump(camera))
    if selected_variant == 'class-agnostic':
        tracker['BaseConfig']['checkClassMatch'] = 0
    elif selected_variant == 'fusion-15':
        tracker['MultiViewAssociator'].update(minPeerTrackletMatchScore=.4, maxPeerToPredDistance4Fusion=1.5)
    elif selected_variant in ('person-pose', 'family-pose', 'family-pose-two', 'family-pose-confident', 'family-pose-moderate', 'family-pose-moderate-match15'):
        shutil.copyfile(ROOT/'.spark/city/models/bodypose3dnet/bodypose3dnet_accuracy.onnx', path/'bodypose.onnx')
        tracker['PoseEstimator'] = dict(poseEstimatorType=1, useVPICropScaler=1, batchSize=1, workspaceSize=128,
            inferDims=[3, 256, 192], networkMode=1, inputOrder=0, colorFormat=0,
            offsets=[123.675, 116.28, 103.53], netScaleFactor=.00392156,
            onnxFile='/trial/bodypose.onnx', modelEngineFile='/trial/bodypose.onnx_b1_gpu0_fp16.engine',
            poseInferenceInterval=-1, operateOnClassIds=[0])
    elif selected_variant == 'reference-reid':
        shutil.copyfile(ROOT/'.spark/city/models/reidentificationnet/resnet50_market1501_aicity156.onnx', path/'reid.onnx')
        tracker['ReID'].update(reidType=2, batchSize=32, workspaceSize=128, useVPICropScaler=1,
            onnxFile='/trial/reid.onnx', modelEngineFile='/trial/reid.onnx_b32_gpu0_fp16.engine',
            minVisibility4GalleryUpdate=.6)
    elif selected_variant not in ('baseline', 'footprint-area', 'bus-area', 'car-truck-family'):
        raise ValueError('Unknown declared comparison variant')
    if engine_cache is not None:
        if selected_variant not in ('person-pose', 'family-pose', 'family-pose-two', 'family-pose-confident', 'family-pose-moderate', 'family-pose-moderate-match15', 'reference-reid'):
            raise ValueError('Engine cache requires an explicit model trial')
        engine_cache = Path(engine_cache).resolve()
        if not engine_cache.is_file() or not 0 < engine_cache.stat().st_size < 1024**3:
            raise ValueError('Expected a bounded previously built trial engine')
        module = 'ReID' if variant == 'reference-reid' else 'PoseEstimator'
        shutil.copyfile(engine_cache, path/Path(tracker[module]['modelEngineFile']).name)
    if selected_variant == 'family-pose-two':
        tracker['MultiViewAssociator']['minCommonFrames4MatchScore'] = 2
    if selected_variant == 'family-pose-confident':
        tracker['ObjectModelProjection']['minPoseConfidence'] = .925
    if selected_variant in ('family-pose-moderate', 'family-pose-moderate-match15'):
        tracker['ObjectModelProjection']['minPoseConfidence'] = .75
    if selected_variant == 'family-pose-moderate-match15':
        # Test ID matching separately from the 1m measurement-fusion inlier
        # gate. Pose refinement is already qualified in the preceding cohort.
        tracker['MultiViewAssociator']['minPeerTrackletMatchScore'] = .4
    if balanced:
        tracker['MultiViewAssociator'].update(minCommonFrames4MatchScore=5, minPeerTrackletMatchScore=.4, maxPeerToPredDistance4Fusion=1.5)
    tracker['ObjectModelProjection']['cameraModelFilepath'] = [f'/trial/camera-{i}.yml' for i in range(2)]
    topics = [f'127.0.0.1:18883;city-quality/{uuid.uuid4().hex}/{i}' for i in range(2)]
    (path/'pub-sub.yml').write_text(yaml.safe_dump(dict(pubBrokerTopicStr=topics, subPeerBrokerTopicStrs=[[topics[1]], [topics[0]]])))
    tracker['Communicator']['pubSubInfoConfigPath'] = '/trial/pub-sub.yml'
    (path/'tracker.yml').write_text(yaml.safe_dump(tracker, sort_keys=False))
    shutil.copyfile(STATE/'native/analytics.ini', path/'analytics.ini')
    model = json.loads((GOAL/'model.before.json').read_text())
    config = next((STATE/'model-config').glob('large-4434b077b360'))
    command = ['docker', 'run', '--rm', '--name', 'vss-city-quality-trial', '--gpus', 'all', '--runtime', 'nvidia',
        '--network', 'host', '--memory', '4g', '--memory-swap', '4g', '--cpus', '4',
        '-v', str(STATE)+':/state:ro', '-v', str(ROOT/'.spark/city/models')+':/models:ro',
        '-v', str(ROOT/f'.spark/city/media/tracking-quality-{cohort}-20261027')+':/media:ro',
        '-v', str(path)+':/trial:rw', image]
    for source in profile['cameraOrder']:
        command.extend(['--source', source+'=file:///media/'+source+'.mkv'])
    command.extend(['--site-id', profile['siteId'], '--output', '/trial/observations.ndjson', '--frames', str(frames),
        '--width', '960', '--height', '540', '--mux-timeout-us', '50000' if mux_pairing else '10000', '--cpu-decode',
        '--recorded-native-sei-clock', '--tracker-diagnostics', '--config-dir', '/state/'+str(config.relative_to(STATE)),
        '--analytics-config', '/trial/analytics.ini', '--model-revision', model['modelRevision'],
        '--tracker-mode', 'mv3dt-demo', '--tracker-config', '/trial/tracker.yml',
        '--tracker-calibration-revision', next(iter(profile['cameraCalibrations'].values())), '--tracking-architecture', 'mv3dt-native-v1'])
    if unpaced:
        command.append('--unpaced')
    if selected_variant in ('car-truck-family', 'family-pose', 'family-pose-two', 'family-pose-confident', 'family-pose-moderate', 'family-pose-moderate-match15'):
        command.append('--native-car-truck-family')
    receipt = dict(schemaVersion='city.tracking-trial.v1', variant=variant, cohort=cohort, image=image,
        command=command, unpaced=unpaced, result='running', startedNs=str(time.time_ns()))
    receipt['baselineProfileSha256'] = hashlib.sha256(baseline_bytes).hexdigest()
    receipt['cohortManifestSha256'] = hashlib.sha256((ROOT/f'.spark/city/runtime/tracking-quality-{cohort}-20261027/manifest.json').read_bytes()).hexdigest()
    receipt['launcherSha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    receipt['modelInputsSha256'] = {file.name: hashlib.sha256(file.read_bytes()).hexdigest()
        for file in path.iterdir() if file.suffix in ('.onnx', '.engine')}
    reserve = json.loads((ROOT/'.spark/settings.json').read_text())['reserve_gib']
    minimum = available_gib()
    if minimum < reserve or subprocess.run(['systemctl', '--user', 'is-active', '--quiet', 'vss-spark-guard.service']).returncode:
        raise RuntimeError('Saved reserve and active memory guard required')
    before = detections()
    restore = before['state'] == 'running'
    if restore:
        receipt['pause'] = detections('stop')
    process = None
    try:
        started = time.monotonic()
        with (path/'run.log').open('x') as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
            while process.poll() is None:
                minimum = min(minimum, available_gib())
                if minimum < reserve+4 or time.monotonic()-started > 125:
                    raise RuntimeError('Replay resource/deadline bound exceeded')
                if subprocess.run(['systemctl', '--user', 'is-active', '--quiet', 'vss-spark-guard.service']).returncode:
                    raise RuntimeError('Memory guard became inactive')
                time.sleep(.5)
            if process.returncode:
                raise RuntimeError('Native replay failed; inspect run.log')
        receipt.update(result='complete', elapsedSeconds=time.monotonic()-started)
    except BaseException as error:
        receipt.update(result='failed', error=str(error))
        raise
    finally:
        if process and process.poll() is None:
            subprocess.run(['docker', 'stop', '-t', '3', 'vss-city-quality-trial'], capture_output=True)
            process.wait(timeout=8)
        restore_error = None
        if restore:
            try:
                receipt['restore'] = detections('start')
            except Exception as error:
                restore_error = error
                receipt.update(result='failed', restoreError=str(error))
        receipt.update(minimumAvailableGiB=minimum, finishedNs=str(time.time_ns()))
        receipt['configSha256'] = {file.name: hashlib.sha256(file.read_bytes()).hexdigest() for file in path.glob('*.yml')}
        (path/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
        if restore_error:
            raise RuntimeError('Live detector restoration failed; receipt retained') from restore_error
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name', required=True)
    parser.add_argument('--cohort', choices=('train', 'holdout'), default='train')
    parser.add_argument('--image', required=True)
    parser.add_argument('--variant', required=True)
    parser.add_argument('--frames', type=int, default=0)
    parser.add_argument('--unpaced', action='store_true')
    parser.add_argument('--engine-cache', type=Path)
    args = parser.parse_args()
    run(args.name, args.cohort, args.image, args.variant, frames=args.frames, unpaced=args.unpaced, engine_cache=args.engine_cache)
