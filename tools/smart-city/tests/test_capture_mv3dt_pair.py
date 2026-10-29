# SPDX-License-Identifier: Apache-2.0
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import pytest

spec = importlib.util.spec_from_file_location('capture_pair_test', Path(__file__).parents[1] / 'capture_mv3dt_pair.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


@pytest.mark.parametrize('values', [[], ['a=rtsp://host/a'], ['a=rtsp://host/a', 'a=rtsp://host/b'],
    ['a=rtsp://host/a', 'b=rtsp://host/a'], ['../a=rtsp://host/a', 'b=rtsp://host/b'],
    ['a=file:///tmp/a', 'b=rtsp://host/b'], ['a=rtsp://host/a', 'b=rtsp://host/b', 'c=rtsp://host/c']])
def test_two_distinct_rtsp_sources_required(values):
    with pytest.raises(ValueError):
        m.sources(values)


def test_source_order_preserved():
    assert m.sources(['sw=rtsp://host/sw', 'ne=rtsps://host/ne']) == [('sw', 'rtsp://host/sw'), ('ne', 'rtsps://host/ne')]


def test_output_is_new_controlled_subdirectory_and_never_overwrites(tmp_path):
    result = m.output_directory('capture-1', tmp_path)
    assert result == tmp_path / 'capture-1'
    with pytest.raises(FileExistsError):
        m.output_directory('capture-1', tmp_path)
    with pytest.raises(ValueError):
        m.output_directory('../outside', tmp_path)


def buffer(pts, reference=None):
    return SimpleNamespace(pts=pts, dts=pts-5, duration=m.NONE, get_flags=lambda: 64,
        get_size=lambda: 256, extract_dup=lambda _offset, size: b'\x01' * size,
        get_reference_timestamp_meta=lambda _caps: reference)


def test_timing_preserves_large_integer_clocks_and_reference_caps_without_rebasing(monkeypatch):
    monkeypatch.setattr(m.time, 'time_ns', lambda: 1792770000123456789)
    reference = SimpleNamespace(reference=SimpleNamespace(to_string=lambda: 'timestamp/x-ntp'),
                                timestamp=3972770000123456789, duration=m.NONE)
    row = m.timing(buffer(1337123456789, reference), 'video/x-h264,alignment=au', 12, {'start': '4000'})
    assert row['ptsNs'] == '1337123456789' and row['dtsNs'] == '1337123456784'
    assert row['reference'] == {'caps': 'timestamp/x-ntp', 'timestampNs': '3972770000123456789', 'durationNs': None}
    assert row['receivedUnixNs'] == '1792770000123456789' and row['segment'] == {'start': '4000'}
    assert len(row['payloadSha256']) == 64
    assert 'source-rtcp' not in str(row) and 'sourceTimeNs' not in row


def test_missing_reference_is_explicit_not_replaced_with_receipt_time():
    row = m.timing(buffer(100), None, 0)
    assert row['reference'] is None and row['durationNs'] is None


def test_summary_keeps_original_first_last_values_and_flags_backward_clocks():
    state = {'accessUnits': 0, 'referenceAccessUnits': 0, 'referenceCaps': []}
    for pts, timestamp in [(100, 200), (300, 400), (250, 350)]:
        row = m.timing(buffer(pts, SimpleNamespace(reference=SimpleNamespace(to_string=lambda: 'timestamp/x-ntp'), timestamp=timestamp, duration=10)), None, 0)
        m.summarize(state, row)
    assert state['firstPtsNs'] == '100' and state['lastPtsNs'] == '250'
    assert state['firstReferenceNs'] == '200' and state['lastReferenceNs'] == '350'
    assert state['regressionsPtsNs'] == state['regressionsReferenceNs'] == 1
    assert state['referenceAccessUnits'] == 3 and state['referenceCaps'] == ['timestamp/x-ntp']


def test_mux_timing_is_container_ticks_with_separate_time_base_and_no_decode(monkeypatch):
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(stdout='{"packets":[{"pts":12000,"dts":12000},{"pts":13000,"dts":13000}],"streams":[{"time_base":"1/1000","codec_name":"h264"}]}')
    monkeypatch.setattr(m.subprocess, 'run', run)
    value = m.file_timestamps(Path('/test/a.mkv'))
    assert value['firstPacket']['pts'] == 12000 and value['lastPacket']['pts'] == 13000
    assert value['stream']['time_base'] == '1/1000'
    assert calls[0][1]['timeout'] == 5 and '-show_packets' in calls[0][0]
    assert 'not source NTP' in value['clockNote']


def test_missing_mux_probe_is_unqualified_and_preserves_capture(monkeypatch):
    def unavailable(*args, **kwargs):
        raise FileNotFoundError()
    monkeypatch.setattr(m.subprocess, 'run', unavailable)
    assert m.file_timestamps(Path('/test/a.mkv'))['status'] == 'unavailable'
