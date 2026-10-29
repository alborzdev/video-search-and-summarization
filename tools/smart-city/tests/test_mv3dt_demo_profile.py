import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('demo_profile', Path(__file__).parents[1] / 'mv3dt_demo_profile.py')
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


def profile(tmp_path):
    state = tmp_path / '.spark/city/state'
    directory = state / 'native/mv3dt-demo'
    directory.mkdir(parents=True)
    tracker = directory / 'tracker.yml'
    tracker.write_text('diagnostic: true\n')
    value = {'schemaVersion': 'city.mv3dt-demo.v1', 'enabled': True,
             'siteId': 'isaac-intersection-a', 'cameraOrder': ['southwest', 'northeast'],
             'cameraCalibrations': {'southwest': 'revision', 'northeast': 'revision'},
             'imageId': 'sha256:' + 'a' * 64, 'trackerConfig': 'native/mv3dt-demo/tracker.yml',
             'fileHashes': {'native/mv3dt-demo/tracker.yml': hashlib.sha256(tracker.read_bytes()).hexdigest()}}
    (directory / 'active.json').write_text(json.dumps(value))
    return value, directory


def test_profile_absent_is_default_pipeline(tmp_path):
    assert demo.load(tmp_path, 'spark') is None
    assert demo.gateway_environment(None) == {}
    assert demo.native_args(None, {}, live=True) == []


def test_explicit_manifest_and_single_camera_admission(tmp_path):
    value, _ = profile(tmp_path)
    assert demo.load(tmp_path, 'spark') == value
    assert demo.native_args(value, {'sources': [{'id': 'southwest'}]}, live=True) == []
    site = {'id': value['siteId'], 'sources': [
        {'id': source, 'calibrationRevision': 'revision'} for source in value['cameraOrder']]}
    assert demo.native_args(value, site, live=True)[0:2] == ['--tracker-mode', 'mv3dt-demo']
    assert demo.gateway_environment(value)['CITY_MV3DT_DEMO_ENABLED'] == 'true'


def test_changed_config_or_geometry_is_rejected(tmp_path):
    value, directory = profile(tmp_path)
    (directory / 'tracker.yml').write_text('changed: true\n')
    with pytest.raises(ValueError, match='config changed'):
        demo.load(tmp_path, 'spark')
    site = {'id': value['siteId'], 'sources': [
        {'id': source, 'calibrationRevision': 'wrong'} for source in value['cameraOrder']]}
    with pytest.raises(ValueError, match='calibration'):
        demo.native_args(value, site, live=True)
    site['sources'].reverse()
    with pytest.raises(ValueError, match='camera order'):
        demo.native_args(value, site, live=True)


def test_recorded_or_other_site_cannot_activate(tmp_path):
    value, _ = profile(tmp_path)
    site = {'id': value['siteId'], 'sources': [
        {'id': source, 'calibrationRevision': 'revision'} for source in value['cameraOrder']]}
    with pytest.raises(ValueError):
        demo.native_args(value, site, live=False)
    site['id'] = 'other'
    with pytest.raises(ValueError):
        demo.native_args(value, site, live=True)


def test_staged_profile_requires_explicit_architecture_and_separate_local_pin(tmp_path):
    value, directory = profile(tmp_path)
    local = directory / 'local-tracker.yml'
    local.write_text('stateEstimatorType: 1\n')
    value.update(trackingArchitecture='nvdcf-local-then-mv3dt-v1',
                 localTrackerConfig='native/mv3dt-demo/local-tracker.yml')
    value['fileHashes'][value['localTrackerConfig']] = hashlib.sha256(local.read_bytes()).hexdigest()
    (directory / 'active.json').write_text(json.dumps(value))
    assert demo.load(tmp_path, 'spark') == value
    site = {'id': value['siteId'], 'sources': [
        {'id': source, 'calibrationRevision': 'revision'} for source in value['cameraOrder']]}
    assert demo.native_args(value, site, live=True)[-2:] == [
        '--local-tracker-config', '/state/native/mv3dt-demo/local-tracker.yml']
    assert demo.native_args(value, {'sources': [site['sources'][0]]}, live=True) == []
    local.write_text('changed\n')
    with pytest.raises(ValueError, match='config changed'):
        demo.load(tmp_path, 'spark')


