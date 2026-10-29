# SPDX-License-Identifier: Apache-2.0
import importlib.util
import hashlib
import json
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
spec = importlib.util.spec_from_file_location('mv3dt_evaluator', Path(__file__).parents[1] / 'evaluate_mv3dt_probe.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_assignment_is_one_to_one_and_globally_optimal():
    assert sorted(module.assignment([[.1, .2], [.15, .9]])) == [(0, 1), (1, 0)]


def test_assignment_preserves_unmatched_and_empty_cases():
    assert module.assignment([[1.1, 2.], [.2, 4.]]) == [(1, 0)]
    assert module.assignment([]) == []
    assert module.assignment([[], []]) == []


def test_percentile_interpolates_without_hiding_outliers():
    assert module.percentile([0., 1., 2., 3., 100.], .95) > 80
    assert module.percentile([], .95) is None


def test_ndjson_accepts_whitespace_but_never_drops_incomplete_capture(tmp_path):
    path = tmp_path / 'observations.ndjson'
    path.write_text('{"value": 1}  \n\n{"value": 2}\n')
    assert module.read_ndjson(path) == [{'value': 1}, {'value': 2}]
    path.write_text('{"value": 1}\n{"value":')
    with pytest.raises(ValueError, match='line 2'):
        module.read_ndjson(path)


def test_ndjson_rejects_non_object_record(tmp_path):
    path = tmp_path / 'observations.ndjson'
    path.write_text('[]\n')
    with pytest.raises(ValueError, match='must be an object'):
        module.read_ndjson(path)


def scored_rows():
    return [dict(sourceId=source, sourceTimeNs=str(at), sourceSessionId=f'{source}-session', fusionEpoch='fusion')
            for at in (100, 200) for source in ('a', 'b')]


def test_scored_rows_allow_interleaved_two_camera_order():
    module.validate_scored_rows(scored_rows(), {'a': {}, 'b': {}})


@pytest.mark.parametrize('mutation,reason', [
    ({'sourceTimeNs': '100'}, 'strictly increase'),
    ({'sourceSessionId': 'restarted'}, 'source session'),
    ({'fusionEpoch': 'new-run'}, 'fusion epoch'),
    ({'sourceSessionId': ''}, 'explicit source and fusion epochs'),
    ({'sourceId': 'unknown'}, 'not in the supplied camera package'),
])
def test_scored_rows_refuse_false_identity_or_bisect_assumptions(mutation, reason):
    rows = scored_rows()
    rows[-1].update(mutation)
    with pytest.raises(ValueError, match=reason):
        module.validate_scored_rows(rows, {'a': {}, 'b': {}})


def test_scored_rows_require_both_camera_sources():
    with pytest.raises(ValueError, match='both calibrated cameras'):
        module.validate_scored_rows(scored_rows()[::2], {'a': {}, 'b': {}})


def test_saved_input_integrity_cannot_qualify_without_pinned_inputs(tmp_path):
    run = tmp_path / 'run'
    run.mkdir()
    package = tmp_path / 'package.json'
    package.write_text('{}')
    assert module.verify_run_inputs(run, package)['verified'] is False
    (run / 'invocation.json').write_text('{}')
    assert module.verify_run_inputs(run, package)['verified'] is False


def test_saved_input_integrity_rejects_mutated_calibration_or_gates(tmp_path):
    run = tmp_path / 'run'
    run.mkdir()
    package = tmp_path / 'package.json'
    gates = tmp_path / 'promotion-gates.json'
    package.write_text('{"calibration": "original"}')
    gates.write_text('{"threshold": 1}')
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (package, gates)}
    (run / 'invocation.json').write_text(json.dumps({'inputHashes': hashes}))
    assert module.verify_run_inputs(run, package)['verified'] is True
    for path in (package, gates):
        original = path.read_text()
        path.write_text('{}')
        with pytest.raises(ValueError, match='changed since the diagnostic invocation'):
            module.verify_run_inputs(run, package)
        path.write_text(original)


