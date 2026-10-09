#!/usr/bin/env python3
"""Start the prepared Thor demo from local caches using a desktop shortcut."""
import argparse
import fcntl
import html
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.request

import bootstrap as b


def environment():
    names = ('PATH', 'HOME', 'DISPLAY', 'WAYLAND_DISPLAY', 'DBUS_SESSION_BUS_ADDRESS',
             'XDG_RUNTIME_DIR', 'XAUTHORITY', 'LANG', 'DOCKER_HOST', 'DOCKER_CONTEXT')
    return {**{name: value for name, value in os.environ.items() if name in names},
            'PYTHONUNBUFFERED': '1'}


class Progress:
    def __init__(self, gui):
        folder = b.STATE / 'desktop-logs'
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = folder / f'{time.strftime("%Y%m%d-%H%M%S")}-{time.time_ns()}.log'
        self.log = os.fdopen(os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'w', buffering=1)
        self.gui = gui
        self.window = subprocess.Popen(['zenity', '--progress', '--pulsate', '--auto-close',
            '--no-cancel', '--title=Start VSS · Anvil T5', '--width=560', '--text=Preparing local VSS…'],
            stdin=subprocess.PIPE, text=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=environment()) if gui else None

    def say(self, message):
        self.log.write(time.strftime('%H:%M:%S ') + message + '\n')
        if not self.gui:
            print(message, flush=True)
        if self.window and self.window.poll() is None:
            try:
                self.window.stdin.write('# ' + html.escape(message) + '\n')
                self.window.stdin.flush()
            except BrokenPipeError:
                pass

    def execute(self, command, message, timeout=1900):
        self.say(message)
        process = None
        try:
            process = subprocess.Popen([str(item) for item in command], cwd=b.ROOT, env=environment(),
                stdin=subprocess.DEVNULL, stdout=self.log, stderr=subprocess.STDOUT,
                start_new_session=True)
            if process.wait(timeout=timeout) != 0:
                raise RuntimeError(message + ' failed. See the startup log.')
        except (OSError, subprocess.SubprocessError) as error:
            raise RuntimeError(message + ' failed. See the startup log.') from error
        finally:
            if process is not None and process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)

    def finish(self, message, error=False):
        self.say(message)
        if self.window and self.window.poll() is None:
            try:
                self.window.stdin.write('100\n')
                self.window.stdin.close()
                self.window.wait(timeout=5)
            except (BrokenPipeError, subprocess.TimeoutExpired):
                self.window.terminate()
        self.log.close()
        if self.gui and error:
            subprocess.Popen(['zenity', '--error', '--no-markup', '--title=VSS startup',
                '--width=560', '--text=' + message + '\n\nLog: ' + str(self.path)], env=environment())


def validate_offline(settings, graph):
    if not settings.get('cached_models'):
        raise RuntimeError('Prepare cached-model mode before using the offline shortcut.')
    services = graph['services']
    for name in ('thor-llm', 'rtvi-embed', 'rtvi-vlm', 'vss-agent', 'vss-va-mcp'):
        env = services[name].get('environment', {})
        if env.get('HF_HUB_OFFLINE') != '1' or env.get('TRANSFORMERS_OFFLINE') != '1' or env.get('NGC_API_KEY'):
            raise RuntimeError(f'{name} is not configured for offline inference.')
        if name in ('rtvi-embed', 'rtvi-vlm') and env.get('RTVI_OFFLINE') != 'true':
            raise RuntimeError(f'{name} may attempt a model download.')
    stream = services['streamprocessing-ms']
    if (stream.get('environment', {}).get('VST_INSTALL_ADDITIONAL_PACKAGES') != 'false'
            or 'user_additional_install.sh' in ' '.join(stream.get('entrypoint', []))):
        raise RuntimeError('Video I/O must use its prepared offline codecs.')
    images = {service['image'] for service in services.values()}
    sidecar = b.STATE / 'nvstreamer-compose.json'
    if sidecar.exists():
        images.update(service['image'] for service in json.loads(sidecar.read_text())['services'].values())
    return sorted(images)


