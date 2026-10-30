"""The desktop client must obey the Kit bridge's ten-second command window."""
import io
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import avatar_control as client


def test_avatar_command_expiry_fits_bridge_window_with_cold_response_timeout(monkeypatch, tmp_path):
    token = tmp_path/'logs/vss-integration/bridge-token'
    token.parent.mkdir(parents=True)
    token.write_text('local-test-token')
    monkeypatch.setattr(client.time, 'time', lambda: 100.)
    calls = []
    def request(req, timeout):
        calls.append((json.loads(req.data), timeout))
        return io.BytesIO(json.dumps({'ok':True,'data':{'schemaVersion':'city.live-avatars.v1','running':True}}).encode())
    monkeypatch.setattr(client.urllib.request, 'urlopen', request)
    assert client.AvatarControl(repo=tmp_path).request('start')['running'] is True
    payload, timeout = calls[0]
    assert payload['operation'] == 'start'
    assert 100 < payload['expiresAt'] <= 110
    assert timeout > 10