@pytest.mark.parametrize('architecture,local', [
    (None, 'native/mv3dt-demo/tracker.yml'), ('unknown', 'native/mv3dt-demo/tracker.yml'),
    ('nvdcf-local-then-mv3dt-v1', None), ('nvdcf-local-then-mv3dt-v1', 'unhashed.yml'),
    ('nvdcf-local-then-mv3dt-v1', 'native/mv3dt-demo/tracker.yml'),
])
def test_staged_incomplete_or_unpinned_config_rejected(tmp_path, architecture, local):
    value, directory = profile(tmp_path)
    value.update(trackingArchitecture=architecture, localTrackerConfig=local)
    (directory / 'active.json').write_text(json.dumps(value))
    with pytest.raises(ValueError, match='Staged tracking'):
        demo.load(tmp_path, 'spark')


def clock_profile(tmp_path, **controls):
    value, directory = profile(tmp_path)
    local = directory / 'local.yml'
    local.write_text('local: pinned\n')
    value.update(trackingArchitecture='nvdcf-local-then-mv3dt-v1',
        localTrackerConfig='native/mv3dt-demo/local.yml', **controls)
    value['fileHashes'][value['localTrackerConfig']] = hashlib.sha256(local.read_bytes()).hexdigest()
    (directory / 'active.json').write_text(json.dumps(value))
    return value


def test_explicit_clock_diagnostic_profile_preserves_default_mux_and_single_admission(tmp_path):
    value = clock_profile(tmp_path, sourceClockDiagnostics=True, muxSyncInputs=False,
        muxMaxLatencyNs=0, muxSyncInputsNtpNs=0)
    assert demo.load(tmp_path, 'spark') == value
    site = {'id': value['siteId'], 'sources': [
        {'id': source, 'calibrationRevision': 'revision'} for source in value['cameraOrder']]}
    args = demo.native_args(value, site, live=True)
    assert '--source-clock-diagnostics' in args and '--mux-sync-inputs' not in args
    assert args[-4:] == ['--mux-max-latency-ns', '0', '--mux-sync-inputs-ntp-ns', '0']
    assert demo.native_args(value, {'sources': [site['sources'][0]]}, live=True) == []


def test_explicit_mux_candidate_emits_nanosecond_values_without_enabling_diagnostics(tmp_path):
    value = clock_profile(tmp_path, muxSyncInputs=True, muxMaxLatencyNs=200_000_000,
        muxSyncInputsNtpNs=50_000_000)
    assert demo.load(tmp_path, 'spark') == value
    site = {'id': value['siteId'], 'sources': [
        {'id': source, 'calibrationRevision': 'revision'} for source in value['cameraOrder']]}
    args = demo.native_args(value, site, live=True)
    assert '--mux-sync-inputs' in args and '--source-clock-diagnostics' not in args
    assert args[-4:] == ['--mux-max-latency-ns', '200000000', '--mux-sync-inputs-ntp-ns', '50000000']


@pytest.mark.parametrize('key,value', [
    ('sourceClockDiagnostics', 1), ('muxSyncInputs', 'true'), ('muxMaxLatencyNs', True),
    ('muxMaxLatencyNs', -1), ('muxMaxLatencyNs', 1_000_000_001), ('muxSyncInputsNtpNs', 1.5),
    ('muxSyncInputsNtpNs', '50000000'),
])
def test_clock_controls_require_exact_types_and_bounded_nanoseconds(tmp_path, key, value):
    clock_profile(tmp_path, **{key: value})
    with pytest.raises(ValueError):
        demo.load(tmp_path, 'spark')