def recorded_fixture(tmp_path):
    media = tmp_path / 'media'
    capture = media / 'pair'
    capture.mkdir(parents=True)
    run = tmp_path / 'run'
    run.mkdir()
    manifest = {'captureId': 'pair', 'status': 'complete', 'eosFinalized': True, 'errors': [], 'sources': []}
    verification = {'schemaVersion': 'city.encoded-pair-clock.v1', 'captureId': 'pair', 'sources': [],
                    'sharedClock': {'status': 'verified-reference-offsets', 'maximumOffsetSpreadNs': '0'}}
    replay_inputs, command, rows = [], [], []
    for source in ('a', 'b'):
        file = capture / f'{source}.mkv'
        timing = capture / f'{source}.timing.ndjson'
        file.write_bytes(b'fixture-coded-payload')
        timing.write_text('{"kind":"fixture-timing"}\n')
        item = {'sourceId': source, 'file': file.name, 'timingFile': timing.name, 'accessUnits': 3}
        manifest['sources'].append(item)
        verification['sources'].append({**item, 'fileSha256': module.file_sha256(file),
            'timingSha256': module.file_sha256(timing), 'packetCorrespondenceVerified': True,
            'referenceMappingAvailable': True, 'referencePrefixMissingPackets': 1,
            'referenceInteriorMissingPackets': 0, 'referenceIssues': [],
            'packets': [{'index': i, 'payloadSha256': 'a' * 64, 'filePtsNs': str(i * 100_000_000),
                         'referenceUnixNs': None if i == 0 else str(1_700_000_000_000_000_000 + i * 100_000_000)}
                        for i in range(3)]})
        replay_inputs.append({'sourceId': source, 'containerUri': f'file:///media/pair/{source}.mkv',
                              'fileSha256': module.file_sha256(file)})
        command.extend(['--source', source + '=' + replay_inputs[-1]['containerUri']])
        for i in range(3):
            rows.append({'sourceId': source, 'sourceTimeNs': str(9_000_000_000 + i * 100_000_000),
                         'rawSourcePtsNs': str(i * 100_000_000), 'timestampBasis': 'recorded-pts',
                         'mediaTimeBasis': 'gstreamer-segment-stream-time', 'sourceSessionId': source, 'fusionEpoch': 'f'})
    (capture / 'capture.json').write_text(json.dumps(manifest))
    verification['captureManifestSha256'] = module.file_sha256(capture / 'capture.json')
    path = capture / 'clock.json'
    path.write_text(json.dumps(verification))
    invocation = {'replayInputs': replay_inputs, 'command': command,
                  'recordedClockVerificationSha256': module.file_sha256(path)}
    (run / 'invocation.json').write_text(json.dumps(invocation))
    (run / 'promotion-gates.json').write_text('{"maximumSourceClockSkewP95Ms": 50}')
    return media, run, path, rows, verification, invocation


def repin_verification(run, path, verification, invocation):
    path.write_text(json.dumps(verification))
    invocation['recordedClockVerificationSha256'] = module.file_sha256(path)
    (run / 'invocation.json').write_text(json.dumps(invocation))


def test_recorded_exact_packet_map_preserves_worker_clock_and_reports_unqualified_prefix(tmp_path):
    media, run, path, rows, _, _ = recorded_fixture(tmp_path)
    original = json.loads(json.dumps(rows))
    mapped, evidence = module.recorded_clock_rows(rows, run, path, ['a', 'b'], media_root=media)
    assert rows == original
    assert len(mapped) == 4
    assert evidence['prefixUnqualifiedObservations'] == 2
    assert evidence['sourceTimestampRewritten'] is False
    assert mapped[0]['sourceTimeNs'] == '9100000000'
    assert mapped[0]['evaluationTimeNs'] == '1700000000100000000'
    assert mapped[0]['timestampBasis'] == 'recorded-pts'
    module.validate_scored_rows(mapped, {'a': {}, 'b': {}})


@pytest.mark.parametrize('field,value,reason', [
    ('rawSourcePtsNs', '100000001', 'no exact verified stored-packet match'),
    ('timestampBasis', 'source-rtcp', 'unchanged recorded-pts'),
    ('mediaTimeBasis', 'source-relative-pts', 'unchanged recorded-pts'),
])
def test_recorded_mapping_never_fits_a_pts_offset_or_fabricates_basis(tmp_path, field, value, reason):
    media, run, path, rows, _, _ = recorded_fixture(tmp_path)
    rows[1][field] = value
    with pytest.raises(ValueError, match=reason):
        module.recorded_clock_rows(rows, run, path, ['a', 'b'], media_root=media)


@pytest.mark.parametrize('artifact', ['a.mkv', 'a.timing.ndjson', 'capture.json', 'clock.json'])
def test_recorded_mapping_rejects_changed_pinned_artifacts(tmp_path, artifact):
    media, run, path, rows, _, _ = recorded_fixture(tmp_path)
    with (path.parent / artifact).open('ab') as stream:
        stream.write(b' ')
    with pytest.raises(ValueError, match='changed|not pinned'):
        module.recorded_clock_rows(rows, run, path, ['a', 'b'], media_root=media)


def test_recorded_mapping_rejects_camera_reordering(tmp_path):
    media, run, path, rows, _, _ = recorded_fixture(tmp_path)
    with pytest.raises(ValueError, match='source order'):
        module.recorded_clock_rows(rows, run, path, ['b', 'a'], media_root=media)