def preflight(progress):
    b.require_thor()
    settings = b.settings()
    graph = json.loads((b.STATE / 'compose.json').read_text())
    images = validate_offline(settings, graph)
    b.verify_agent_cache()
    progress.execute(['docker', 'image', 'inspect', *images], 'Checking locally cached Docker images…', timeout=30)
    for name in ('nemotron', 'rtvi-ngc'):
        if not (Path(settings['data_dir']) / 'models' / name).is_dir():
            raise RuntimeError(f'The local {name} model cache is missing.')
    if settings.get('detector_enabled'):
        engine = Path(settings['data_dir']) / 'models/thor-detector/rtdetr_warehouse_v1.0.2.fp16.onnx_b1_gpu0_fp16.engine'
        if not engine.is_file() or not engine.stat().st_size:
            raise RuntimeError('The cached native Thor detector engine is missing.')
    if not (b.ROOT / 'services/ui/node_modules/next/dist/bin/next').is_file():
        raise RuntimeError('UI dependencies must be installed before going offline.')
    progress.execute(['sudo', '-n', '/usr/bin/jetson_clocks', '--show'], 'Checking the configured Jetson clock permission…', timeout=30)
    return settings, graph


def ready_services(graph):
    ids = b.run(b.compose('ps', '-a', '-q'), capture_output=True, text=True, timeout=20).stdout.split()
    if not ids:
        return set()
    rows = json.loads(b.run(['docker', 'inspect', *ids], capture_output=True, text=True, timeout=20).stdout)
    completed = b.shared.completed_services(graph)
    ready = set()
    for row in rows:
        name = row['Config']['Labels']['com.docker.compose.service']
        state = row['State']
        if ((name in completed and state['Status'] == 'exited' and state['ExitCode'] == 0)
                or (name not in completed and state['Status'] == 'running'
                    and state.get('Health', {}).get('Status', 'healthy') == 'healthy')):
            ready.add(name)
    return ready


def stage_plan(graph):
    services = set(graph['services'])
    models = {'thor-llm', 'rtvi-embed', 'rtvi-vlm'}
    app = {'lvs-server', 'alert-bridge', 'vss-agent', 'vss-va-mcp', 'history-maintenance', 'vss-ui', 'vss-haproxy-ingress'}
    detector = {'thor-perception'} & services
    return [('support', services - models - app - detector),
            ('thor-llm', {'thor-llm'}), ('rtvi-embed', {'rtvi-embed'}),
            ('rtvi-vlm', {'rtvi-vlm'}), *([('thor-perception', detector)] if detector else []),
            ('app', app)]


def connect(progress, connection, message):
    active = subprocess.check_output(['nmcli', '-g', 'UUID', 'connection', 'show', '--active'],
                                     text=True, timeout=10).splitlines()
    if connection not in active:
        progress.execute(['nmcli', 'connection', 'up', 'uuid', connection], message, timeout=35)


