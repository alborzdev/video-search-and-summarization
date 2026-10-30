#!/usr/bin/env python3
"""VSS-owned host lifecycle for the fixed, local Moondream2 + SAM 2.1 worker.

Selection and unit installation never load models. The unit has no login target
and is started only by an explicit VSS start. No model downloads are performed.
"""

import argparse
import json
import math
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / '.spark'
UNIT = 'vss-spark-local-vision.service'
GUARD = 'vss-spark-guard.service'
URL = 'http://127.0.0.1:8026'


def _state(state=None):
    return STATE if state is None else Path(state)


def selected(settings=None, state=None):
    if settings is None:
        path = _state(state) / 'settings.json'
        settings = json.loads(path.read_text()) if path.exists() else {}
    value = settings.get('local_vision_enabled', False)
    if not isinstance(value, bool):
        raise RuntimeError('local_vision_enabled must be a boolean.')
    return value


def token_value(state=None):
    directory = _state(state) / 'local-segmentation'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / 'service-token'
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(secrets.token_urlsafe(32))
    if path.is_symlink():
        raise RuntimeError('Local vision token must be a regular private file.')
    path.chmod(0o600)
    token = path.read_text().strip()
    if len(token) < 32 or len(token) > 128 or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in token):
        raise RuntimeError('Invalid local vision token.')
    return token


def configure_graph(graph, *, enabled=None, state=None):
    enabled = selected(state=state) if enabled is None else selected({'local_vision_enabled': enabled})
    ui = graph.get('services', {}).get('vss-ui')
    if ui is not None:
        env = ui.setdefault('environment', {})
        env.pop('LOCAL_VISION_API_URL', None)
        env.pop('LOCAL_VISION_API_TOKEN', None)
        if enabled:
            env.update(LOCAL_VISION_API_URL=URL, LOCAL_VISION_API_TOKEN=token_value(state))
    return graph


def ui_configuration_matches(graph):
    """Compare private server env without returning/logging the credential."""
    service = graph.get('services', {}).get('vss-ui', {})
    container = service.get('container_name')
    if not container:
        return False
    keys = ('LOCAL_VISION_API_URL', 'LOCAL_VISION_API_TOKEN')
    expected = {key: service.get('environment', {}).get(key) for key in keys}
    try:
        result = subprocess.run(['docker', 'inspect', '--format', '{{json .Config.Env}}', container],
                                check=True, capture_output=True, text=True, timeout=10)
        entries = json.loads(result.stdout)
        actual = dict(entry.split('=', 1) for entry in entries if isinstance(entry, str) and '=' in entry)
        return all(actual.get(key) == expected[key] for key in keys)
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        return False


def _private_write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def select(enabled, state=None):
    """Explicitly select startup, migrating only cached UI wiring; no services."""
    state = _state(state)
    settings_path = state / 'settings.json'
    settings = json.loads(settings_path.read_text())
    settings['local_vision_enabled'] = selected({'local_vision_enabled': enabled})
    graph_path = state / 'compose.json'
    graph = json.loads(graph_path.read_text())
    configure_graph(graph, enabled=enabled, state=state)
    _private_write(graph_path, json.dumps(graph, indent=2) + '\n')
    _private_write(settings_path, json.dumps(settings, indent=2) + '\n')


def reserve_gib(state=None):
    reserve = json.loads((_state(state) / 'settings.json').read_text())['reserve_gib']
    if isinstance(reserve, bool) or not isinstance(reserve, (int, float)) or not math.isfinite(reserve) or not 0 <= reserve < 128:
        raise RuntimeError('Local vision requires a valid saved Spark reserve (0 disables the floor).')
    return float(reserve)


def available_gib():
    return next(int(line.split()[1]) / 2**20 for line in Path('/proc/meminfo').read_text().splitlines()
                if line.startswith('MemAvailable:'))


def active(unit):
    return subprocess.run(['systemctl', '--user', 'is-active', '--quiet', unit],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5).returncode == 0


def admission(state=None):
    reserve = reserve_gib(state)
    if not active(GUARD):
        raise RuntimeError('Start the existing Spark memory guard before local vision.')
    available = available_gib()
    if available < reserve:
        raise RuntimeError(f'Local vision needs the saved {reserve:g} GiB reserve; have {available:.2f} GiB.')
    return reserve