def test_recorded_mapping_rejects_cross_camera_input_clock_misalignment(tmp_path):
    media, run, path, rows, verification, invocation = recorded_fixture(tmp_path)
    for packet in verification['sources'][1]['packets'][1:]:
        packet['referenceUnixNs'] = str(int(packet['referenceUnixNs']) + 51_000_000)
    verification['sharedClock']['maximumOffsetSpreadNs'] = '51000000'
    repin_verification(run, path, verification, invocation)
    with pytest.raises(ValueError, match='unchanged cross-camera skew gate'):
        module.recorded_clock_rows(rows, run, path, ['a', 'b'], media_root=media)


def test_recorded_mapping_rejects_interior_missing_clock_without_silent_filtering(tmp_path):
    media, run, path, rows, verification, invocation = recorded_fixture(tmp_path)
    verification['sources'][0]['packets'][2]['referenceUnixNs'] = None
    repin_verification(run, path, verification, invocation)
    with pytest.raises(ValueError, match='interior missing reference'):
        module.recorded_clock_rows(rows, run, path, ['a', 'b'], media_root=media)


def test_recorded_mapping_rejects_different_run_input_uri(tmp_path):
    media, run, path, rows, verification, invocation = recorded_fixture(tmp_path)
    invocation['command'][1] = 'a=file:///media/unrelated.mkv'
    repin_verification(run, path, verification, invocation)
    with pytest.raises(ValueError, match='actual replay source arguments'):
        module.recorded_clock_rows(rows, run, path, ['a', 'b'], media_root=media)


def test_gate_path_uses_pinned_candidate_snapshot(tmp_path):
    run = tmp_path / 'run'
    run.mkdir()
    assert module.gate_path(run) == tmp_path / 'promotion-gates.json'
    (run / 'promotion-gates.json').write_text('{}')
    assert module.gate_path(run) == run / 'promotion-gates.json'


def test_recorded_evaluation_uses_capture_time_not_replay_epoch(tmp_path, monkeypatch):
    media, run, path, rows, verification, invocation = recorded_fixture(tmp_path)
    package = {'cameras': [{'sourceId': source, 'width': 100, 'height': 100,
        'projectionMatrix3x4': [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0, 1]],
        'imageToGroundHomography': [[1, 0, 0], [0, 1, 0], [0, 0, 1]]} for source in ('a', 'b')]}
    package_path = run / 'package.json'
    package_path.write_text(json.dumps(package))
    gates = {'maximumSourceClockSkewP95Ms': 50, 'minimumRunSeconds': 120, 'minimumAvailableGiB': 23,
        'minimumPairedSamples': 2, 'maximumPersonPositionMedianM': .5, 'maximumPersonPositionP95M': 1.,
        'minimumMatchedPeople': 1, 'minimumDuplicateReductionFraction': .5}
    (run / 'promotion-gates.json').write_text(json.dumps(gates))
    invocation['inputHashes'] = {name: module.file_sha256(run / name) for name in ('package.json', 'promotion-gates.json')}
    repin_verification(run, path, verification, invocation)
    for row in rows:
        row['objects'] = [{'class': 'person', 'observedThisFrame': True, 'localTrackId': '0',
            'bboxPx': [15, 10, 10, 10], 'native3D': {'visibility': 1., 'worldPositionM': [20, 20]}}]
    (run / 'observations.ndjson').write_text(''.join(json.dumps(row) + '\n' for row in rows))
    (run / 'receipt.json').write_text(json.dumps({'completedWithoutRuntimeError': True, 'wallSeconds': 120, 'minimumAvailableGiB': 30}))
    truth = tmp_path / 'gt.ndjson'
    truth.write_text(json.dumps({'kind': 'simulator-ground-truth-evaluation-only'}) + '\n' + ''.join(
        json.dumps({'captureUnixNs': str(1_700_000_000_000_000_000 + i * 100_000_000),
                    'peopleWorldM': {'person': [20, 20, 0]}}) + '\n' for i in (1, 2)))
    original = module.recorded_clock_rows
    monkeypatch.setattr(module, 'recorded_clock_rows', lambda *args: original(*args, media_root=media))
    with pytest.raises(ValueError, match='require --recorded-clock'):
        module.evaluate(run, truth, package_path, warmup_seconds=0)
    result = module.evaluate(run, truth, package_path, warmup_seconds=0, recorded_clock=path)
    assert result['passed'] is True
    assert result['metrics']['matchedPersonObservations'] == 4
    assert result['clockEvidence']['prefixUnqualifiedObservations'] == 2
    assert result['clockEvidence']['sourceTimestampRewritten'] is False
