# SPDX-License-Identifier: Apache-2.0
import hashlib
import io
import json

import pytest

import freeze_live_tracking_window as collector


@pytest.fixture
def window(tmp_path, monkeypatch):
    monkeypatch.setattr(collector, 'ROOT', tmp_path)
    state = tmp_path/'.spark/city/state'
    (state/'native/mv3dt-demo').mkdir(parents=True)
    profile = state/'native/mv3dt-demo/active.json'
    profile.write_text('{}')
    (state/'runtime-tuning.json').write_text('{"muxTimeoutUs":10000}')
    capture = tmp_path/'capture'; capture.mkdir()
    (capture/'manifest.json').write_text(json.dumps(dict(result='complete', cameraOrder=['a','b'],
        nativeProfileSha256=hashlib.sha256(profile.read_bytes()).hexdigest())))
    (capture/'reference.ndjson').write_text(json.dumps(dict(sampleEndUnixNs='900000000'))+'\n'+
        json.dumps(dict(sampleStartUnixNs='3100000000'))+'\n')
    rows = [dict(sourceId=source, sourceSessionId='session-'+source, sequence=str(i), fusionEpoch='epoch',
        sourceTimeNs=str(1_000_000_000+i*(2_000_000_000//29)), modelRevision='model',
        timestampBasis='source-native-sei', trackingArchitecture='mv3dt-native-v1',
        detectorTrackerAudit=dict(inputSnapshotComplete=True)) for i in range(30) for source in ('a','b')]
    log = state/'live-observations.ndjson'
    def write():
        log.write_text(''.join(json.dumps(row)+'\n' for row in rows))
        stat = log.stat()
        (state/'live-observations.ndjson.manifest.json').write_text(json.dumps(dict(files=[
            dict(name=log.name, generation='1', inode=str(stat.st_ino), device=str(stat.st_dev))])))
    write()
    snapshot = dict(sources=[dict(id=source, status='live', lastSourceTimeNs='4000000000') for source in ('a','b')])
    monkeypatch.setattr(collector.urllib.request, 'urlopen', lambda *a, **kw: io.BytesIO(json.dumps(snapshot).encode()))
    return capture, tmp_path/'frozen', rows, write, state


def test_freeze_preserves_live_clock_and_never_changes_writer(window):
    capture, output, rows, _, state = window
    before = (state/'live-observations.ndjson').read_bytes()
    path = collector.freeze(capture, output)
    assert [json.loads(line) for line in path.read_text().splitlines()] == rows
    assert (state/'live-observations.ndjson').read_bytes() == before
    assert json.loads((output/'receipt.json').read_text())['clockBasis'] == 'source-native-sei'


@pytest.mark.parametrize('change', ['session', 'model', 'clock', 'detector-snapshot'])
def test_unqualified_live_windows_cannot_be_reported_complete(window, change):
    capture, output, rows, write, _ = window
    if change == 'session': rows[10]['sourceSessionId'] = 'restarted'
    if change == 'model': rows[10]['modelRevision'] = 'different'
    if change == 'clock': rows[10]['timestampBasis'] = 'arrival-pts-unsynchronized'
    if change == 'detector-snapshot': rows[10]['detectorTrackerAudit']['inputSnapshotComplete'] = False
    write()
    with pytest.raises(ValueError): collector.freeze(capture, output)
    assert not output.exists()


def test_rotation_during_collection_requires_a_retry(window):
    capture, output, _, _, state = window
    path = state/'live-observations.ndjson.manifest.json'; manifest = json.loads(path.read_text())
    manifest['files'][0]['inode'] = '0'; path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='rotated'): collector.freeze(capture, output)
    assert not output.exists()


def test_tuning_change_after_capture_is_rejected(window):
    capture, output, _, _, state = window
    path = capture/'manifest.json'; manifest = json.loads(path.read_text())
    manifest['runtimeTuningSha256'] = collector.sha(state/'runtime-tuning.json')
    path.write_text(json.dumps(manifest))
    (state/'runtime-tuning.json').write_text('{"muxTimeoutUs":50000}')
    with pytest.raises(ValueError, match='Runtime tuning changed'):
        collector.freeze(capture, output)
    assert not output.exists()
