#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Bounded, explicitly diagnostic MV3DT run. Does not publish production tracks."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import time
from urllib.parse import unquote, urlsplit
import yaml

import manage

ROOT = Path(__file__).resolve().parents[2]
NAME = 'vss-city-mv3dt-probe'
CANDIDATES = ('baseline', 'sv3dt-only', 'mv3dt-no-see-through')
CLASSES = ('person', 'bicycle', 'car', 'motorcycle', 'bus', 'truck')


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def replay_provenance(root: Path, sources: list[str], verification: str | None = None) -> dict:
    """Pin immutable media evidence without interpreting or repairing its clock."""
    media = (root / '.spark/city/media').resolve()
    inputs = []
    for source in sources:
        source_id, uri = source.split('=', 1)
        parsed = urlsplit(uri)
        if parsed.scheme != 'file':
            continue
        path = Path(unquote(parsed.path))
        if parsed.netloc or parsed.query or parsed.fragment or not path.is_relative_to('/media') or '..' in path.parts:
            raise ValueError('Recorded probe inputs must be plain approved /media file URIs')
        local = (media / path.relative_to('/media')).resolve()
        if not local.is_relative_to(media) or not local.is_file():
            raise ValueError('Recorded probe input is outside the saved media tree or missing')
        before = local.stat()
        sha = digest(local)
        after = local.stat()
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise ValueError('Recorded probe input changed while hashing')
        inputs.append({'sourceId': source_id, 'containerUri': uri, 'fileSha256': sha})
    result = {'replayInputs': inputs}
    if verification:
        path = Path(verification).resolve()
        if len(inputs) != len(sources) or len(inputs) != 2:
            raise ValueError('Recorded clock verification requires two recorded inputs')
        if not path.is_relative_to(media) or not path.is_file():
            raise ValueError('Recorded clock verification must be a saved file in the media tree')
        result['recordedClockVerificationSha256'] = digest(path)
        result['recordedClockVerificationPath'] = str(path)
        result['recordedClockVerificationNote'] = 'Pinned evidence only; evaluator validates file/sidecar mapping. No clock is rewritten or promoted by this launcher.'
    return result


def static_geometry(package: dict, directory: Path, camera_paths: list[str], tracker: dict) -> list[dict]:
    """Require the saved per-class constants; never consume actor poses or labels."""
    geometry = package.get('classGeometry', [])
    if len(geometry) != len(CLASSES) or {row.get('class') for row in geometry} != set(CLASSES):
        raise ValueError('All six saved static class models are required')
    if tracker['ObjectModelProjection'].get('objectModelType') != 0:
        raise ValueError('Bounded candidates preserve the saved cylinder model')
    by_class = {row['class']: row for row in geometry}
    expected = []
    for index, name in enumerate(CLASSES):
        row = by_class[name]
        dimensions = [row.get('heightM'), row.get('radiusM')]
        if row.get('shape') != 'cylinder' or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in dimensions):
            raise ValueError('Static cylinder dimensions must be finite positive metres')
        expected.append({'classID': index, 'height': dimensions[0], 'radius': dimensions[1]})
    for path in camera_paths:
        models = yaml.safe_load((directory / Path(path).name).read_text()).get('modelInfo')
        if not isinstance(models, list) or len(models) != len(expected) or any(
            not isinstance(actual, dict) or actual.get('classID') != wanted['classID'] or any(
                isinstance(actual.get(key), bool) or not isinstance(actual.get(key), (int, float)) or
                not math.isclose(actual[key], wanted[key], rel_tol=1e-12, abs_tol=0)
                for key in ('height', 'radius'))
            for actual, wanted in zip(models, expected)
        ):
            raise ValueError('Camera class model differs from the saved static geometry')
    return expected


