# SPDX-License-Identifier: Apache-2.0
"""Runtime relocation controls; no services, saved VSS state or Kit calls."""
import json
from pathlib import Path
import runpy
import sys

import pytest

TOOLS = Path(__file__).parents[1]
workspace = runpy.run_path(str(TOOLS / 'isaac_workspace.py'))


def test_default_selects_workspace_package_without_legacy_root_fallback():
    root = workspace['runtime_root']({'SMARTCITY_REPO': '/home/sparkdev/isaac_city_sim'})
    assert root == Path('/home/sparkdev/Documents/ChatGPT/isaacsim-6/environments/city')


def test_default_services_use_workspace_owner():
    assert workspace['service_names']({}) == ('isaac-workspace.service', 'isaac-workspace-rtsp.service')


def test_explicit_workspace_service_names_are_shared_with_demo(monkeypatch):
    monkeypatch.setenv('VSS_ISAAC_WORKSPACE_SERVICE', 'isaac-workspace-trial.service')
    monkeypatch.setenv('VSS_ISAAC_RTSP_SERVICE', 'isaac-workspace-trial-rtsp.service')
    demo = runpy.run_path(str(TOOLS / 'isaac_demo.py'))
    assert (demo['WORKSPACE_SERVICE'], demo['RTSP_SERVICE']) == (
        'isaac-workspace-trial.service', 'isaac-workspace-trial-rtsp.service')


@pytest.mark.parametrize('overrides', [
    {'VSS_ISAAC_WORKSPACE_SERVICE': 'isaac-city-vss-demo.service'},
    {'VSS_ISAAC_RTSP_SERVICE': 'isaac-city-rtsp.service'},
    {'VSS_ISAAC_WORKSPACE_SERVICE': '../escape.service'},
    {'VSS_ISAAC_WORKSPACE_SERVICE': 'isaac-workspace-rtsp.service'}])
def test_invalid_or_retired_service_selection_fails_closed(overrides):
    with pytest.raises(ValueError, match='retired city units'):
        workspace['service_names'](overrides)


@pytest.mark.parametrize('value', ['', ' ', '.', 'environments/city'])
def test_ambiguous_override_fails_closed(value):
    with pytest.raises(ValueError, match='explicit absolute runtime root'):
        workspace['runtime_root']({'VSS_ISAAC_CITY_ROOT': value})


def test_explicit_missing_package_never_creates_or_substitutes_a_runtime(tmp_path):
    missing = tmp_path / 'not-prepared'
    assert workspace['runtime_root']({'VSS_ISAAC_CITY_ROOT': str(missing)}) == missing
    assert not missing.exists()


def test_demo_and_control_share_explicit_root_and_keep_vss_registration_owner(monkeypatch, tmp_path):
    monkeypatch.setenv('VSS_ISAAC_CITY_ROOT', str(tmp_path))
    demo = runpy.run_path(str(TOOLS / 'isaac_demo.py'))
    control = runpy.run_path(str(TOOLS / 'demo_control.py'))['DemoControl']
    assert demo['CITY'] == tmp_path
    assert demo['REGISTRATION'] == TOOLS.parents[1] / '.spark/city/isaac-registration.json'
    assert control().repo == tmp_path
    explicit = tmp_path / 'explicit'
    assert control(repo=explicit).repo == explicit


def test_bridge_token_follows_runtime_root_without_changing_control_contract(monkeypatch, tmp_path):
    monkeypatch.setenv('VSS_ISAAC_CITY_ROOT', str(tmp_path))
    token = tmp_path / 'logs/vss-integration/bridge-token'
    token.parent.mkdir(parents=True)
    token.write_text('isolated-test-token')
    control = runpy.run_path(str(TOOLS / 'demo_control.py'))['DemoControl']()
    calls = []
    def request(url, payload, *, headers):
        calls.append((url, payload, headers))
        return {'ok': True, 'data': {'schemaVersion': 'city.tradeshow-control.v1'}}
    monkeypatch.setattr(control, '_json', request)
    assert control._bridge()['schemaVersion'] == 'city.tradeshow-control.v1'
    assert calls == [('http://127.0.0.1:8766/control', {'action': 'demo', 'operation': 'status'},
                      {'X-City-Token': 'isolated-test-token'})]


def test_mobility_default_export_uses_explicit_package_before_any_api_call(monkeypatch, tmp_path):
    monkeypatch.setenv('VSS_ISAAC_CITY_ROOT', str(tmp_path))
    monkeypatch.syspath_prepend(str(TOOLS))
    mobility = runpy.run_path(str(TOOLS / 'isaac_mobility.py'))
    monkeypatch.setattr(sys, 'argv', ['isaac_mobility.py'])
    with pytest.raises(FileNotFoundError) as error:
        mobility['main']()
    assert Path(error.value.filename) == tmp_path / 'logs/vss-integration/camera-map-export.json'


def test_relocation_preserves_saved_prepared_transaction(monkeypatch, tmp_path):
    monkeypatch.setenv('VSS_ISAAC_CITY_ROOT', str(tmp_path / 'city'))
    saved = {'transaction': {'boundaryId': 'retained-boundary', 'nativeRunId': 'native:001',
                             'phase': 'closed'}, 'requests': {'existing-request': {'operation': 'prepare'}}}
    state = tmp_path / 'prepared-control.json'
    original = json.dumps(saved)
    state.write_text(original)
    control = runpy.run_path(str(TOOLS / 'demo_control.py'))['DemoControl'](state_path=state)
    assert control.transaction == saved['transaction']
    assert control.requests == saved['requests']
    assert state.read_text() == original
