#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Explicit local deployment profile for experimental people map association."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

IMAGE = re.compile(r"sha256:[a-f0-9]{64}\Z")
NATIVE = 'mv3dt-native-v1'


def load(root: Path, device: str) -> dict | None:
    state = root / f'.{device}/city/state'
    path = state / 'native/mv3dt-demo/active.json'
    if not path.is_file():
        return None
    if path.is_symlink() or path.stat().st_size > 65536:
        raise ValueError('Invalid local MV3DT demo profile')
    value = json.loads(path.read_text())
    if value.get('enabled') is False:
        return None
    if value.get('schemaVersion') != 'city.mv3dt-demo.v1' or value.get('enabled') is not True:
        raise ValueError('MV3DT demo requires an explicit enabled versioned profile')
    order, calibrations = value.get('cameraOrder'), value.get('cameraCalibrations')
    if (device != 'spark' or value.get('siteId') != 'isaac-intersection-a'
            or not isinstance(order, list) or len(order) != 2 or len(set(order)) != 2
            or not isinstance(calibrations, dict) or set(calibrations) != set(order)
            or any(not isinstance(v, str) or not v for v in calibrations.values())
            or not IMAGE.fullmatch(value.get('imageId', ''))):
        raise ValueError('MV3DT demo needs its explicit Spark site, camera pair, calibration and image')
    hashes = value.get('fileHashes')
    tracker = value.get('trackerConfig')
    if not isinstance(hashes, dict) or not hashes or tracker not in hashes:
        raise ValueError('MV3DT demo tracker/config hashes are required')
    local_tracker = value.get('localTrackerConfig')
    architecture = value.get('trackingArchitecture')
    if 'trackingClassPolicy' in value and (architecture != NATIVE or value['trackingClassPolicy'] != 'car-truck-family-v1'):
        raise ValueError('Car/truck association policy requires explicit single native MV3DT')
    if 'trackerDiagnostics' in value and (architecture != NATIVE or type(value['trackerDiagnostics']) is not bool):
        raise ValueError('Tracker diagnostics require an explicit boolean on single native MV3DT')
    if architecture == NATIVE:
        singles = value.get('singleCameraTrackerConfigs')
        if (local_tracker is not None or not isinstance(singles, dict) or set(singles) != set(order)
                or any(not isinstance(p, str) or p not in hashes for p in singles.values())):
            raise ValueError('Native MV3DT requires pinned per-camera configs and no separate local tracker')
    elif local_tracker is not None or architecture is not None:
        if (architecture != 'nvdcf-local-then-mv3dt-v1' or not isinstance(local_tracker, str)
                or local_tracker == tracker or local_tracker not in hashes):
            raise ValueError('Staged tracking requires its explicit architecture and separately pinned local config')
    clock_booleans = ('sourceClockDiagnostics', 'muxSyncInputs')
    clock_nanoseconds = ('muxMaxLatencyNs', 'muxSyncInputsNtpNs')
    mode = value.get('sourceClockMode', 'source-rtcp')
    if mode not in ('source-rtcp', 'source-native-sei'):
        raise ValueError('sourceClockMode must be source-rtcp or source-native-sei')
    if mode == 'source-native-sei' and architecture not in ('nvdcf-local-then-mv3dt-v1', NATIVE):
        raise ValueError('Native SEI clock requires the explicitly pinned staged Isaac profile')
    if any(key in value for key in (*clock_booleans, *clock_nanoseconds)):
        if architecture not in ('nvdcf-local-then-mv3dt-v1', NATIVE):
            raise ValueError('Explicit clock controls require the staged native profile')
        if any(key in value and type(value[key]) is not bool for key in clock_booleans):
            raise ValueError('Clock diagnostic/sync controls must be explicit booleans')
        if any(key in value and (type(value[key]) is not int or not 0 <= value[key] <= 1_000_000_000)
               for key in clock_nanoseconds):
            raise ValueError('Mux latency/window controls must be integers from 0 to 1000000000 nanoseconds')
    for relative, expected in hashes.items():
        candidate = state / relative
        if (not isinstance(relative, str) or not relative.startswith('native/mv3dt-demo/')
                or candidate.is_symlink() or not candidate.resolve().is_relative_to(state.resolve())
                or not candidate.is_file() or candidate.stat().st_size > 1024 * 1024
                or hashlib.sha256(candidate.read_bytes()).hexdigest() != expected):
            raise ValueError('MV3DT demo config changed or escaped its local profile')
    assets = value.get('auxiliaryModelAssets', {})
    if not isinstance(assets, dict) or len(assets) > 4:
        raise ValueError('Invalid auxiliary tracking model manifest')
    models = root/f'.{device}/city/models'
    for relative, expected in assets.items():
        if not isinstance(relative, str):
            raise ValueError('Auxiliary tracking model path must be relative text')
        candidate = models/relative
        if (architecture != NATIVE or not isinstance(relative, str) or candidate.is_symlink()
                or not candidate.resolve().is_relative_to(models.resolve()) or not candidate.is_file()
                or not isinstance(expected, dict) or type(expected.get('bytes')) is not int
                or not 0 < expected['bytes'] <= 512*1024*1024 or candidate.stat().st_size != expected['bytes']
                or hashlib.sha256(candidate.read_bytes()).hexdigest() != expected.get('sha256')):
            raise ValueError('Auxiliary tracking model changed or escaped its pinned cache')
    return value