def prepare_candidate(directory: Path, run: Path, candidate: str, state_root: Path) -> dict:
    """CPU-only snapshot; never overwrite a failed probe or active profile."""
    if candidate not in CANDIDATES:
        raise ValueError('Unknown bounded diagnostic candidate')
    relative = run.resolve().relative_to(state_root.resolve())
    container = '/state/' + relative.as_posix()
    package = json.loads((directory / 'package.json').read_text())
    cameras = package['cameras']
    if len(cameras) != 2 or len({(c['width'], c['height']) for c in cameras}) != 1:
        raise ValueError('Candidate requires two equal-resolution calibrated camera inputs')
    tracker = yaml.safe_load((directory / 'tracker-mv3dt.experimental.yml').read_text())
    originals = ['package.json', 'manifest.json', 'promotion-gates.json', 'mqtt.ini', 'pub-sub.yml', 'tracker-mv3dt.experimental.yml']
    camera_paths = tracker['ObjectModelProjection']['cameraModelFilepath']
    if not isinstance(camera_paths, list) or len(camera_paths) != 2:
        raise ValueError('Candidate requires an explicit ordered pair of camera files')
    originals.extend(Path(path).name for path in camera_paths)
    if len(set(originals)) != len(originals) or any(not (directory / name).is_file() for name in originals):
        raise ValueError('Candidate calibration/config snapshot is incomplete or ambiguous')
    models = static_geometry(package, directory, camera_paths, tracker)
    hashes = {name: digest(directory / name) for name in originals}
    run.mkdir(parents=True, exist_ok=False)
    for name in originals:
        shutil.copyfile(directory / name, run / name)
    tracker['ObjectModelProjection']['cameraModelFilepath'] = [f'{container}/{Path(path).name}' for path in camera_paths]
    changes = []
    if candidate == 'sv3dt-only':
        tracker.pop('MultiViewAssociator', None)
        tracker.pop('Communicator', None)
        changes.append('Remove peer association and MQTT; retain monocular3D estimation and local re-association.')
    else:
        communicator = tracker['Communicator']
        communicator['pubSubInfoConfigPath'] = f'{container}/pub-sub.yml'
        communicator['mqttProtoAdaptorConfigPath'] = f'{container}/mqtt.ini'
        if candidate == 'mv3dt-no-see-through':
            tracker['MultiViewAssociator']['enableSeeThrough'] = 0
            changes.append('Disable peer-created see-through targets; retain ordinary peer association, correction and fusion.')
        topology = yaml.safe_load((run / 'pub-sub.yml').read_text())
        def isolated(value):
            if isinstance(value, str):
                broker, topic = value.split(';', 1)
                return f'{broker};{topic}/probe/{run.name}'
            if isinstance(value, list):
                return [isolated(item) for item in value]
            raise ValueError('Expected ordered MQTT topic lists')
        topology = {key: isolated(topology[key]) for key in ('pubBrokerTopicStr', 'subPeerBrokerTopicStrs')}
        (run / 'pub-sub.yml').write_text(yaml.safe_dump(topology, sort_keys=False))
    (run / 'tracker-mv3dt.experimental.yml').write_text(yaml.safe_dump(tracker, sort_keys=False))
    receipt = {'candidate': candidate, 'preparedOnly': True, 'diagnosticOnly': True, 'runtimeQualified': False,
        'globalOutputEnabled': False, 'sourceProfile': str(directory), 'inputHashes': hashes,
        'changes': changes, 'trackerInputResolution': [640, 384],
        'trackerConfigContainerPath': f'{container}/tracker-mv3dt.experimental.yml',
        'cameraOrder': [camera['sourceId'] for camera in cameras],
        'staticClassModels': models,
        'geometryPolicy': 'Frozen saved class dimensions only; no runtime actor pose, trajectory, label or per-instance dimensions are read by the probe.',
        'clockRequirement': 'Paired files must preserve their common source PTS; SDK uses NTP when present, otherwise buf_pts. HTTP output clock assignment occurs after tracker.',
        'identityScope': 'camera-local-control' if candidate == 'sv3dt-only' else 'unqualified-peer-diagnostic',
        'preparedHashes': {name: digest(run / name) for name in originals}}
    (run / 'candidate.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


def volume_args(root: Path) -> list[str]:
    return ['-v', str(root / '.spark/city/models') + ':/models:ro',
            '-v', str(root / '.spark/city/media') + ':/media:ro',
            '-v', str(root / '.spark/city/state') + ':/state']


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', action='append', default=[])
    parser.add_argument('--seconds', type=int, default=180)
    parser.add_argument('--frames', type=int, default=2200)
    parser.add_argument('--profile', choices=('mv3dt', 'mv3dt-person-plane', 'mv3dt-person-pose'), default='mv3dt')
    parser.add_argument('--candidate', choices=CANDIDATES, default='baseline')
    parser.add_argument('--prepare-only', action='store_true', help='Write isolated candidate configs without Docker, GPU, or runtime changes')
    parser.add_argument('--image', default='vss-city-perception:isaac-mv3dt-dev')
    parser.add_argument('--recorded-clock-verification', help='Pin a saved media-tree verification receipt; does not change tracker clocks')
    args = parser.parse_args()
    if not 30 <= args.seconds <= 600 or not 1 <= args.frames <= 10000 or (not args.prepare_only and len(args.source) != 2):
        raise ValueError('Two sources and bounded duration/frame count required')
    directory = ROOT / '.spark/city/state/native' / args.profile
    package = json.loads((directory / 'package.json').read_text())
    if args.source and [value.split('=', 1)[0] for value in args.source] != [camera['sourceId'] for camera in package['cameras']]:
        raise ValueError('Source order differs from measured camera order')
    for source in args.source:
        if not manage.approved_uri(source.split('=', 1)[1], 'spark'):
            raise ValueError('Source is not an approved camera URI')
    replay = replay_provenance(ROOT, args.source, args.recorded_clock_verification)
    if not args.prepare_only:
        active = subprocess.run(['docker', 'ps', '--format', '{{.Names}}'], text=True, capture_output=True, check=True).stdout.splitlines()
        if any(name in active for name in (NAME, 'vss-city-detector')):
            raise RuntimeError('Pause the owned city pipeline; no parallel GPU probes')
        manage.ensure_headroom('spark')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    run = directory / ('probe-' + args.candidate + '-' + stamp)
    candidate = prepare_candidate(directory, run, args.candidate, ROOT / '.spark/city/state')
    if args.prepare_only:
        print(json.dumps({'directory': str(run), **candidate}, indent=2))
        return
    model = manage.city_model_module().config_for_launch(ROOT, 'spark')
    image = args.image
    image_id = subprocess.check_output(['docker', 'image', 'inspect', image, '--format', '{{.Id}}'], text=True).strip()
    command = ['docker', 'run', '--rm', '--name', NAME, '--runtime=nvidia', '--gpus', 'all', '--network=host',
               '--user=1000:1000', '--memory=8g', '--memory-swap=8g', '--cpus=6',
               '-e', 'NVIDIA_DRIVER_CAPABILITIES=compute,utility,video', '-e', 'XDG_CACHE_HOME=/tmp',
               *volume_args(ROOT), image]
    for source in args.source:
        command += ['--source', source]
    relative = run.relative_to(ROOT / '.spark/city/state')
    command += ['--site-id', package['siteId'], '--output', '/state/' + str(relative / 'observations.ndjson'),
                '--output-max-bytes', str(64 * 1024 ** 2), '--output-retained-files', '1',
                '--frames', str(args.frames), *model['nativeArgs'],
                '--tracker-config', candidate['trackerConfigContainerPath'],
                '--tracker-mode', 'mv3dt-diagnostic', '--tracker-calibration-revision', package['cameras'][0]['calibrationRevision'],
                '--mux-timeout-us', '10000', '--width', str(package['cameras'][0]['width']),
                '--height', str(package['cameras'][0]['height']), '--cpu-decode']
    (run / 'invocation.json').write_text(json.dumps({'command': command, 'imageId': image_id,
        'candidate': candidate, 'inputHashes': candidate['inputHashes'], **replay,
        'gates': json.loads((run / 'promotion-gates.json').read_text())}, indent=2) + '\n')
    start = time.monotonic()
    minimum = float('inf')
    reason = None
    process = None
    with (run / 'console.log').open('w') as log, (run / 'telemetry.ndjson').open('w', buffering=1) as telemetry:
        try:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
            while process.poll() is None:
                available = manage.available_gib()
                minimum = min(minimum, available)
                telemetry.write(json.dumps({'elapsedSeconds': time.monotonic() - start, 'availableGiB': available}) + '\n')
                manage.ensure_headroom('spark')
                observations = run / 'observations.ndjson'
                if time.monotonic() - start > 30 and (not observations.exists() or time.time() - observations.stat().st_mtime > 20):
                    reason = 'observation-progress-timeout'
                    break
                if time.monotonic() - start > args.seconds:
                    reason = 'bounded-duration-reached'
                    break
                time.sleep(1)
        except BaseException as exc:
            reason = type(exc).__name__ + ': ' + str(exc)
        finally:
            if process is not None and process.poll() is None:
                subprocess.run(['docker', 'stop', '-t', '5', NAME], timeout=15, capture_output=True)
                process.wait(timeout=15)
    receipt = {'completedWithoutRuntimeError': process is not None and process.returncode == 0 and reason is None,
               'runtimeQualified': False, 'globalOutputEnabled': False, 'diagnosticOnly': True,
               'exitCode': process.returncode if process else None, 'stopReason': reason,
               'wallSeconds': time.monotonic() - start, 'minimumAvailableGiB': minimum,
               'imageId': image_id, 'observationsFile': str(run / 'observations.ndjson')}
    (run / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'directory': str(run), **receipt}, indent=2))
    if not receipt['completedWithoutRuntimeError']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
