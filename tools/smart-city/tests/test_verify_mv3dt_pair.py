# SPDX-License-Identifier: Apache-2.0
from copy import deepcopy
import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('verify_pair_test', Path(__file__).parents[1] / 'verify_mv3dt_pair.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
SEGMENTS = [{'format': 'time', 'rate': 1.0, 'appliedRate': 1.0}]
UTC = 1_792_777_600_000_000_000


def sample(prefix=0, offset=2_000_000, clock_offset=0):
    units, packets = [], []
    for index in range(5):
        pts = 123_456_789 + index * 66_666_667
        stored = pts // 1_000_000 * 1_000_000 + offset
        reference = {'caps': 'timestamp/x-ntp', 'timestampNs': str(UTC + pts + clock_offset + m.NTP_UNIX_NS)} if index >= prefix else None
        units.append({'index': index, 'ptsNs': str(pts), 'dtsNs': str(pts), 'bytes': 100,
                      'payloadSha256': str(index)*64, 'reference': reference, 'discontinuity': index == 0})
        packets.append({'index': index, 'ptsNs': str(stored), 'dtsNs': str(stored), 'bytes': 100,
                        'payloadSha256': str(index)*64, 'timeBase': '1/1000'})
    return units, packets


def test_payload_verified_offset_retains_exact_reference_mapping_and_quantization_interval():
    units, packets = sample()
    row = m.verify_source(units, packets, SEGMENTS)
    assert row['packetCorrespondenceVerified'] and row['referenceMappingAvailable']
    assert int(row['filePtsOffset']['minNs']) <= 2_000_000 <= int(row['filePtsOffset']['maxNs'])
    assert row['filePtsOffset']['quantizationToleranceNs'] == '1000000'
    assert row['packets'][0]['originalPtsNs'] == units[0]['ptsNs']
    assert row['packets'][0]['filePtsNs'] == packets[0]['ptsNs']
    assert row['packets'][0]['referenceUnixNs'] == str(UTC+int(units[0]['ptsNs']))


def test_initial_missing_references_are_explicit_but_interior_loss_fails():
    units, packets = sample(prefix=2)
    row = m.verify_source(units, packets, SEGMENTS)
    assert row['referenceMappingAvailable'] and row['referencePrefixMissingPackets'] == 2
    assert row['packets'][0]['referenceUnixNs'] is None
    units[3]['reference'] = None
    row = m.verify_source(units, packets, SEGMENTS)
    assert not row['referenceMappingAvailable'] and row['referenceInteriorMissingPackets'] == 1


@pytest.mark.parametrize('kind', ['hash', 'order', 'size', 'count', 'pts', 'discontinuity', 'segments', 'drift'])
def test_correspondence_or_timeline_failure_is_never_fitted_away(kind):
    units, packets = sample()
    segments = deepcopy(SEGMENTS)
    if kind == 'hash': packets[2]['payloadSha256'] = 'changed'
    if kind == 'order': units[1]['index'] = 4
    if kind == 'size': packets[2]['bytes'] = 101
    if kind == 'count': packets.pop()
    if kind == 'pts': packets[2]['ptsNs'] = packets[1]['ptsNs']
    if kind == 'discontinuity': units[2]['discontinuity'] = True
    if kind == 'segments': segments.append(deepcopy(SEGMENTS[0]))
    if kind == 'drift': packets[-1]['ptsNs'] = str(int(packets[-1]['ptsNs'])+3_000_000)
    row = m.verify_source(units, packets, segments)
    assert not row['packetCorrespondenceVerified'] and not row['referenceMappingAvailable']


def test_reference_epoch_is_explicit_and_unknown_caps_never_use_receipt_time():
    assert m.reference_unix({'caps': 'timestamp/x-unix', 'timestampNs': str(UTC)}) == UTC
    assert m.reference_unix({'caps': 'timestamp/x-ntp, host=(string)clock', 'timestampNs': str(UTC+m.NTP_UNIX_NS)}) == UTC
    with pytest.raises(ValueError): m.reference_unix({'caps': 'timestamp/x-driver', 'timestampNs': str(UTC)})
    units, packets = sample()
    units[2]['reference']['caps'] = 'timestamp/x-driver'
    assert not m.verify_source(units, packets, SEGMENTS)['referenceMappingAvailable']


def test_shared_gate_rejects_different_file_offsets_even_when_each_file_is_individually_consistent():
    a = m.verify_source(*sample(offset=0), SEGMENTS)
    b = m.verify_source(*sample(offset=200_000_000), SEGMENTS)
    assert a['referenceMappingAvailable'] and b['referenceMappingAvailable']
    result = m.shared_clock([a,b])
    assert result['status'] == 'unqualified' and int(result['maximumOffsetSpreadNs']) > 50_000_000


def test_shared_reference_gate_checks_overlap_and_real_reference_clocks_not_host_start():
    a = m.verify_source(*sample(), SEGMENTS)
    b = m.verify_source(*sample(clock_offset=10_000_000), SEGMENTS)
    result = m.shared_clock([a,b])
    assert result['status'] == 'verified-reference-offsets'
    assert result['nearestReferenceFrameSkewMaxNs'] == '10000000'
    assert 'replayAlignmentQualified' not in result
    b = m.verify_source(*sample(clock_offset=10_000_000_000), SEGMENTS)
    assert m.shared_clock([a,b])['status'] == 'unqualified'


def test_no_or_reordered_reference_clocks_remain_unqualified():
    units, packets = sample(prefix=5)
    assert not m.verify_source(units, packets, SEGMENTS)['referenceMappingAvailable']
    units, packets = sample()
    units[-1]['reference'] = units[0]['reference']
    assert not m.verify_source(units, packets, SEGMENTS)['referenceMappingAvailable']


def test_missing_frames_reduce_pair_coverage_without_invalidating_a_common_clock_offset():
    a = m.verify_source(*sample(), SEGMENTS)
    b = deepcopy(a)
    b['packets'] = [b['packets'][0], b['packets'][-1]]
    result = m.shared_clock([a,b])
    assert result['status'] == 'verified-reference-offsets'
    assert int(result['maximumOffsetSpreadNs']) < 1_000_000
    assert int(result['nearestReferenceFrameSkewMaxNs']) > 50_000_000
    assert result['framePairCoverage']['maximumPairSkewNs'] == '50000000'
    assert result['framePairCoverage']['firstToSecond'] == {'eligibleReferenceFrames': 5, 'framesWithNeighborWithinLimit': 2}
    assert result['framePairCoverage']['secondToFirst'] == {'eligibleReferenceFrames': 2, 'framesWithNeighborWithinLimit': 2}
