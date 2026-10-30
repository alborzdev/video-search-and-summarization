#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Operate the existing two-camera Isaac/VSS integration; no install or model build."""
from __future__ import annotations

import argparse
import json
import os
import runpy
import subprocess
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[2]
_workspace = runpy.run_path(str(Path(__file__).with_name('isaac_workspace.py')))
CITY = _workspace['runtime_root']()
WORKSPACE_SERVICE, RTSP_SERVICE = _workspace['service_names']()
REGISTRATION = ROOT / '.spark/city/isaac-registration.json'
GATEWAY = 'http://127.0.0.1:9184/api/v1/city/'
CONTROLLER = 'http://127.0.0.1:9190'
UI_ORIGIN = os.environ.get('VSS_ISAAC_UI_ORIGIN', 'http://127.0.0.1:7782')
if UI_ORIGIN not in ('http://127.0.0.1:7777', 'http://127.0.0.1:7782'):
    raise ValueError('Select the local VSS UI on port 7777 or 7782')
CAMERA_IDS = ('cam_SW', 'cam_NE')


class CityLoadFailed(Exception):
    """A completed failed load cannot become ready by waiting longer."""


def loaded_city():
    state = bridge()
    if not state.get('loading') and not state.get('loaded') and state.get('error'):
        raise CityLoadFailed('City preparation failed: ' + str(state['error'])[:400])
    return state.get('loaded')


def selected_scene_stage():
    module = CITY / 'scripts/scene/demo_scene_profile.py'
    if not module.is_file():
        if (CITY / 'config/tradeshow_scene_profile.json').exists():
            raise RuntimeError('The selected scene profile reader is missing')
        return str(CITY / 'stages/smart_city_pilot.usda')
    return runpy.run_path(str(module))['load_scene_profile'](CITY)['stage']


def configured_backend():
    backend = json.loads((CITY / 'config/survey_intersection_A.json').read_text()).get('rtsp', {}).get('backend')
    if backend not in ('software', 'native'):
        raise RuntimeError('The prepared VSS demo requires an explicit software or native RTSP backend')
    return backend


def stream_progress(stream, *, expected_backend=None, minimum_frames=1):
    """Validate actual writer state, without inventing native encoder queues.

    Native ``pushed`` counts server handoffs, not decoded downstream delivery.
    ready() and ensure_recordings() independently check those consumers.
    """
    backend = stream.get('backend')
    if backend not in ('software', 'native') or (expected_backend is not None and backend != expected_backend):
        raise RuntimeError('The attached RTSP backend does not match the configured backend')
    if stream.get('attached') is not True or stream.get('n_cameras') != 2:
        raise RuntimeError('Expected exactly two attached stream render products')
    urls = stream.get('urls') or []
    if len(urls) != 2 or {row.get('cam') for row in urls} != set(CAMERA_IDS):
        raise RuntimeError('Expected exactly the two selected RTSP camera URLs')
    if backend == 'native':
        channels = stream.get('streams') or {}
    else:
        stats = stream.get('stats') or {}
        if stats.get('error') or stats.get('push_errors'):
            raise RuntimeError('Software encoder reported a push failure')
        channels = stats.get('streams') or {}
    if set(channels) != set(CAMERA_IDS):
        raise RuntimeError('The stream camera identities do not match the selected pair')
    counts = {}
    for name, row in channels.items():
        count = row.get('pushed' if backend == 'native' else 'frame_id')
        healthy = (row.get('attached') is True and row.get('server') is True
            and row.get('failed') is False and row.get('first_error') is None
            and row.get('swizzle_error') is None and not row.get('error')) if backend == 'native' else (
                row.get('encoderAlive') is True and not row.get('error'))
        if not healthy or type(count) is not int or count < minimum_frames:
            raise RuntimeError('A camera writer has failed or has not produced enough frames')
        counts[name] = count
    return {'backend': backend, 'frameCounts': counts, 'channels': channels,
        'counterBasis': 'native-server-handoffs' if backend == 'native' else 'software-encoded-frames',
        'maximumQueuedFramesPerCamera': None if backend == 'native' else 1,
        'queueBoundStatus': 'unavailable-native-api' if backend == 'native' else 'bounded-software-queue'}


