#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run a bounded, isolated MV3DT experiment against retained paired footage.

Only encoded footage, detector assets and static calibration enter inference.
Reference actor traces stay outside the container. The current live detector is
restored even when an experiment fails. Nothing here promotes a configuration.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time
import uuid

import yaml

from replay_tracking_trial import ROOT, STATE, available_gib, detections

DEST = ROOT/'.spark/city/runtime/mv3dt-diagnostics-20261028'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def merge(base, changes):
    for key, value in changes.items():
        if isinstance(value, dict):
            merge(base.setdefault(key, {}), value)
        else:
            base[key] = value


def run(name, cohort, overrides, *, frames=0, image=None, extra_args=(), camera_radius=None, stock=False, reference_tracker=False, tensor_dump=False):
    if not name.replace('-', '').isalnum() or cohort not in ('train', 'holdout'):
        raise ValueError('A new plain run name and an existing cohort are required')
    path = DEST/'runs'/name
    path.mkdir(parents=True, exist_ok=False)
    profile_path = STATE/'native/mv3dt-demo/active.json'
    profile = json.loads(profile_path.read_text())
    image = subprocess.check_output(['docker', 'image', 'inspect', '--format', '{{.Id}}', image or profile['imageId']], text=True).strip()
    profile_sha = sha(profile_path)
    for relative, expected in profile['fileHashes'].items():
        if sha(STATE/relative) != expected:
            raise ValueError('Active static configuration pin changed')
    selected = STATE/Path(profile['trackerConfig']).parent
    tracker = yaml.safe_load((STATE/profile['trackerConfig']).read_text())
    if reference_tracker:
        tracker = yaml.safe_load((DEST/'reference/config_tracker.yml').read_text().replace('%YAML:1.0', ''))
        # The supplied pose model is human-only; retain that explicit class
        # scope when adapting the warehouse example to six-class traffic.
        tracker['PoseEstimator'].update(operateOnClassIds=[0], workspaceSize=128,
            onnxFile='/models/bodypose3dnet/bodypose3dnet_accuracy.onnx',
            modelEngineFile='/models/bodypose3dnet/bodypose3dnet_accuracy.onnx_b1_gpu0_fp16.engine')
    merge(tracker, overrides)
    for i in range(2):
        camera = yaml.safe_load((selected/f'camera-{i}.yml').read_text())
        for model in camera['modelInfo']:
            if camera_radius and str(model['classID']) in camera_radius:
                model['radius'] = camera_radius[str(model['classID'])]
        (path/f'camera-{i}.yml').write_text(yaml.safe_dump(camera))
    tracker['ObjectModelProjection']['cameraModelFilepath'] = [f'/trial/camera-{i}.yml' for i in range(2)]
    topics = [f'127.0.0.1:18883;city-diagnostics/{uuid.uuid4().hex}/{i}' for i in range(2)]
    (path/'pub-sub.yml').write_text(yaml.safe_dump(dict(pubBrokerTopicStr=topics, subPeerBrokerTopicStrs=[[topics[1]], [topics[0]]])))
    shutil.copyfile(selected/'mqtt.ini', path/'mqtt.ini')
    tracker['Communicator'].update(pubSubInfoConfigPath='/trial/pub-sub.yml', mqttProtoAdaptorConfigPath='/trial/mqtt.ini')
    (path/'tracker.yml').write_text(yaml.safe_dump(tracker, sort_keys=False))
    shutil.copyfile(STATE/'native/analytics.ini', path/'analytics.ini')
    original = json.loads((ROOT/f'.spark/city/runtime/tracking-quality-20261027/runs/moderate-{cohort}/receipt.json').read_text())
    command = copy.deepcopy(original['command'])
    command[command.index('vss-city-quality-trial')] = 'vss-city-diagnostics-trial'
    for index, value in enumerate(command):
        if value.endswith(':/trial:rw'):
            command[index] = str(path)+':/trial:rw'
    old_image = original['image']
    command[command.index(old_image)] = image or profile['imageId']
    command[command.index('--frames')+1] = str(frames)
    command.extend(extra_args)
    if tensor_dump:
        library = DEST/'build/libcity_preprocess_tensor_dump.so'
        if not library.is_file():
            raise ValueError('Build the diagnostic tensor-dump adapter first')
        index = command.index(image)
        command[index:index] = ['-v', str(library)+':/opt/city/libcity_preprocess.so:ro']
    if stock:
        for name_ in ('infer', 'tracker'):
            (path/f'{name_}-dump').mkdir()
        infer = (STATE/'model-config/large-4434b077b360/infer.ini').read_text()
        (path/'infer.ini').write_text(infer.replace('[property]', '[property]\ninput-tensor-from-meta=1', 1))
        shutil.copyfile(STATE/'model-config/large-4434b077b360/preprocess.ini', path/'preprocess.ini')
        # NVIDIA's unmodified sample application and tracker, with only the
        # documented custom-detector/source/static-calibration configuration.
        sections = ['[application]\nenable-perf-measurement=1\nperf-measurement-interval-sec=5\ngie-kitti-output-dir=/trial/infer-dump\nkitti-track-output-dir=/trial/tracker-dump']
        for i, source in enumerate(profile['cameraOrder']):
            sections.append(f'[source{i}]\nenable=1\ntype=3\nuri=file:///media/{source}.mkv\ngpu-id=0\nvideo-format=RGBA\nnvbuf-memory-type=2')
        sections.extend(['[streammux]\nwidth=960\nheight=540\nbatch-size=2\nbatched-push-timeout=-1\nlive-source=0\nnvbuf-memory-type=2\nattach-sys-ts-as-ntp=0',
            '[pre-process]\nenable=1\nconfig-file=/trial/preprocess.ini',
            '[primary-gie]\nenable=1\ngie-unique-id=1\nbatch-size=2\ninput-tensor-meta=1\nconfig-file=/trial/infer.ini',
            '[tracker]\nenable=1\ntracker-width=640\ntracker-height=384\ngpu-id=0\nll-lib-file=/opt/nvidia/deepstream/deepstream/lib/libnvds_nvmultiobjecttracker.so\nll-config-file=/trial/tracker.yml',
            '[osd]\nenable=0', '[tiled-display]\nenable=1\nrows=1\ncolumns=2\nwidth=960\nheight=540\nnvbuf-memory-type=2',
            '[sink0]\nenable=1\ntype=1\nsync=1\nqos=0', '[tests]\nfile-loop=0'])
        (path/'app.txt').write_text('\n\n'.join(sections)+'\n')
        image_index = command.index(image or profile['imageId'])
        debug_library = DEST/'build/libcity_preprocess_debug_v2.so'
        mounts = ['-v', str(debug_library)+':/opt/city/libcity_preprocess.so:ro'] if debug_library.exists() and not tensor_dump else []
        command = command[:image_index]+mounts+['-e', 'GST_DEBUG=nvinfer:6,nvdspreprocess:6',
            '-e', 'GST_PLUGIN_FEATURE_RANK=nvv4l2decoder:NONE,avdec_h264:MAX',
            '--entrypoint', '/opt/nvidia/nvidia_entrypoint.sh', command[image_index],
            '/usr/bin/deepstream-test5-app', '-c', '/trial/app.txt']
    receipt = dict(schemaVersion='city.mv3dt-diagnostics.v1', result='running', cohort=cohort,
        overrides=overrides, cameraRadius=camera_radius, stockApplication=stock, nvidiaReferenceTracker=reference_tracker,
        diagnosticTensorDump=tensor_dump,
        command=command, imageId=image, startedNs=str(time.time_ns()),
        activeProfileSha256=profile_sha, launcherSha256=sha(Path(__file__)),
        sourceTrialReceiptSha256=sha(ROOT/f'.spark/city/runtime/tracking-quality-20261027/runs/moderate-{cohort}/receipt.json'))
    before = detections()
    restore = before['state'] == 'running'
    process = None
    minimum = available_gib()
    receipt['beforePauseAvailableGiB'] = minimum
    try:
        if restore:
            receipt['pause'] = detections('stop')
        minimum = available_gib()
        reserve = json.loads((ROOT/'.spark/settings.json').read_text())['reserve_gib']
        receipt['resourcePolicy'] = dict(savedReserveGiB=reserve, startupHeadroomGiB=4, runtimeEarlyStopHeadroomGiB=1,
            guardRequired=True, containerMemoryGiB=4)
        if available_gib() < reserve:
            raise RuntimeError('Available memory is below the saved reserve')
        started = time.monotonic()
        progress_size = 0
        progress_at = started
        with (path/'run.log').open('x') as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
            while process.poll() is None:
                minimum = min(minimum, available_gib())
                guard = subprocess.run(['systemctl', '--user', 'is-active', '--quiet', 'vss-spark-guard.service']).returncode
                # Admission headroom is required before allocating the model.
                # During inference retain the operator's reserve, with an
                # extra GiB to stop this probe before the independent guard.
                if minimum < reserve+1 or guard or time.monotonic()-started > 125:
                    raise RuntimeError('Memory guard, reserve headroom or experiment deadline exceeded')
                output = path/'observations.ndjson'
                if stock or output.exists():
                    size = (sum(1 for _ in (path/'infer-dump').glob('*.txt')) + sum(1 for _ in (path/'tracker-dump').glob('*.txt'))
                            if stock else output.stat().st_size)
                    if size != progress_size:
                        progress_size, progress_at = size, time.monotonic()
                    if time.monotonic()-progress_at > 15:
                        raise RuntimeError('Native output stalled for 15 seconds')
                time.sleep(.5)
            if process.returncode:
                raise RuntimeError('Native experiment failed; inspect run.log')
        receipt.update(result='complete', elapsedSeconds=time.monotonic()-started)
        if stock:
            receipt['positiveControlPassed'] = any(p.stat().st_size for p in (path/'infer-dump').glob('*.txt'))
    except BaseException as error:
        receipt.update(result='failed', error=str(error))
        raise
    finally:
        if process and process.poll() is None:
            subprocess.run(['docker', 'stop', '-t', '3', 'vss-city-diagnostics-trial'], capture_output=True)
            process.wait(timeout=8)
        try:
            if sha(profile_path) != profile_sha:
                raise RuntimeError('Active profile changed during isolated experiment')
            if restore:
                receipt['restore'] = detections('start')
        except Exception as error:
            receipt.update(result='failed', restoreError=str(error))
            raise
        finally:
            receipt.update(minimumAvailableGiB=minimum, finishedNs=str(time.time_ns()),
                configSha256={p.name: sha(p) for p in path.glob('*.yml')})
            (path/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(dict(path=str(path), result=receipt['result'], elapsedSeconds=receipt['elapsedSeconds'], minimumAvailableGiB=minimum)))
    return path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name', required=True)
    parser.add_argument('--cohort', choices=('train', 'holdout'), default='train')
    parser.add_argument('--overrides', type=json.loads, default={})
    parser.add_argument('--camera-radius', type=json.loads)
    parser.add_argument('--frames', type=int, default=0)
    parser.add_argument('--image')
    parser.add_argument('--extra-arg', action='append', default=[])
    parser.add_argument('--stock', action='store_true')
    parser.add_argument('--reference-tracker', action='store_true')
    parser.add_argument('--tensor-dump', action='store_true')
    args = parser.parse_args()
    run(args.name, args.cohort, args.overrides, frames=args.frames, image=args.image,
        extra_args=args.extra_arg, camera_radius=args.camera_radius, stock=args.stock, reference_tracker=args.reference_tracker,
        tensor_dump=args.tensor_dump)