def start(progress):
    settings, graph = preflight(progress)
    config = json.loads((b.STATE / 'desktop-config.json').read_text())
    connect(progress, config['local_connection'], 'Restoring the stable local VSS address…')
    # The camera can be switched off while the models and app are still useful.
    try:
        connect(progress, config['camera_connection'], 'Connecting camera Ethernet…')
    except RuntimeError:
        progress.say('Camera Ethernet is unavailable. Starting VSS and waiting for the camera.')
    progress.execute(['sudo', '-n', '/usr/bin/jetson_clocks'], 'Applying Jetson maximum clocks…', timeout=60)
    progress.execute([sys.executable, b.ROOT / 'tools/thor/bootstrap.py', 'install-guard'],
                     f'Applying the saved {b.memory_reserve():g} GiB memory guard…', timeout=30)
    # A restarted guard needs its first live memory/thermal sample before admission.
    deadline = time.monotonic() + 15
    while True:
        try:
            b.require_guard()
            break
        except RuntimeError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(1)
    touched = False
    labels = {
        'support': 'Starting local video and data services…',
        'thor-llm': 'Loading the language model from local cache…',
        'rtvi-embed': 'Loading video search from local cache…',
        'rtvi-vlm': 'Loading visual reasoning from local cache…',
        'thor-perception': 'Starting detection and tracking…',
        'app': 'Starting VSS…',
    }
    try:
        for stage, names in stage_plan(graph):
            if names <= ready_services(graph):
                progress.say(labels[stage].rstrip('…') + ': already ready.')
                continue
            touched = True
            progress.execute([sys.executable, b.ROOT / 'tools/thor/bootstrap.py', 'start', '--stage', stage, '--reuse-ready'],
                             labels[stage])
        if (b.STATE / 'nvstreamer-compose.json').exists():
            progress.execute([sys.executable, b.ROOT / 'tools/thor/nvstreamer.py', 'start'],
                             'Restoring the optional mock stream server…', timeout=90)
        progress.execute([sys.executable, b.ROOT / 'tools/thor/bootstrap.py', 'verify'],
                         'Checking actual local service readiness…', timeout=120)
        url = f'http://{settings["host_ip"]}:3001/?workspace=live'
        with urllib.request.urlopen(url, timeout=30) as response:
            if response.status != 200:
                raise RuntimeError('The VSS UI did not become ready.')
        with urllib.request.urlopen('http://127.0.0.1:3001/api/vision/primary-source', timeout=10) as response:
            primary = json.load(response).get('streamId')
        if primary != config['primary_stream_id']:
            raise RuntimeError('The saved main-camera selection has changed. Review it in VSS.')
        with urllib.request.urlopen('http://127.0.0.1:30888/vst/api/v1/sensor/status', timeout=10) as response:
            camera = json.load(response).get(primary, {})
        message = 'VSS is ready. Main camera is ' + ('online.' if camera.get('state') == 'online' else 'waiting for its connection.')
        b.shared.private_write(b.STATE / 'desktop-ready.json', json.dumps({
            'time': time.time(), 'url': url, 'reserve_gib': b.memory_reserve(),
            'primary_stream_id': primary, 'camera_state': camera.get('state'),
            'available_gib': b.shared.available(), 'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}))
        return message, url
    except Exception:
        if touched:
            progress.say('Startup did not finish. Stopping partial services; saved data is preserved.')
            subprocess.run([str(item) for item in b.compose('stop', '-t', '10')],
                env=environment(), stdout=progress.log, stderr=subprocess.STDOUT, timeout=180, check=False)
        raise


def install_shortcut():
    content = f'''[Desktop Entry]
Version=1.0
Type=Application
Name=Start VSS · Anvil T5
Comment=Start offline VSS, camera services and Jetson clocks
Exec=/usr/bin/python3 "{Path(__file__).resolve()}" start --gui
Path={b.ROOT}
Icon={b.ROOT / 'tools/spark/icons/vss-start.svg'}
Terminal=false
Categories=AudioVideo;
StartupNotify=false
'''
    desktop = Path(subprocess.check_output(['xdg-user-dir', 'DESKTOP'], text=True).strip())
    for folder in (desktop, Path.home() / '.local/share/applications'):
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / 'vss-thor-start.desktop'
        path.write_text(content)
        path.chmod(0o755)
        if folder == desktop:
            subprocess.run(['gio', 'set', str(path), 'metadata::trusted', 'true'], check=True)
    print('Installed Start VSS · Anvil T5 on the Desktop and in Applications.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('start', 'check', 'install'))
    parser.add_argument('--gui', action='store_true')
    parser.add_argument('--no-open', action='store_true')
    args = parser.parse_args()
    if args.action == 'install':
        install_shortcut()
        return 0
    progress = Progress(args.gui)
    def interrupted(*_):
        raise RuntimeError('VSS startup was interrupted.')
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    with (b.STATE / 'desktop-operation.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if args.action == 'check':
                preflight(progress)
                message = 'Offline configuration and locally cached images, models, UI and clock permissions verified.'
            else:
                message, url = start(progress)
                if not args.no_open:
                    subprocess.Popen(['xdg-open', url], env=environment(),
                        stdout=progress.log, stderr=subprocess.STDOUT, start_new_session=True)
            progress.finish(message)
            return 0
        except Exception as error:
            progress.finish('A VSS startup is already running.' if isinstance(error, BlockingIOError) else str(error), error=True)
            return 1


if __name__ == '__main__':
    sys.exit(main())