def validate_saved_calibration(site, registrations, state=None):
    """Reuse static geometry only for the saved stage/camera/resolution package."""
    profile = json.loads((CITY / 'config/vss_camera_profile.json').read_text())
    package = json.loads((CITY / 'logs/vss-integration/camera-map-export.json').read_text())
    stage = selected_scene_stage()
    resolution = profile.get('resolution')
    if (profile.get('cameraIds') != list(CAMERA_IDS) or not isinstance(resolution, list) or len(resolution) != 2
            or package.get('schemaVersion') != 'city.isaac-camera-export.v1'
            or package.get('cameraOrder') != list(CAMERA_IDS) or package.get('stage') != stage
            or not package.get('calibrationRevision')):
        raise RuntimeError('Saved camera package identity changed; review and explicitly refresh calibration')
    selected = site.get('sources', [])
    expected_ids = {source['id'] for source in registrations}
    if len({row['id'] for row in selected}) != len(selected) or any(row['id'] not in expected_ids for row in selected):
        raise RuntimeError('The selected site camera identities do not match the saved registrations')
    archived = {}
    if expected_ids - {row['id'] for row in selected}:
        # A normal Agent pause removes its source from the active site. The
        # controller retains static geometry for that same UUID; validate it
        # before resuming instead of requiring another site regeneration.
        archive_file = ROOT / '.spark/city/controller-calibrations.json'
        archived = json.loads(archive_file.read_text()) if archive_file.exists() else {}
    for name, source in zip(CAMERA_IDS, registrations):
        camera = package.get('cameras', {}).get(name, {})
        if [camera.get('width'), camera.get('height')] != resolution:
            raise RuntimeError('Saved camera resolution changed; review and explicitly refresh calibration')
        previous = next((row for row in selected if row['id'] == source['id']), archived.get(source['id']))
        if not previous or ([previous.get('width'), previous.get('height')] != resolution
                or previous.get('calibrationRevision') != package['calibrationRevision']):
            raise RuntimeError('The selected site and saved camera calibration do not match')
    if state is not None:
        cameras = (state.get('streams') or {}).get('cameras') or []
        expected_prims = {name: '/World/SmartCity/Cameras/' + name for name in CAMERA_IDS}
        if (state.get('stage') != stage or len(cameras) != 2
                or {row.get('id'): row.get('prim_path') for row in cameras} != expected_prims):
            raise RuntimeError('The running stage/camera prims do not match the saved calibration package')


