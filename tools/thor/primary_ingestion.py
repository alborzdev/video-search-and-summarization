#!/usr/bin/env python3
"""Start the selected camera without making camera readiness a VSS startup gate."""
import json
from datetime import datetime
from pathlib import Path
import subprocess
import sys
import time
import urllib.parse

from desktop import environment, local_json
import bootstrap as b

UNIT = 'vss-thor-primary-ingestion.service'


def timestamp(value):
    if not value:
        return 0
    return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()


class Startup:
    def __init__(self, primary):
        self.primary = primary
        self.analysis_requested = False
        self.recording_started = False
        self.previous = None
        self.record_advanced = self.index_advanced = None

    def step(self):
        camera = local_json('/vst/api/v1/sensor/status', port=30888).get(self.primary, {})
        if camera.get('state') != 'online' or not camera.get('name'):
            self.previous = None
            self.record_advanced = self.index_advanced = None
            return 'waiting-for-camera'
        sid = urllib.parse.quote(self.primary, safe='')
        analysis_path = f'/api/v1/rtsp-streams/{sid}/analysis'
        analysis = local_json(analysis_path, port=8100)
        # Resume once at launch. Thereafter the agent owns reconnection; an
        # operator pause must not be overridden by this startup helper.
        if self.analysis_requested and analysis.get('state') == 'paused':
            return 'paused'
        if not self.analysis_requested:
            steps = analysis.get('steps', {})
            if analysis.get('state') == 'paused' or not (
                    steps.get('embedding_resource') and steps.get('embedding')):
                b.require_guard()
                local_json(analysis_path, {'action': 'resume', 'name': camera['name']},
                           timeout=110, port=8100)
            self.analysis_requested = True

        record_path = f'/vst/api/v1/record/{sid}'
        mode = local_json(record_path + '/status', port=30888).get('recordingStatus')
        if self.recording_started and mode == 'off':
            return 'paused'
        if mode == 'error':
            # VIOS cannot start an Error recorder without a reset. This does
            # not remove retained video or touch any other source.
            b.require_guard()
            local_json(record_path + '/stop', {}, port=30888)
        if mode not in ('user', 'schedule', 'alwaysOn', 'on'):
            b.require_guard()
            local_json('/api/vision/live-capture', {'streamId': self.primary, 'action': 'start'})
        else:
            self.recording_started = True

        timelines = local_json(f'/vst/api/v1/storage/{sid}/timelines', port=30888)
        query = urllib.parse.urlencode({'sensorId': self.primary, 'name': camera['name']})
        intelligence = local_json('/api/vision/source-intelligence?' + query)
        current = (max((timestamp(row.get('endTime')) for row in timelines), default=0),
                   timestamp(intelligence.get('lastSemanticAt')),
                   intelligence.get('semanticSegments') or 0)
        now = time.monotonic()
        if self.previous is not None:
            if current[0] > self.previous[0]:
                self.record_advanced = now
            if current[1] > self.previous[1] or current[2] > self.previous[2]:
                self.index_advanced = now
        self.previous = current
        # Observe new data during this launch. Camera/NTP timestamps may lag
        # host wall time; static retained evidence alone cannot pass this check.
        if all(value is not None and now - value < 90
               for value in (self.record_advanced, self.index_advanced)):
            return 'active'
        return 'waiting-for-progress'


def report(state, primary):
    b.shared.private_write(b.STATE / 'primary-ingestion.json', json.dumps({
        'time': time.time(), 'primary_stream_id': primary, 'state': state,
        'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}))


def serve():
    config = json.loads((b.STATE / 'desktop-config.json').read_text())
    if not config.get('auto_primary_ingestion', False):
        return
    startup = Startup(config['primary_stream_id'])
    previous = None
    while True:
        try:
            b.require_guard()
        except Exception:
            report('guard-unavailable', startup.primary)
            print('Camera startup stopped: runtime guard is unavailable.', flush=True)
            return
        try:
            state = startup.step()
        except Exception as error:
            # API errors can include private source URLs. Log the category only.
            state = 'waiting-for-services:' + type(error).__name__
        report(state, startup.primary)
        if state != previous:
            print('Main-camera startup: ' + state, flush=True)
            previous = state
        if state in ('active', 'paused'):
            return
        time.sleep(10)


def start():
    script = str(Path(__file__).resolve())
    if any(char in script for char in '\n\r"%\\'):
        raise RuntimeError('Unsupported systemd checkout path')
    unit = Path.home() / '.config/systemd/user' / UNIT
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text(f'''[Unit]
Description=VSS main-camera automatic startup
[Service]
ExecStart=/usr/bin/python3 "{script}" serve
Restart=no
MemoryMax=128M
CPUQuota=50%
UMask=0077
''')
    # Launched by the desktop after service readiness, never independently at
    # boot. A guard stop cannot cause this unit to restart any model services.
    for command in ('daemon-reload', 'start'):
        subprocess.run(['systemctl', '--user', command, *([UNIT] if command == 'start' else [])],
                       check=True, timeout=10, env=environment())


if __name__ == '__main__':
    if sys.argv[1:] == ['serve']:
        serve()
    elif sys.argv[1:] == ['start']:
        start()
    else:
        raise SystemExit('Use start or serve')