def test_clock_controls_cannot_enable_on_legacy_profile(tmp_path):
    value, directory = profile(tmp_path)
    value['sourceClockDiagnostics'] = True
    (directory / 'active.json').write_text(json.dumps(value))
    with pytest.raises(ValueError, match='staged native profile'):
        demo.load(tmp_path, 'spark')


def test_native_sei_clock_is_explicit_and_preserved_during_single_then_pair_admission(tmp_path):
    value = clock_profile(tmp_path, sourceClockMode='source-native-sei')
    assert demo.load(tmp_path, 'spark') == value
    site = {'id': value['siteId'], 'sources': [
        {'id': source, 'calibrationRevision': 'revision'} for source in value['cameraOrder']]}
    for source in site['sources']:
        assert demo.native_args(value, {**site, 'sources': [source]}, live=True) == ['--source-native-sei-clock']
    args = demo.native_args(value, site, live=True)
    assert args.count('--source-native-sei-clock') == 1
    assert '--local-tracker-config' in args and args[0:2] == ['--tracker-mode', 'mv3dt-demo']
    assert demo.gateway_environment(value)['CITY_SOURCE_CLOCK_MODE'] == 'source-native-sei'


@pytest.mark.parametrize('change', ['unknown-source', 'wrong-calibration', 'other-site', 'recorded', 'empty'])
def test_native_sei_single_admission_cannot_escape_its_pinned_isaac_scope(tmp_path, change):
    value = clock_profile(tmp_path, sourceClockMode='source-native-sei')
    site = {'id': value['siteId'], 'sources': [{'id': value['cameraOrder'][0], 'calibrationRevision': 'revision'}]}
    if change == 'unknown-source': site['sources'][0]['id'] = 'other'
    if change == 'wrong-calibration': site['sources'][0]['calibrationRevision'] = 'other'
    if change == 'other-site': site['id'] = 'other'
    if change == 'empty': site['sources'] = []
    with pytest.raises(ValueError, match='single-camera admission'):
        demo.native_args(value, site, live=change != 'recorded')


@pytest.mark.parametrize('mode', ['source-sei', True, None, 'source-rtcp-with-sei-fallback'])
def test_clock_mode_rejects_unknown_or_implicit_native_fallback(tmp_path, mode):
    clock_profile(tmp_path, sourceClockMode=mode)
    with pytest.raises(ValueError, match='sourceClockMode'):
        demo.load(tmp_path, 'spark')


def test_native_sei_requires_staged_pins_and_generic_default_stays_rtcp(tmp_path):
    value, directory = profile(tmp_path)
    assert demo.gateway_environment(value)['CITY_SOURCE_CLOCK_MODE'] == 'source-rtcp'
    value['sourceClockMode'] = 'source-native-sei'
    (directory / 'active.json').write_text(json.dumps(value))
    with pytest.raises(ValueError, match='pinned staged Isaac'):
        demo.load(tmp_path, 'spark')


def native_profile(tmp_path):
    value, directory = profile(tmp_path)
    value.update(trackingArchitecture=demo.NATIVE, sourceClockMode='source-native-sei',
        muxSyncInputs=False, muxMaxLatencyNs=0, muxSyncInputsNtpNs=0,
        singleCameraTrackerConfigs={source: value['trackerConfig'] for source in value['cameraOrder']})
    (directory / 'active.json').write_text(json.dumps(value))
    return value, directory


def test_native_tracker_diagnostics_are_explicit_and_typed(tmp_path):
    value, directory = native_profile(tmp_path)
    site = dict(id=value['siteId'], sources=[dict(id=s, calibrationRevision='revision') for s in value['cameraOrder']])
    assert '--tracker-diagnostics' not in demo.native_args(value, site, live=True)
    value['trackerDiagnostics'] = True
    (directory/'active.json').write_text(json.dumps(value))
    assert demo.load(tmp_path, 'spark')['trackerDiagnostics'] is True
    assert '--tracker-diagnostics' in demo.native_args(value, site, live=True)
    value['trackerDiagnostics'] = 'true'
    (directory/'active.json').write_text(json.dumps(value))
    with pytest.raises(ValueError, match='explicit boolean'):
        demo.load(tmp_path, 'spark')


