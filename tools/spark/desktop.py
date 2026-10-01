#!/usr/bin/env python3
"""One-click, cached Spark VSS start/stop. The simulator remains independent."""

import argparse
import fcntl
import html
import json
import os
from pathlib import Path
import queue
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import bootstrap as b
import offline
import ui
import history_metadata

APP_URL = 'http://127.0.0.1:7777/?workspace=guided'
API = 'http://127.0.0.1:7777/api/vision'
cancelled = threading.Event()


class Cancelled(RuntimeError):
    pass


def environment():
    # No download credentials or shell startup scripts in the desktop flow.
    keys = ('PATH', 'HOME', 'DOCKER_HOST', 'DOCKER_CONTEXT', 'XDG_RUNTIME_DIR',
            'DISPLAY', 'WAYLAND_DISPLAY', 'DBUS_SESSION_BUS_ADDRESS', 'XAUTHORITY', 'LANG')
    return {**{key: value for key, value in os.environ.items() if key in keys},
            'PYTHONUNBUFFERED': '1'}


def open_browser(progress):
    # Use the same Chromium session/profile as the simulator's desktop shortcut.
    executable = shutil.which('chromium-browser') or shutil.which('chromium')
    command = [executable, '--new-tab', APP_URL] if executable else None
    if command is None:
        executable = shutil.which('xdg-open')
        command = [executable, APP_URL] if executable else None
    if command is None:
        progress.say('No browser launcher is available. Open ' + APP_URL)
        return False
    try:
        subprocess.Popen(command, env=environment(), start_new_session=True,
            stdout=progress.log, stderr=subprocess.STDOUT)
    except OSError as error:
        progress.say('The browser could not open: ' + str(error) + '. Open ' + APP_URL)
        return False
    return True


