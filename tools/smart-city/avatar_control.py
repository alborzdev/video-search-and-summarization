"""Fixed, loopback-only operator commands to the Kit-owned avatar session."""
import json
from pathlib import Path
import runpy
import time
import urllib.request


class AvatarControl:
    def __init__(self, repo=None):
        self.repo = Path(repo) if repo else runpy.run_path(
            str(Path(__file__).with_name('isaac_workspace.py')))['runtime_root']()

    def request(self, operation='status'):
        if operation not in {'status', 'start', 'stop'}:
            raise ValueError('Choose start or stop live avatars')
        payload = {'action': 'avatars', 'operation': operation}
        if operation != 'status':
            payload['expiresAt'] = time.time() + 8
        token = (self.repo / 'logs/vss-integration/bridge-token').read_text().strip()
        request = urllib.request.Request('http://127.0.0.1:8766/control',
            data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json', 'X-City-Token': token})
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.load(response)
        if result.get('ok') is not True:
            raise RuntimeError(str(result.get('error', 'Avatar control unavailable')).splitlines()[-1][:240])
        data = result.get('data', {})
        if data.get('schemaVersion') != 'city.live-avatars.v1':
            raise RuntimeError('Restart the Smart City demo to connect live avatar controls')
        return data