def test_native_profile_has_no_two_dimensional_fallback_in_either_camera_order(tmp_path):
    value, _ = native_profile(tmp_path)
    assert demo.load(tmp_path, 'spark') == value
    sources = [{'id': s, 'calibrationRevision': 'revision'} for s in value['cameraOrder']]
    for selected in ([sources[0]], [sources[1]], sources):
        args = demo.native_args(value, dict(id=value['siteId'], sources=selected), live=True)
        assert args[:2] == ['--tracker-mode', 'mv3dt-demo']
        assert '--local-tracker-config' not in args
        assert args[args.index('--tracking-architecture') + 1] == demo.NATIVE
        assert '--source-native-sei-clock' in args
    with pytest.raises(ValueError):
        demo.native_args(value, dict(id=value['siteId'], sources=sources[::-1]), live=True)
    with pytest.raises(ValueError):
        demo.native_args(value, dict(id=value['siteId'], sources=[]), live=True)


def test_native_car_truck_family_is_explicit_and_applies_to_single_admission(tmp_path):
    value, directory = native_profile(tmp_path)
    sources = [{'id': s, 'calibrationRevision': 'revision'} for s in value['cameraOrder']]
    assert '--native-car-truck-family' not in demo.native_args(value, dict(id=value['siteId'], sources=sources), live=True)
    value['trackingClassPolicy'] = 'car-truck-family-v1'
    (directory/'active.json').write_text(json.dumps(value))
    assert demo.load(tmp_path, 'spark') == value
    for selected in ([sources[0]], [sources[1]], sources):
        assert '--native-car-truck-family' in demo.native_args(value, dict(id=value['siteId'], sources=selected), live=True)
    value['trackingClassPolicy'] = 'all-classes'
    (directory/'active.json').write_text(json.dumps(value))
    with pytest.raises(ValueError, match='Car/truck association'):
        demo.load(tmp_path, 'spark')


@pytest.mark.parametrize('change', ['extra-local', 'missing-single', 'unpinned-single', 'unknown-single'])
def test_native_profile_rejects_local_stage_and_incomplete_camera_pins(tmp_path, change):
    value, directory = native_profile(tmp_path)
    if change == 'extra-local': value['localTrackerConfig'] = value['trackerConfig']
    if change == 'missing-single': value['singleCameraTrackerConfigs'].pop('southwest')
    if change == 'unpinned-single': value['singleCameraTrackerConfigs']['southwest'] = 'unhashed.yml'
    if change == 'unknown-single': value['singleCameraTrackerConfigs']['unknown'] = value['trackerConfig']
    (directory / 'active.json').write_text(json.dumps(value))
    with pytest.raises(ValueError, match='Native MV3DT'):
        demo.load(tmp_path, 'spark')


def test_native_auxiliary_weights_and_engine_are_pinned_before_start(tmp_path):
    value, directory = native_profile(tmp_path)
    model = tmp_path/'.spark/city/models/pose/fixture.engine'
    model.parent.mkdir(parents=True);model.write_bytes(b'fixture-engine')
    value['auxiliaryModelAssets'] = {'pose/fixture.engine': dict(bytes=model.stat().st_size,
        sha256=hashlib.sha256(model.read_bytes()).hexdigest())}
    (directory/'active.json').write_text(json.dumps(value))
    assert demo.load(tmp_path,'spark') == value
    model.write_bytes(b'changed-engine')
    with pytest.raises(ValueError,match='Auxiliary tracking model'):
        demo.load(tmp_path,'spark')
    value['auxiliaryModelAssets'] = {'../../../../outside.engine': dict(bytes=1,sha256='f'*64)}
    (directory/'active.json').write_text(json.dumps(value))
    with pytest.raises(ValueError,match='Auxiliary tracking model'):
        demo.load(tmp_path,'spark')