def native_args(profile: dict | None, site: dict, *, live: bool) -> list[str]:
    if profile is None:
        return []
    sources = site.get('sources', [])
    native = profile.get('trackingArchitecture') == NATIVE
    # Native MV3DT uses the correctly ordered camera calibration even during
    # one-camera admission. Never silently fall back to the 2D tracker.
    if native:
        if (not live or site.get('id') != profile['siteId'] or not 1 <= len(sources) <= 2
                or any(s.get('id') not in profile['cameraCalibrations']
                    or s.get('calibrationRevision') != profile['cameraCalibrations'][s['id']] for s in sources)):
            raise ValueError('Native MV3DT camera admission must match its pinned live site/calibration')
    if len(sources) < 2 and not native:
        if profile.get('sourceClockMode') == 'source-native-sei':
            if (len(sources) != 1 or not live or site.get('id') != profile['siteId']
                    or sources[0].get('id') not in profile['cameraCalibrations']
                    or sources[0].get('calibrationRevision') != profile['cameraCalibrations'][sources[0]['id']]):
                raise ValueError('Native SEI single-camera admission must match its pinned Isaac source/calibration')
            return ['--source-native-sei-clock']
        return []
    if (not live or site.get('id') != profile['siteId']
            or (len(sources) == 2 and [s['id'] for s in sources] != profile['cameraOrder'])
            or any(s.get('calibrationRevision') != profile['cameraCalibrations'][s['id']] for s in sources)):
        raise ValueError('MV3DT demo camera order/site/calibration no longer matches its profile')
    revision = set(profile['cameraCalibrations'].values())
    if len(revision) != 1:
        raise ValueError('The two demo cameras need the same calibration revision')
    tracker = (profile['singleCameraTrackerConfigs'][sources[0]['id']]
               if native and len(sources) == 1 else profile['trackerConfig'])
    result = ['--tracker-mode', 'mv3dt-demo', '--tracker-config', '/state/' + tracker,
              '--tracker-calibration-revision', next(iter(revision))]
    if profile.get('trackingArchitecture') == 'nvdcf-local-then-mv3dt-v1':
        result.extend(['--local-tracker-config', '/state/' + profile['localTrackerConfig']])
    if native:
        result.extend(['--tracking-architecture', NATIVE])
        if profile.get('trackingClassPolicy') == 'car-truck-family-v1':
            result.append('--native-car-truck-family')
        if profile.get('trackerDiagnostics') is True:
            result.append('--tracker-diagnostics')
    if native or profile.get('trackingArchitecture') == 'nvdcf-local-then-mv3dt-v1':
        if profile.get('sourceClockMode') == 'source-native-sei':
            result.append('--source-native-sei-clock')
        if profile.get('sourceClockDiagnostics') is True:
            result.append('--source-clock-diagnostics')
        if profile.get('muxSyncInputs') is True:
            result.append('--mux-sync-inputs')
        for key, option in (('muxMaxLatencyNs', '--mux-max-latency-ns'),
                            ('muxSyncInputsNtpNs', '--mux-sync-inputs-ntp-ns')):
            if key in profile:
                result.extend([option, str(profile[key])])
    return result


def gateway_environment(profile: dict | None) -> dict[str, str]:
    if profile is None:
        return {}
    return {'CITY_MV3DT_DEMO_ENABLED': 'true', 'CITY_MV3DT_DEMO_SITE_ID': profile['siteId'],
            'CITY_MV3DT_DEMO_CAMERA_CALIBRATIONS': json.dumps(profile['cameraCalibrations'], sort_keys=True),
            'CITY_SOURCE_CLOCK_MODE': profile.get('sourceClockMode', 'source-rtcp')}