def json_request(url, payload=None, token=None, *, timeout=20):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['X-City-Token'] = token
    req = urllib.request.Request(url, data=None if payload is None else json.dumps(payload).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def bridge(action='status', **extra):
    token = (CITY / 'logs/vss-integration/bridge-token').read_text()
    result = json_request('http://127.0.0.1:8766/control', {'action': action, **extra}, token)
    if not result.get('ok'):
        raise RuntimeError(str(result.get('error', 'Kit request failed'))[-1000:])
    return result['data']


def script(path, **defines):
    return bridge('script', path=path, defines=defines)


def prepare_pre_stream():
    path = 'scripts/tools/prepare_vss_viewport.py'
    extensions = ('isaacsim.robot_setup.virtual_gantry.ui', 'isaacsim.robot_setup.virtual_gantry')
    def viewport_valid(value):
        return (isinstance(value, dict) and value.get('schemaVersion') == 'city.vss-viewport.v1'
            and value.get('resolutionScale') == .5 and value.get('updatesEnabled') is True
            and value.get('streamRenderProductCount') == 0)
    prepared = script(path).get('result')
    gantry = prepared.get('gantry') if isinstance(prepared, dict) else None
    requested = gantry.get('requestedAtUpdate') if isinstance(gantry, dict) else None
    if (not viewport_valid(prepared) or type(requested) is not int or requested < 0
            or gantry.get('primCount') != 0 or gantry.get('requestedDisabled') != list(extensions)):
        raise RuntimeError('Pre-stream GUI viewport preparation was not confirmed')
    def verified():
        value = script(path, ACTION='verify', REQUESTED_AT_UPDATE=requested).get('result')
        state = value.get('gantry') if isinstance(value, dict) else None
        if not viewport_valid(value) or not isinstance(state, dict):
            return False
        enabled = state.get('extensionsEnabled')
        current = state.get('verifiedAtUpdate')
        return value if (value.get('ready') is True and state.get('verifiedAfterUpdate') is True
            and state.get('primCount') == 0 and state.get('requestedAtUpdate') == requested
            and type(current) is int and current > requested and isinstance(enabled, dict)
            and set(enabled) == set(extensions) and all(flag is False for flag in enabled.values())) else False
    return wait_for(verified, 'Waiting for unused gantry extension shutdown and GUI viewport readback…', 30)


def command(*arguments):
    return subprocess.run([str(a) for a in arguments], cwd=ROOT, check=True, capture_output=True, text=True)


def sources():
    registration = json.loads(REGISTRATION.read_text())
    if set(registration) != {'cam_SW', 'cam_NE'} or len({s['id'] for s in registration.values()}) != 2:
        raise RuntimeError('Exactly the two saved southwest/northeast registrations are required')
    profile = json.loads((CITY / 'config/vss_camera_profile.json').read_text())
    if profile['cameraIds'] != ['cam_SW', 'cam_NE']:
        raise RuntimeError('Two-camera profile changed; review calibration before starting')
    return [registration[name] for name in ('cam_SW', 'cam_NE')]


def embedding_service_stopped():
    """Host proof for pausing an explicitly optional, already stopped producer."""
    try:
        state = subprocess.run(['docker', 'inspect', 'vss-rtvi-embed', '--format', '{{json .State.Running}}'],
                               capture_output=True, text=True, timeout=5)
        return state.returncode == 0 and state.stdout.strip() == 'false'
    except (OSError, subprocess.SubprocessError):
        return False


def analysis(source, action):
    # Agent HTTP 200 can mean partial success. Smart City CV may be healthy
    # without an embedding producer only when the Agent explicitly confirms
    # the independent indexing policy; missing service fields are not proof.
    since = datetime.now(UTC).isoformat()
    result = command(sys.executable, ROOT / 'tools/smart-city/manage.py', 'source-analysis', '--kind', 'live',
        '--source-id', source['id'], '--name', source['name'], '--action', action)
    response = json.loads(result.stdout)
    if not isinstance(response, dict) or any(response.get(key) != value for key, value in (
        ('sensorId', source['id']), ('name', source['name']), ('action', action), ('analysisProfileId', 'smart-city'),
    )) or response.get('detectionEnabled') is not True:
        raise RuntimeError(f'Analysis {action} returned an invalid source/profile identity for {source["name"]}')
    steps = response.get('steps')
    if not isinstance(steps, dict) or not steps or any(type(value) is not bool for value in steps.values()):
        raise RuntimeError(f'Analysis {action} returned invalid service steps for {source["name"]}')
    indexing_required = response.get('indexingRequired', True)
    indexing_policy = response.get('indexingPolicy', 'continuous')
    indexing_confirmed = (
        indexing_required is False and indexing_policy in ('on-demand', 'disabled')
        and type(steps.get('embedding')) is bool
    ) or (
        indexing_required is True and indexing_policy == 'continuous' and steps.get('embedding') is True
    )
    complete = (
        response.get('state') == 'active' and response.get('analysisActive') is True
        and steps.get('detection') is True and indexing_confirmed
    ) if action == 'resume' else (
        response.get('analysisActive') is False and steps.get('detection') is True and (
            response.get('state') == 'paused' and steps.get('embedding') is True and all(steps.values())
            or response.get('state') == 'partial' and indexing_confirmed and indexing_required is False
            and steps.get('embedding') is False and all(value for key, value in steps.items() if key != 'embedding')
            and embedding_service_stopped()
        )
    )
    if not complete:
        required = ('detection',) if action == 'resume' and indexing_required is False and indexing_confirmed else (
            'detection', 'embedding', 'embedding_resource')
        incomplete = ', '.join(key for key in required if steps.get(key) is False)
        diagnostic = analysis_failure_detail(source['id'], since) if action == 'resume' else None
        detail = diagnostic or 'Required analysis services did not confirm the requested state'
        raise RuntimeError(f'Analysis {action} failed for {source["name"]}: {detail}; incomplete steps={incomplete or "unknown"}')
    return response


def analysis_failure_detail(source_id, since):
    """Read-only diagnostics, never retry authorization; do not expose raw logs."""
    try:
        result = subprocess.run(['docker', 'logs', '--since', since, '--tail', '200', 'vss-agent'],
            capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode:
        return None
    marker = f'Could not restore detection for {source_id}: RTVI-CV returned '
    found = None
    for line in (result.stdout + '\n' + result.stderr).splitlines():
        if marker not in line:
            continue
        status, _, body = line.split(marker, 1)[1].partition(': ')
        if len(status) != 3 or not status.isdecimal():
            continue
        found = f'Detector admission returned HTTP {status}; inspect the source-scoped Agent/controller log'
        try:
            payload = json.loads(body)
        except ValueError:
            continue
        detail = payload.get('detail') if isinstance(payload, dict) else None
        if detail in ('Registered source CPU decode probe failed',
                      'Registered source CPU probe exceeded its bounded timeout',
                      'Registered media could not be probed'):
            found = f'Detector admission returned HTTP {status}: {detail}'
    return found


def wait_for(check, description, seconds):
    deadline = time.monotonic() + seconds
    last_error = None
    next_notice = 0
    while time.monotonic() < deadline:
        try:
            result = check()
            if result:
                return result
        except (OSError, ValueError, RuntimeError) as exc:
            last_error = type(exc).__name__
        if time.monotonic() >= next_notice:
            print(description, flush=True)
            next_notice = time.monotonic() + 30
        time.sleep(1)
    raise RuntimeError(f'Timed out: {description}; last error={last_error}')


def expected_tracking_architecture():
    """Read the same hash-pinned profile used by the native controller."""
    loader = runpy.run_path(str(ROOT / 'tools/smart-city/mv3dt_demo_profile.py'))['load']
    profile = loader(ROOT, 'spark')
    return profile.get('trackingArchitecture') if profile else None


def expected_source_clock_mode():
    loader = runpy.run_path(str(ROOT / 'tools/smart-city/mv3dt_demo_profile.py'))['load']
    profile = loader(ROOT, 'spark')
    return profile.get('sourceClockMode', 'source-rtcp') if profile else 'source-rtcp'


def ready(*, excluded_source_sessions=None):
    health = json_request(GATEWAY + 'health')
    expected_order = [source['id'] for source in sources()]
    expected = set(expected_order)
    if health.get('siteId') != 'isaac-intersection-a' or health.get('mode') != 'live':
        return False
    architecture = expected_tracking_architecture()
    clock_mode = expected_source_clock_mode()
    selected = []
    if architecture or clock_mode == 'source-native-sei' or excluded_source_sessions is not None:
        # /health deliberately exposes only id/status. Read the actual full
        # source DTO from the unaligned current snapshot, never assume health
        # contains source sessions or tracker provenance.
        snapshot = json_request(GATEWAY + 'snapshot')
        selected = snapshot.get('sources', [])
        if (snapshot.get('siteId') != health['siteId'] or snapshot.get('mode') != 'live'
                or [source.get('id') for source in selected] != expected_order
                or any(source.get('status') != 'live' for source in selected)):
            return False
    if architecture:
        if (len(selected) != 2 or any(source.get('trackingArchitecture') != architecture
                or source.get('trackingMode') != 'mv3dt-demo'
                or not source.get('sourceSessionId') or not source.get('fusionEpoch') for source in selected)
                or len({source['fusionEpoch'] for source in selected}) != 1):
            return False
    if clock_mode == 'source-native-sei':
        for source in selected:
            proof = source.get('sourceClockEvidence') or {}
            if not isinstance(proof, dict):
                return False
            if (source.get('timestampBasis') != clock_mode or source.get('sourceClockMode') != clock_mode
                    or source.get('browserClockVerified') is not False
                    or proof.get('schemaVersion') != 'city.source-native-sei.v1'
                    or proof.get('method') != 'isaac-native-sei-wall-capture'
                    or proof.get('correlation') != 'exact-au-pts'
                    or proof.get('captureTimeNs') != source.get('lastSourceTimeNs')
                    or proof.get('auPtsNs') != source.get('rawSourcePtsNs')
                    or set(proof) != {'schemaVersion', 'method', 'correlation', 'captureTimeNs', 'auPtsNs', 'frameCounter'}
                    or any(not isinstance(proof.get(key), str) or not proof[key].isascii()
                        or not proof[key].isdigit() or len(proof[key]) > 20
                        or int(proof[key]) > (2**64 - 1 if key == 'frameCounter' else 2**63 - 1)
                        for key in ('captureTimeNs', 'auPtsNs', 'frameCounter'))
                    or int(proof['captureTimeNs']) == 0):
                return False
    if excluded_source_sessions is not None:
        if set(excluded_source_sessions) != expected:
            return False
        for source in selected:
            if (not source.get('sourceSessionId')
                    or source['sourceSessionId'] == excluded_source_sessions[source['id']]):
                return False
    live = {source['id'] for source in health['sources'] if source['status'] == 'live'}
    transport = health.get('processedPreview', {}).get('nativeDelivery', {}).get('transport')
    display = health.get('processedVideo' if transport == 'webrtc' else 'processedPreview', {})
    previews = {source['id'] for source in display.get('sources', []) if source.get('available')}
    native = health.get('nativeAnalyticsStatus', {})
    if clock_mode == 'source-native-sei' and native.get('sourceClockMode') != clock_mode:
        return False
    rules = json_request(GATEWAY + 'rules')
    expected_rules = {rule['id']: rule for rule in rules['rules'] if rule.get('enabled', True)}
    primitives = native.get('primitives', [])
    accounted = {}
    for primitive in primitives:
        identifier, status = primitive.get('ruleId'), primitive.get('primitiveStatus')
        if identifier not in expected_rules or identifier in accounted:
            return False
        space = expected_rules[identifier].get('geometry', {}).get('space')
        if status == 'backend-only':
            if space != 'site-metres' or not primitive.get('reason'):
                return False
        elif status != 'compiled' or space == 'site-metres':
            return False
        accounted[identifier] = status
    backend_active = rules.get('status') == 'active' and rules.get('authority') == 'city-behavior-analytics'
    return health if (live == expected and previews == expected
        and native.get('operationalStatus') == 'fresh' and native.get('status') == 'active'
        and backend_active and expected_rules and accounted.keys() == expected_rules.keys()
        and native.get('requestedRevision') == rules['revision']
        and native.get('appliedRevision') == rules['revision']) else False


def ensure_recordings():
    """A live decoder does not prove retained footage for Ask/evidence."""
    selected = sources()
    deadline = time.monotonic() + 60
    starts, retry_after = {}, {}
    description = 'Waiting for verified five-second recordings from both cameras…'
    def request(url, payload=None):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError('Timed out: ' + description)
        return json_request(url, payload, timeout=min(20, remaining))
    def restore(source, *, retry=False):
        sid = source['id']
        print(('Retrying' if retry else 'Restoring') + ' retained footage for ' + source['name'], flush=True)
        # Bound recovery attempts per source; a late VIOS QoS removal can race
        # an acknowledged recorder start. Existing media/identity stay intact.
        starts[sid] = starts.get(sid, 0) + 1
        try:
            request(UI_ORIGIN + '/api/vision/live-capture',
                {'streamId': sid, 'action': 'stop', 'lookbackSeconds': 5})
        except HTTPError:
            pass  # The following start and verified readiness decide success.
        request(UI_ORIGIN + '/api/vision/live-capture',
            {'streamId': sid, 'action': 'start', 'lookbackSeconds': 5})
        retry_after[sid] = time.monotonic() + 2
    for source in selected:
        sid = source['id']
        status = request('http://127.0.0.1:30888/vst/api/v1/record/' + sid + '/status')['recordingStatus']
        if status not in ('user', 'schedule', 'alwaysOn', 'on'):
            restore(source)
    def footage_ready():
        ready = True
        for source in selected:
            sid = source['id']
            state = request(UI_ORIGIN + '/api/vision/live-capture?streamId=' + sid + '&lookbackSeconds=5')
            ready = ready and state.get('questionReady') is True
            if (state.get('recordingStatus') == 'off' and starts.get(sid) == 1
                    and time.monotonic() >= retry_after[sid]):
                restore(source, retry=True)
                ready = False
        return ready
    wait_for(footage_ready, description, max(0, deadline - time.monotonic()))


def ensure_video_service():
    """Restore the existing owned service after a crash, without recreating data."""
    state = json.loads(command('docker', 'inspect', 'vss-vios-streamprocessing',
        '--format', '{{json .State}}').stdout)
    if not state.get('Running'):
        command('systemctl', '--user', 'is-active', '--quiet', 'vss-spark-guard.service')
        doctor = json.loads(command(sys.executable, ROOT / 'tools/smart-city/manage.py', 'doctor').stdout)
        if doctor['availableGiB'] < doctor['reserveGiB']:
            raise RuntimeError('Video service recovery needs the saved reserve available')
        print('Restoring the existing VSS video service…', flush=True)
        command('docker', 'start', 'vss-vios-streamprocessing')
    def available():
        # An empty catalog is a valid response while sensors reconnect.
        json_request('http://127.0.0.1:30888/vst/api/v1/live/streams')
        return True
    wait_for(available, 'Waiting for the VSS camera service…', 60)


def wait_for_gateway():
    """A gateway restart may outlive Docker's restart response; do not mutate yet."""
    def available():
        health = json_request(GATEWAY + 'health', timeout=5)
        return isinstance(health, dict) and health.get('status') == 'ok' and health.get('service') == 'vss-city-analytics'
    wait_for(available, 'Waiting for the Smart City analytics service…', 60)


def wait_for_controller(registrations):
    """Wait for the existing controller before any source lifecycle request."""
    expected = {source['id']: source['name'] for source in registrations}
    def available():
        health = json_request(CONTROLLER + '/api/v1/health', timeout=5)
        if not isinstance(health, dict) or health.get('ready') is not True:
            return False
        capacity = health.get('capacity')
        wrapper = health.get('stream-info')
        entries = wrapper.get('stream-info') if isinstance(wrapper, dict) else None
        if not isinstance(capacity, dict) or not isinstance(entries, list):
            return False
        if any(type(capacity.get(key)) is not int for key in ('maxSources', 'registeredSources', 'availableSources')):
            return False
        if capacity['maxSources'] != 2 or capacity['registeredSources'] != len(entries) or not 0 <= len(entries) <= 2 or capacity['availableSources'] != 2 - len(entries):
            return False
        ids = []
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get('camera_id'), str) or entry['camera_id'] not in expected:
                return False
            if entry.get('camera_name') != expected[entry['camera_id']] or entry.get('status') not in ('running', 'registered-stopped'):
                return False
            ids.append(entry['camera_id'])
        if len(ids) != len(set(ids)):
            return False
        # The health DTO has no service-name field. Verify the app identity via
        # its read-only OpenAPI document, rather than accepting a generic 200.
        description = json_request(CONTROLLER + '/openapi.json', timeout=5)
        info = description.get('info') if isinstance(description, dict) else None
        return isinstance(info, dict) and info.get('title') == 'Local VSS Smart City source controller'
    wait_for(available, 'Waiting for the Smart City source controller and its owned-source inventory…', 60)


def start(*, refresh_calibration=False):
    registrations = sources()
    backend = configured_backend()
    # The early already-running check also needs the gateway. Wait before both
    # ready() and /site; a transient refused connection must not abort recovery.
    # This checks the existing service only and never starts an unknown one.
    wait_for_gateway()
    active = subprocess.run(['systemctl', '--user', 'is-active', '--quiet', WORKSPACE_SERVICE]).returncode == 0
    if active:
        state = wait_for(lambda: bridge(), 'Waiting for the existing Isaac control bridge…', 90)
        if not refresh_calibration and state['loaded'] and state['streaming'] and state['playing']:
            try:
                stream_progress(state.get('streams') or {}, expected_backend=backend, minimum_frames=30)
            except RuntimeError:
                pass  # Release the old writer below before attaching the configured backend.
            else:
                site = json_request(GATEWAY + 'site')
                validate_saved_calibration(site, registrations, state)
                worker = json_request(CONTROLLER + '/api/v1/detections')
                if worker.get('state') == 'running' and ready():
                    ensure_recordings()
                    print('Two-camera Isaac Smart City demo is already ready.'); return
    # Reject an unrelated active site instead of replacing another workspace's work.
    site = json_request(GATEWAY + 'site')
    if site.get('id') != 'isaac-intersection-a':
        raise RuntimeError('Another site is selected; explicitly restore/review the Isaac site first')
    if not refresh_calibration:
        validate_saved_calibration(site, registrations)
    # systemctl restart can return before Uvicorn is accepting requests. Keep
    # this before the mutation/rollback block: an unavailable controller must
    # not trigger either initial pauses or an unnecessary simulator shutdown.
    wait_for_controller(registrations)
    started_here = not active
    try:
        # Release old analysis sessions before reconnecting or changing calibration.
        for source in registrations:
            analysis(source, 'pause')
        ensure_video_service()
        command('systemctl', '--user', 'start', RTSP_SERVICE)
        command('systemctl', '--user', 'start', WORKSPACE_SERVICE)
        state = wait_for(lambda: bridge(), 'Waiting for the Isaac control bridge…', 240)
        if not state['loaded']:
            if not state['loading']:
                script('scripts/tools/pilot_ext_driver.py', ACTION='click', BTN='load')
            wait_for(loaded_city, 'Loading the city and checking people/navigation…', 210)
        state = bridge()
        if state['streaming'] and (state.get('streams') or {}).get('backend') != backend:
            script('scripts/tools/pilot_ext_driver.py', ACTION='click', BTN='stop_stream')
            state = bridge()
        if not state['playing']:
            if state['streaming']:
                script('scripts/tools/pilot_ext_driver.py', ACTION='click', BTN='stop_stream')
            script('scripts/tools/pilot_ext_driver.py', ACTION='click', BTN='play')
        wait_for(lambda: (s if (s := bridge()).get('playing') and s.get('playbackReady') else False),
                 'Waiting for native pedestrian and traffic playback preparation…', 90)
        if not bridge()['streaming']:
            prepare_pre_stream()
            # The live dropdown can retain the previous backend even after the
            # survey changes. Exercise its real selection before Start.
            script('scripts/tools/pilot_ext_driver.py', ACTION='click', BTN='rtsp:' + backend)
            script('scripts/tools/pilot_ext_driver.py', ACTION='click', BTN='start_stream')
        state = wait_for(lambda: (s if (s := bridge())['streaming'] and not s['streamBusy'] else False),
            'Starting the two configured RTSP camera writers…', 75)
        streams = state.get('streams') or {}
        if streams.get('attached') is not True or streams.get('n_cameras') != 2 or len(streams.get('urls', [])) != 2:
            raise RuntimeError('Expected exactly two attached stream render products')
        def encoders_ready():
            state = bridge()
            stream_progress(state.get('streams') or {}, expected_backend=backend, minimum_frames=30)
            return state
        state = wait_for(encoders_ready, 'Waiting for the first encoded camera frames…', 30)
        if refresh_calibration:
            script('scripts/rtsp/export_vss_calibration.py')
            command(sys.executable, ROOT / 'tools/smart-city/isaac_site.py', '--camera-package',
                CITY / 'logs/vss-integration/camera-map-export.json', '--registration', REGISTRATION,
                '--output', ROOT / '.spark/city/runtime/isaac-integration-20261023', '--apply')
            command(sys.executable, ROOT / 'tools/smart-city/isaac_mobility.py', '--apply')
        else:
            validate_saved_calibration(site, registrations, state)
        # Let the origin/VIOS produce a decodable GOP before native admission.
        for source in registrations:
            print('Resuming ' + source['name'], flush=True)
            analysis(source, 'resume')
        health = wait_for(ready, 'Waiting for real inference, configured rules and exact previews…', 60)
        ensure_recordings()
        print(json.dumps({'ready': True, 'url': UI_ORIGIN + '/?workspace=smart-city',
            'sourceCount': len(health['sources']), 'globalFusionEnabled': health.get('globalFusionEnabled'),
            'note': 'Camera-local tracks. The simulator runs below wall rate on this combined Spark workload.'}, indent=2))
    except BaseException:
        for source in registrations:
            try:
                analysis(source, 'pause')
            except Exception:
                pass
        if started_here:
            subprocess.run(['systemctl', '--user', 'stop', WORKSPACE_SERVICE], timeout=55)
        raise


def stop():
    # A partial Agent response for one camera must not prevent attempts to stop
    # the second owned source and the simulator explicitly requested by the user.
    failures = []
    for source in sources():
        try:
            analysis(source, 'pause')
        except Exception as exc:
            failures.append(f'{source["name"]} pause unconfirmed ({type(exc).__name__})')
    try:
        command('systemctl', '--user', 'stop', WORKSPACE_SERVICE)
    except Exception as exc:
        failures.append(f'Isaac service stop unconfirmed ({type(exc).__name__})')
    if failures:
        raise RuntimeError('Stop completed only partially: ' + '; '.join(failures))
    print('The two Isaac sources are paused; media and unrelated services are preserved.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('start', 'stop', 'status'))
    parser.add_argument('--refresh-calibration', action='store_true',
        help='Explicitly regenerate the static camera/site/rule package after reviewing camera geometry changes')
    args = parser.parse_args()
    if args.refresh_calibration and args.action != 'start':
        parser.error('--refresh-calibration is only valid with start')
    if args.action == 'start':
        start(refresh_calibration=args.refresh_calibration)
    elif args.action == 'stop':
        stop()
    else:
        try:
            state = bridge()
        except (OSError, ValueError, RuntimeError):
            state = {'running': False}
        result = {'isaac': state}
        try:
            pipeline_ready = bool(ready())
            result['vssReady'] = False
            if pipeline_ready and state.get('loaded') and state.get('playing') and state.get('streaming') and not state.get('streamBusy'):
                try:
                    stream_progress(state.get('streams') or {}, expected_backend=configured_backend(), minimum_frames=30)
                except RuntimeError:
                    pass
                else:
                    result['vssReady'] = True
        except (OSError, ValueError, RuntimeError) as exc:
            result.update(vssReady=False, vssError=f'The Smart City gateway is unavailable ({type(exc).__name__}).')
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('ERROR: ' + ' '.join(str(error).split())[:600], flush=True)
        raise SystemExit(1)