def unit_content(state=None, root=ROOT):
    state = _state(state)
    root = Path(root)
    venv = state / 'moondream-photon/venv'
    python = venv / 'bin/python'
    # The staged venv is Python 3.12. Do not inspect/import a GPU package here.
    site = venv / 'lib/python3.12/site-packages'
    libs = sorted({str(path) for package in ('nvidia', 'nvpl')
                   for path in (site / package).glob('**/lib') if path.is_dir()})
    values = [str(root), str(state), str(python), *libs]
    if any(any(c in value for c in '\n\r"%\\') for value in values):
        raise RuntimeError('Unsupported systemd service path characters.')
    return f'''[Unit]
Description=VSS local Moondream2 and SAM 2.1 Tiny vision
BindsTo={GUARD}
After={GUARD}
[Service]
Type=simple
WorkingDirectory={root}
ExecStart="{python}" "{root / 'tools/segmentation/server.py'}" --host 127.0.0.1 --port 8026 --token-file "{state / 'local-segmentation/service-token'}"
Environment="LD_LIBRARY_PATH={':'.join(libs)}"
Environment=PYTHONUNBUFFERED=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 OMP_NUM_THREADS=4
Restart=no
KillMode=control-group
TimeoutStopSec=15
CPUQuota=400%
MemoryAccounting=yes
MemoryMax=16G
MemorySwapMax=0
UMask=0077
'''


def install_unit(state=None, unit_dir=None):
    state = _state(state)
    token_value(state)
    for path in (state / 'moondream-photon/venv/bin/python', ROOT / 'tools/segmentation/server.py',
                 state / 'local-segmentation/manifest.json', state / 'moondream-photon/md2-model-path.txt',
                 state / 'moondream-photon/tokenizer-path.txt'):
        if not path.is_file():
            raise RuntimeError(f'Local vision staged artifact is missing: {path}')
    directory = Path(unit_dir) if unit_dir is not None else Path.home() / '.config/systemd/user'
    path = directory / UNIT
    content = unit_content(state)
    changed = not path.exists() or path.read_text() != content
    if changed:
        _private_write(path, content)
        subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True, timeout=20)
    return changed


def ready_snapshot():
    with urllib.request.urlopen(URL + '/ready', timeout=2) as response:
        if response.status != 200:
            raise RuntimeError('Local vision is not ready.')
        value = json.load(response)
    if (value.get('ready') is not True or value.get('status') != 'ready'
            or value.get('model') != 'moondream2' or value.get('segmenter') != 'sam2.1-tiny'
            or value.get('runtime') != 'photon'):
        raise RuntimeError('Local vision readiness did not confirm the selected models.')
    return value


def stop_service():
    # No disk reads: also safe as a best-effort shutdown after startup errors.
    result = subprocess.run(['systemctl', '--user', 'stop', UNIT], capture_output=True, text=True, timeout=20)
    if result.returncode and 'not loaded' not in result.stderr and 'not found' not in result.stderr:
        raise RuntimeError('Could not stop the local vision service.')


def ensure_service(state=None, timeout=180):
    state = _state(state)
    if not selected(state=state):
        if active(UNIT):
            stop_service()
        return False
    already_active = active(UNIT)
    changed = install_unit(state)
    started = False
    if changed and already_active:
        stop_service()
        already_active = False
    if not already_active:
        admission(state)
        subprocess.run(['systemctl', '--user', 'start', UNIT], check=True, timeout=20)
        started = True
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not active(GUARD) or not active(UNIT):
                raise RuntimeError('Local vision or its memory guard stopped before readiness.')
            if available_gib() < reserve_gib(state):
                raise RuntimeError('Local vision crossed the saved reserve during startup.')
            try:
                ready_snapshot()
                return started
            except (OSError, ValueError, RuntimeError):
                time.sleep(2)
        raise RuntimeError('Local vision did not warm both models within the readiness timeout.')
    except BaseException:
        if started:
            try:
                stop_service()
            except (OSError, RuntimeError, subprocess.SubprocessError):
                pass  # Preserve the actual startup failure for the operator.
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('select', 'install', 'start', 'stop', 'status'))
    parser.add_argument('--enabled', action=argparse.BooleanOptionalAction, default=None)
    args = parser.parse_args()
    if args.action == 'select':
        if args.enabled is None:
            parser.error('select requires --enabled or --no-enabled')
        select(args.enabled)
    elif args.enabled is not None:
        parser.error('--enabled applies only to select')
    elif args.action == 'install':
        install_unit()
    elif args.action == 'start':
        ensure_service()
    elif args.action == 'stop':
        stop_service()
    else:
        print(json.dumps({'enabled': selected(), 'active': active(UNIT)}))