def api(path, body=None, method=None, timeout=20):
    headers = {'Content-Type': 'application/json'}
    base = API
    if not (b.STATE / 'desktop-offline.json').exists():
        host = json.loads((b.STATE / 'settings.json').read_text())['host_ip']
        base = f'http://{host}:7777/api/vision'
    request = urllib.request.Request(base + path,
        data=json.dumps(body).encode() if body is not None else None,
        method=method or ('POST' if body is not None else 'GET'), headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        detail = ''
        try:
            payload = json.loads(error.read(4096))
            message = payload.get('error') if isinstance(payload, dict) else None
            if isinstance(message, str):
                detail = ' ' + ' '.join(message.split())[:300]
        except (OSError, ValueError):
            pass
        raise RuntimeError(f'VSS could not complete {path.split("?")[0]} (HTTP {error.code}).' + detail) from error


def read_url(url, timeout=10):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.load(response)


class Progress:
    def __init__(self, action, gui):
        self.gui = gui
        self.window = None
        stamp = time.strftime('%Y%m%d-%H%M%S')
        folder = b.STATE / 'desktop-logs'
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = folder / f'{stamp}-{action}-{time.time_ns()}.log'
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        self.log = os.fdopen(fd, 'w', buffering=1)
        if gui:
            self.window = subprocess.Popen(['zenity', '--progress', '--pulsate', '--no-cancel',
                '--auto-close', '--title=' + ('Starting VSS' if action == 'start' else 'Stopping VSS'),
                '--text=Preparing…', '--width=540', '--height=170'], stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True, env=environment())

    def say(self, message):
        self.log.write(time.strftime('%H:%M:%S ') + message + '\n')
        if not self.gui:
            print(message, flush=True)
        if self.window and self.window.poll() is None:
            try:
                self.window.stdin.write('# ' + html.escape(message.replace('\n', ' ')) + '\n')
                self.window.stdin.flush()
            except BrokenPipeError:
                pass

    def finish(self, message, error=False):
        self.say(message)
        if self.window:
            if self.window.poll() is None:
                self.window.stdin.write('100\n')
                self.window.stdin.close()
                try:
                    self.window.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.window.terminate()
            self.window = None
        self.log.close()
        if self.gui:
            subprocess.Popen(['zenity', '--error' if error else '--info', '--no-markup',
                '--title=VSS', '--width=540', '--text=' + message + ('\n\nLog: ' + str(self.path) if error else '')],
                env=environment(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def execute(self, command, label, timeout=1500):
        if cancelled.is_set():
            raise Cancelled('Startup was interrupted by Stop VSS.')
        self.say(label)
        process = subprocess.Popen([str(x) for x in command], cwd=b.ROOT,
            env=environment(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, start_new_session=True)
        lines = queue.Queue()
        def consume():
            try:
                for line in process.stdout:
                    lines.put(line)
            finally:
                process.stdout.close()
        reader = threading.Thread(target=consume, daemon=True)
        reader.start()
        deadline = time.monotonic() + timeout
        failure = None
        try:
            while process.poll() is None or not lines.empty() or reader.is_alive():
                if cancelled.is_set():
                    raise Cancelled('Startup was interrupted by Stop VSS.')
                if time.monotonic() > deadline:
                    raise RuntimeError(label + ' timed out. Check the saved log.')
                try:
                    line = lines.get(timeout=0.25)
                except queue.Empty:
                    continue
                self.log.write(line)
                if line.startswith('ERROR: '):
                    failure = line.strip().removeprefix('ERROR: ')
                if line.startswith(' Container ') and 'Starting' in line:
                    name = line.split()[1]
                    phases = {
                        'vss-spark-spark-llm-1': 'Loading the language model from local cache…',
                        'vss-rtvi-embed': 'Loading video embeddings from local cache…',
                        'vss-rtvi-vlm': 'Loading visual reasoning from local cache…',
                        'vss-rtvi-cv': 'Starting warehouse detection and tracking…',
                        'vss-agent': 'Starting the video agent…',
                        'vss-agent-ui': 'Starting the app…',
                    }
                    self.say(phases.get(name, 'Starting video and data services…'))
            if process.wait() != 0:
                detail = ' ' + failure + '.' if failure else ''
                raise RuntimeError(label + ' failed.' + detail + ' Check the saved log.')
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)


def lock(action, progress):
    path = b.STATE / 'desktop-operation.lock'
    handle = path.open('a+')
    operation = b.STATE / 'desktop-operation.json'
    deadline = time.monotonic() + (180 if action == 'stop' else 1)
    notified = False
    signaled = False
    while True:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if action != 'stop' or time.monotonic() >= deadline:
                handle.close()
                raise RuntimeError('A VSS operation is already in progress. Wait for its window, or use Stop VSS.')
            if not notified:
                progress.say('Waiting for the current VSS operation…')
                notified = True
            if not signaled:
                try:
                    current = json.loads(operation.read_text())
                    pid = int(current['pid'])
                    command = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
                    cwd = Path(f'/proc/{pid}/cwd').resolve()
                    own_script = any((cwd / os.fsdecode(argument)).resolve() == Path(__file__).resolve()
                                     for argument in command if argument)
                    # Avoid signaling a reused PID or an unrelated application.
                    if current['action'] == 'start' and own_script:
                        progress.say('Interrupting startup before shutdown…')
                        os.kill(pid, signal.SIGTERM)
                        signaled = True
                except (OSError, ValueError, KeyError, json.JSONDecodeError):
                    pass
            time.sleep(0.25)
    b.private_write(operation, json.dumps({'pid': os.getpid(), 'action': action, 'time': time.time()}))
    return handle


def model_health():
    for url in ('http://127.0.0.1:30081/v1/models', 'http://127.0.0.1:8018/v1/health/ready',
                'http://127.0.0.1:8017/v1/ready', 'http://127.0.0.1:8100/health',
                'http://127.0.0.1:9000/api/v1/health/get-dsready-state'):
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                if response.status != 200:
                    return False
        except (OSError, urllib.error.URLError):
            return False
    return True


def wait_docker(progress):
    progress.say('Waiting for the local Docker engine…')
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if cancelled.is_set():
            raise Cancelled('Startup was interrupted by Stop VSS.')
        try:
            b.run(['docker', 'info', '--format', '{{.ServerVersion}}'],
                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
            return
        except FileNotFoundError as error:
            raise RuntimeError('Docker is not installed; local VSS setup is required.') from error
        except (OSError, subprocess.SubprocessError):
            time.sleep(1)
    raise RuntimeError('The local Docker engine did not become ready within 45 seconds. Try Start VSS after Docker is available.')


def models_running():
    ids = b.run(b.compose('ps', '--status', 'running', '-q', 'spark-llm', 'rtvi-embed', 'rtvi-vlm'),
                capture_output=True, text=True, timeout=15).stdout.strip()
    return bool(ids)


def stack_ready(graph):
    ids = b.run(b.compose('ps', '-a', '-q'), capture_output=True, text=True, timeout=15).stdout.split()
    if not ids:
        return False
    rows = json.loads(b.run(['docker', 'inspect', *ids], capture_output=True, text=True, timeout=15).stdout)
    states = {row['Config']['Labels']['com.docker.compose.service']: row['State'] for row in rows}
    completed = b.completed_services(graph)
    for name in graph['services']:
        state = states.get(name, {})
        if name in completed and state.get('Status') == 'exited' and state.get('ExitCode') == 0:
            continue
        if state.get('Status') != 'running' or state.get('Health', {}).get('Status', 'healthy') != 'healthy':
            return False
    return True


def wait_app(progress):
    progress.say('Opening the current app and checking local services…')
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if cancelled.is_set():
            raise Cancelled('Startup was interrupted by Stop VSS.')
        try:
            with urllib.request.urlopen(APP_URL, timeout=20) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(2)
    raise RuntimeError('The app did not respond. Check the saved startup log.')


def pause_rules():
    for rule in api('/monitoring-rules').get('rules', []):
        if rule.get('status') == 'active':
            api('/monitoring-rules?id=' + urllib.parse.quote(rule['id'], safe=''),
                {'action': 'pause'}, method='PATCH', timeout=60)


def local_sim_published():
    """Bounded, read-only probe of the registered local Sim video path."""
    deadline = time.monotonic() + 3
    response = bytearray()
    try:
        with socket.create_connection(('127.0.0.1', 8554), timeout=3) as connection:
            connection.sendall(b'DESCRIBE rtsp://127.0.0.1:8554/digital-twin RTSP/1.0\r\n'
                               b'CSeq: 1\r\nAccept: application/sdp\r\n\r\n')
            while len(response) < 65536:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                connection.settimeout(remaining)
                chunk = connection.recv(min(4096, 65536 - len(response)))
                if not chunk:
                    return False
                response.extend(chunk)
                if b'\r\n\r\n' not in response:
                    continue
                header, body = bytes(response).split(b'\r\n\r\n', 1)
                lines = header.split(b'\r\n')
                if lines[0].split()[:2] != [b'RTSP/1.0', b'200']:
                    return False
                headers = dict(line.lower().split(b':', 1) for line in lines[1:] if b':' in line)
                length = int(headers.get(b'content-length', b'0').strip())
                if length <= 0 or length > 65536 - len(header) - 4:
                    return False
                if len(body) >= length:
                    return (headers.get(b'content-type', b'').strip() == b'application/sdp'
                            and any(line.startswith(b'm=video ') for line in body[:length].splitlines()))
    except (OSError, ValueError):
        pass
    return False


def recover_sensor_connection(sid, status, progress):
    """Recover VIOS discovery without touching the independent live recorder.

    Its cached binary retains CameraNotFoundError when a publisher comes online
    after boot. Fresh retained footage or a successful local video DESCRIBE
    proves publication, including when the recorder was explicitly stopped.
    """
    if status.get('state') != 'offline' or status.get('errorCode') != 'CameraNotFoundError':
        return False
    try:
        recording = api('/live-capture?streamId=' + urllib.parse.quote(sid, safe=''))
    except (RuntimeError, OSError):
        recording = {}
    if recording.get('questionReady') is not True and not local_sim_published():
        return False
    progress.execute(b.compose('restart', 'sensor-ms'),
                     'Recovering camera discovery from the published local video…', timeout=60)
    return True


def ready_sim(prepared, progress, fresh_start):
    sid = prepared['sensor_id']
    # Cold startup reserves visual reasoning for questions even if the Sim is
    # published later. Persisted active flags must not outlive lost CPU state.
    if fresh_start:
        pause_rules()
        # A bridge restart can lose jobs while leaving local ownership files,
        # including ones whose saved rule already says paused. Release those
        # stale reservations before source analysis or questions need Cosmos.
        api('/live-alert-rules?sourceId=' + urllib.parse.quote(sid, safe=''),
            method='DELETE', timeout=75)
    progress.say('Checking the simulator stream. Start the Sim using its existing shortcut…')
    deadline = time.monotonic() + 45
    sensor = None
    recovered = False
    while time.monotonic() < deadline:
        if cancelled.is_set():
            raise Cancelled('Startup was interrupted by Stop VSS.')
        try:
            status = read_url(f'http://127.0.0.1:30888/vst/api/v1/sensor/{sid}/status')
            # Discovery can retain an online state after the local publisher
            # exits. Do not attempt analysis/capture against that stale flag:
            # a late Sim should leave the loaded app available, not fail start.
            if status.get('state') in ('online', 'streaming') and local_sim_published():
                sensor = read_url(f'http://127.0.0.1:30888/vst/api/v1/sensor/{sid}/info')
                break
        except (OSError, ValueError):
            # Discovery briefly drops its HTTP listener during selective recovery.
            time.sleep(2)
            continue
        if not recovered and recover_sensor_connection(sid, status, progress):
            recovered = True
            deadline = time.monotonic() + 45
        time.sleep(2)
    if not sensor:
        return 'VSS is running. The simulator stream is not available yet. Start the Sim, then click Start VSS again to connect it.'
    # Heavy visual monitoring is explicit in the app, leaving the visual lane available for questions.
    body = {'sourceId': sid, 'name': sensor['name'], 'sourceKind': 'live'}
    state = read_url(f'http://127.0.0.1:8100/api/v1/rtsp-streams/{sid}/analysis')
    if state.get('analysisProfileId') != 'warehouse-safety' or not state.get('detectionEnabled'):
        api('/source-analysis', {**body, 'action': 'configure', 'analysisProfileId': 'warehouse-safety'}, timeout=180)
        state = read_url(f'http://127.0.0.1:8100/api/v1/rtsp-streams/{sid}/analysis')
    if not state.get('analysisActive'):
        progress.say('Restoring live indexing, detection and tracking…')
        api('/source-analysis', {**body, 'action': 'pause'}, timeout=180)
        api('/source-analysis', {**body, 'action': 'resume'}, timeout=180)
    api('/live-capture', {'streamId': sid, 'action': 'start'}, timeout=40)
    progress.say('Recording is on. Waiting for fresh searchable footage…')
    started = time.time() - 10
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if cancelled.is_set():
            raise Cancelled('Startup was interrupted by Stop VSS.')
        state = read_url(f'http://127.0.0.1:8100/api/v1/rtsp-streams/{sid}/analysis')
        query = urllib.parse.urlencode({'name': sensor['name'], 'sensorId': sid})
        intelligence = api('/source-intelligence?' + query)
        stamp = intelligence.get('lastSemanticAt')
        if stamp:
            from datetime import datetime
            observed = datetime.fromisoformat(stamp.replace('Z', '+00:00')).timestamp()
            if observed >= started and state.get('analysisActive'):
                try:
                    recording = api('/live-capture?streamId=' + urllib.parse.quote(sid, safe=''))
                except (OSError, RuntimeError):
                    # Recording can be on before its recent timeline is usable.
                    # Keep waiting within the same readiness deadline.
                    recording = {}
                if recording.get('streamId') == sid and recording.get('questionReady') is True:
                    return ('VSS is ready. Live recording, searchable video, detection and tracking are running. '
                            + ('Visual monitoring rules are paused so you can ask questions.' if fresh_start else 'Existing monitoring settings are preserved.'))
        time.sleep(3)
    raise RuntimeError('VSS started, but fresh indexing and playable live recording were not verified. Check the camera in the app; do not present it as ready.')


def start(progress):
    wait_docker(progress)
    settings, graph = offline.preflight(progress.say)
    b.doctor()
    progress.execute(['systemctl', '--user', 'start', 'vss-spark-guard.service'], 'Checking the memory guard', timeout=20)
    progress.execute(['systemctl', '--user', 'is-active', '--quiet', 'vss-spark-guard.service'],
                     'Verifying the memory guard is running', timeout=20)
    history_metadata.ensure_bridge()
    touched = not (b.STATE / 'desktop-offline.json').exists() or settings['host_ip'] != settings['gateway']
    try:
        prepared = offline.prepare(settings, progress.say, progress.execute)
        # Preparation can upgrade the existing cached graph or local addresses.
        # Read readiness against that resulting configuration.
        _, graph = offline.load()
        models_ready = model_health()
        if (models_ready and not stack_ready(graph)) or (not models_ready and models_running()):
            # A missing UI or data service needs a full, guarded recovery. Stop
            # loaded models first so cold-start admission has its normal headroom.
            touched = True
            progress.say('Recovering an incomplete VSS session…')
            stop(progress)
            models_ready = False
        if not models_ready:
            touched = True
            progress.execute([sys.executable, Path(__file__).with_name('bootstrap.py'), 'up'],
                'Starting cached VSS services. Model warm-up can take several minutes…')
        if ui.current_mode() != 'dev':
            # UI recreation owns only the UI. A warm session keeps its rules
            # and loaded models even if the later app/source check fails.
            progress.execute([sys.executable, Path(__file__).with_name('ui.py'), 'dev'], 'Loading the latest workspace')
        wait_app(progress)
        result = ready_sim(prepared, progress, touched)
        if b.available() < b.memory_reserve():
            raise RuntimeError('The memory reserve was crossed during startup.')
        b.private_write(b.STATE / 'desktop-ready.json', json.dumps({'time': time.time(),
            'available_gib': b.available(), 'reserve_gib': b.memory_reserve(), 'message': result, 'url': APP_URL}))
        return result
    except Exception:
        if touched:
            progress.say('Startup did not finish. Stopping partial VSS services…')
            try:
                subprocess.run([str(x) for x in b.compose('stop', '-t', '10')], env=environment(),
                               stdout=progress.log, stderr=subprocess.STDOUT, timeout=120, check=False)
            except (OSError, subprocess.SubprocessError) as error:
                progress.log.write('Partial startup cleanup failed: ' + str(error) + '\n')
        raise


def stop(progress):
    progress.say('Pausing monitoring and finishing the current recording…')
    try:
        pause_rules()
    except Exception as error:
        progress.log.write('Monitoring pause was unavailable: ' + str(error) + '\n')
    marker = b.STATE / 'desktop-offline.json'
    sid = None
    if marker.exists():
        try:
            sid = json.loads(marker.read_text())['sensor_id']
        except (OSError, ValueError, KeyError) as error:
            progress.log.write('Source identity was unavailable: ' + str(error) + '\n')
    if sid:
        try:
            sensor = read_url(f'http://127.0.0.1:30888/vst/api/v1/sensor/{sid}/info')
            api('/source-analysis', {'sourceId': sid, 'name': sensor['name'], 'action': 'pause'}, timeout=90)
        except Exception as error:
            progress.log.write('Source pause was unavailable: ' + str(error) + '\n')
        try:
            # Finishing retained footage remains necessary even if monitoring
            # or camera discovery is temporarily unavailable.
            api('/live-capture', {'streamId': sid, 'action': 'stop'}, timeout=40)
        except Exception as error:
            progress.log.write('Recording stop was unavailable: ' + str(error) + '\n')
    progress.execute(b.compose('stop', '-t', '20'), 'Stopping VSS services. Saved recordings and reports are preserved.', timeout=180)
    history_metadata.stop_bridge()
    remaining = b.run(b.compose('ps', '--status', 'running', '-q'), capture_output=True, text=True, timeout=15).stdout.strip()
    if remaining:
        raise RuntimeError('Some VSS services are still running. Check the shutdown log.')
    return 'VSS is stopped. Recordings, reports, rules and cached models are preserved. The simulator is still controlled by its own shortcut.'


def install_shortcuts():
    for action, title in (('start', 'Start VSS'), ('stop', 'Stop VSS')):
        icon = Path(__file__).parent / 'icons' / f'vss-{action}.svg'
        content = f'''[Desktop Entry]
Version=1.0
Type=Application
Name={title}
Comment={'Start local video intelligence from cached models' if action == 'start' else 'Stop video intelligence and preserve saved evidence'}
Exec=/usr/bin/python3 "{Path(__file__).resolve()}" {action} --gui
Path={b.ROOT}
Icon={icon.resolve()}
Terminal=false
Categories=AudioVideo;
StartupNotify=false
'''
        for folder in (Path.home() / 'Desktop', Path.home() / '.local/share/applications'):
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f'vss-{action}.desktop'
            path.write_text(content)
            path.chmod(0o755)
            if folder.name == 'Desktop':
                subprocess.run(['gio', 'set', str(path), 'metadata::trusted', 'true'], check=True)
    print('Installed Start VSS and Stop VSS on the Desktop and in Applications.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'stop', 'check', 'install'])
    parser.add_argument('--gui', action='store_true')
    parser.add_argument('--no-open', action='store_true')
    args = parser.parse_args()
    if args.action == 'install':
        install_shortcuts()
        return 0
    b.STATE.mkdir(mode=0o700, exist_ok=True)
    def interrupt(*_):
        cancelled.set()
        if args.action == 'start':
            raise Cancelled('Startup was interrupted by Stop VSS.')
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, interrupt)
    progress = Progress(args.action, args.gui)
    if args.gui:
        # Desktop launchers may close their inherited output pipes. Keep both
        # Python and child-process diagnostics in the private log instead.
        os.dup2(progress.log.fileno(), 1)
        os.dup2(progress.log.fileno(), 2)
    handle = None
    try:
        handle = lock(args.action, progress)
        if args.action == 'check':
            offline.preflight(progress.say)
            result = 'Offline prerequisites verified: cached images, model files, engines, video decoder, data folders and UI dependencies.'
        else:
            result = globals()[args.action](progress)
        if args.action == 'start' and not args.no_open:
            if not open_browser(progress):
                result += '\n\nOpen the app manually: ' + APP_URL
        progress.finish(result)
        return 0
    except Exception as error:
        progress.finish(str(error), error=True)
        return 1
    finally:
        if handle:
            (b.STATE / 'desktop-operation.json').unlink(missing_ok=True)
            fcntl.flock(handle, fcntl.LOCK_UN)
            handle.close()


if __name__ == '__main__':
    sys.exit(main())
