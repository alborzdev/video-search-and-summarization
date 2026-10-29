#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Read-only encoded-pair clock verification; use .spark/city/export-env/bin/python.

--capture NAME writes a new verification receipt inside that completed capture.
No payload/timestamp rewrites, decoding, GPU work or host-time synchronization.
"""
from __future__ import annotations
import argparse
from bisect import bisect_left
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parents[2]
MEDIA = ROOT / '.spark/city/media'
NTP_UNIX_NS = 2_208_988_800_000_000_000
MAX_SKEW_NS = 50_000_000
MAX_PACKETS = 50_000


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def demux(path):
    import av
    packets = []
    with av.open(str(path)) as container:
        videos = list(container.streams.video)
        if len(videos) != 1 or videos[0].codec_context.name != 'h264':
            raise ValueError('Expected exactly one H264 video stream.')
        stream = videos[0]
        stream_info = {'codec_name': 'h264', 'width': stream.codec_context.width,
                       'height': stream.codec_context.height, 'time_base': str(stream.time_base)}
        for packet in container.demux(stream):
            if not packet.size:
                continue  # PyAV flush sentinel is not an encoded packet.
            if len(packets) >= MAX_PACKETS or packet.size > 16 * 1024 * 1024:
                raise ValueError('Packet count/size exceeds the bounded capture contract.')
            basis = Fraction(packet.time_base)
            to_ns = lambda ticks: None if ticks is None else str(int(ticks * basis * 1_000_000_000))
            packets.append({'index': len(packets), 'pts': packet.pts, 'dts': packet.dts,
                            'timeBase': str(basis), 'ptsNs': to_ns(packet.pts), 'dtsNs': to_ns(packet.dts),
                            'bytes': packet.size, 'payloadSha256': hashlib.sha256(bytes(packet)).hexdigest()})
    return packets, stream_info


def inspect_file(path):
    packets, stream = demux(path)
    return {'status': 'read' if packets else 'no-packets', 'reader': 'pyav-demux-no-decode',
            'packetCount': len(packets), 'stream': stream,
            'firstPacket': packets[0] if packets else None, 'lastPacket': packets[-1] if packets else None,
            'clockNote': 'Container time-base ticks, not source NTP. Compare with access-unit sidecar before replay.'}


def reference_unix(reference):
    if not reference or reference.get('timestampNs') is None:
        return None
    caps = reference.get('caps', '').split(',', 1)[0].strip()
    value = int(reference['timestampNs'])
    # GstReferenceTimestampMeta timestamps are nanoseconds, not packed NTP64.
    # https://gstreamer.freedesktop.org/documentation/gstreamer/gstbuffer.html
    # https://gstreamer.freedesktop.org/documentation/rtponvif/rtponviftimestamp.html
    if caps == 'timestamp/x-ntp':
        value -= NTP_UNIX_NS
    elif caps != 'timestamp/x-unix':
        raise ValueError('Unknown reference epoch/caps; no UTC conversion applied.')
    if value < 0:
        raise ValueError('Reference clock precedes Unix epoch or has invalid units.')
    return value


def verify_source(units, packets, segments):
    issues, reference_issues, mapping = [], [], []
    result = {'packetCorrespondenceVerified': False, 'filePtsOffset': None,
              'referenceMappingAvailable': False, 'referencePrefixMissingPackets': 0,
              'referenceInteriorMissingPackets': 0, 'issues': issues, 'referenceIssues': reference_issues,
              'packets': mapping}
    if not units or len(units) != len(packets):
        issues.append('Access-unit and file packet counts differ or are empty.')
        return result
    offsets, quantums, previous_pts, previous_file, previous_ref = [], [], None, None, None
    first_reference = False
    for index, (unit, packet) in enumerate(zip(units, packets)):
        if unit.get('index') != index or not unit.get('payloadSha256') or unit['payloadSha256'] != packet['payloadSha256'] or unit.get('bytes') != packet['bytes']:
            issues.append(f'Packet {index}: payload/order/size correspondence failed.')
            break
        if unit.get('ptsNs') is None or packet.get('ptsNs') is None:
            issues.append(f'Packet {index}: PTS is absent.')
            break
        original, stored = int(unit['ptsNs']), int(packet['ptsNs'])
        if (previous_pts is not None and original <= previous_pts) or (previous_file is not None and stored <= previous_file):
            issues.append(f'Packet {index}: duplicate or reordered presentation timestamps.')
        previous_pts, previous_file = original, stored
        quantum = Fraction(packet['timeBase']) * 1_000_000_000
        if quantum <= 0 or quantum > 1_000_000:
            issues.append('Container time base is coarser than supported Matroska 1 ms units.')
        quantums.append(max(1, int(quantum)))
        offsets.append(stored - original)
        if index > 0 and unit.get('discontinuity'):
            issues.append(f'Packet {index}: interior discontinuity.')
        reference = unit.get('reference')
        try:
            utc = reference_unix(reference)
        except (ValueError, TypeError, KeyError) as exc:
            reference_issues.append(f'Packet {index}: {exc}')
            utc = None
        if utc is None:
            key = 'referenceInteriorMissingPackets' if first_reference else 'referencePrefixMissingPackets'
            result[key] += 1
        else:
            first_reference = True
            if previous_ref is not None and utc <= previous_ref:
                reference_issues.append(f'Packet {index}: reference timestamps are not strictly increasing.')
            previous_ref = utc
        mapping.append({'index': index, 'payloadSha256': packet['payloadSha256'],
                        'filePtsNs': str(stored), 'fileDtsNs': packet.get('dtsNs'),
                        'originalPtsNs': str(original), 'originalDtsNs': unit.get('dtsNs'),
                        'referenceCaps': (reference or {}).get('caps'),
                        'referenceTimestampNs': (reference or {}).get('timestampNs'),
                        'referenceUnixNs': None if utc is None else str(utc)})
    if len(segments) != 1 or segments[0].get('format') != 'time' or segments[0].get('rate') != 1 or segments[0].get('appliedRate') != 1:
        issues.append('Capture must have one unchanged unit-rate TIME segment.')
    if offsets:
        tolerance = max(quantums)
        low, high = max(offsets) - tolerance, min(offsets) + tolerance
        result['filePtsOffset'] = {'minNs': str(low), 'maxNs': str(high), 'quantizationToleranceNs': str(tolerance),
                                  'basis': 'file-PTS-minus-original-AU-PTS; interval reflects mux quantization, not an inter-camera fit'}
        if low > high:
            issues.append('No constant file/original PTS offset fits the mux quantization bound.')
    if result['referenceInteriorMissingPackets']:
        reference_issues.append('Reference metadata is missing after the first available reference.')
    if len({row['referenceCaps'] for row in mapping if row['referenceUnixNs'] is not None}) > 1:
        reference_issues.append('Reference clock caps changed inside one source capture.')
    result['packetCorrespondenceVerified'] = not issues and len(mapping) == len(units)
    result['referenceMappingAvailable'] = result['packetCorrespondenceVerified'] and not reference_issues and sum(row['referenceUnixNs'] is not None for row in mapping) >= 2
    return result


def shared_clock(sources):
    result = {'status': 'unqualified', 'maxAllowedSkewNs': str(MAX_SKEW_NS), 'comparedPackets': 0,
              'note': 'This tests stored-packet/reference offsets only. Native replay frame-clock correspondence and physical capture synchronization remain separate gates.'}
    if len(sources) != 2 or not all(source['referenceMappingAvailable'] for source in sources):
        return result
    series = [[row for row in source['packets'] if row['referenceUnixNs'] is not None] for source in sources]
    offsets = [int(row['referenceUnixNs']) - int(row['filePtsNs']) for rows in series for row in rows]
    low, high = min(offsets), max(offsets)
    result.update(referenceOffsetMinNs=str(low), referenceOffsetMaxNs=str(high), maximumOffsetSpreadNs=str(high-low), comparedPackets=len(offsets))
    overlap = [max(int(rows[0]['referenceUnixNs']) for rows in series), min(int(rows[-1]['referenceUnixNs']) for rows in series)]
    result['commonReferenceWindowNs'] = [str(value) for value in overlap]
    if overlap[0] >= overlap[1]:
        return result
    times = [[int(row['referenceUnixNs']) for row in rows] for rows in series]
    nearest, coverage = [], []
    for a, b in [(times[0], times[1]), (times[1], times[0])]:
        eligible, matched = 0, 0
        for value in a:
            if not overlap[0] <= value <= overlap[1]:
                continue
            index = bisect_left(b, value)
            distance = min(abs(b[j]-value) for j in [index-1, index] if 0 <= j < len(b))
            nearest.append(distance)
            eligible += 1
            matched += distance <= MAX_SKEW_NS
        coverage.append({'eligibleReferenceFrames': eligible, 'framesWithNeighborWithinLimit': matched})
    result['nearestReferenceFrameSkewMaxNs'] = str(max(nearest)) if nearest else None
    result['framePairCoverage'] = {'maximumPairSkewNs': str(MAX_SKEW_NS),
                                  'firstToSecond': coverage[0], 'secondToFirst': coverage[1],
                                  'note': 'Neighbor availability is coverage, not clock-offset validity. Each evaluated frame pair must still meet this unchanged skew limit.'}
    # Sparse/asynchronous capture may have large nearest-frame gaps even when
    # file PTS and reference UTC use one consistent offset. Do not fit offsets
    # per camera or substitute missing frames; the evaluator gates actual pairs.
    if high-low <= MAX_SKEW_NS:
        result['status'] = 'verified-reference-offsets'
    return result


def verify(directory):
    manifest_path = directory / 'capture.json'
    manifest_hash = sha256(manifest_path)
    manifest = json.loads(manifest_path.read_text())
    result = {'schemaVersion': 'city.encoded-pair-clock.v1', 'captureId': manifest['captureId'],
              'captureManifestSha256': manifest_hash, 'verifiedAtUnixNs': str(time.time_ns()),
              'replayAlignmentQualified': False, 'issues': [], 'sources': []}
    if manifest.get('status') != 'complete' or manifest.get('eosFinalized') is not True:
        result['issues'].append('Capture did not complete EOS finalization successfully.')
    for source in manifest.get('sources', []):
        paths = [directory / source[key] for key in ['file', 'timingFile']]
        if any(path.resolve().parent != directory.resolve() for path in paths):
            raise ValueError('Capture files must remain inside their capture directory.')
        file_path, sidecar = paths
        before = [sha256(path) for path in paths]
        rows = [json.loads(line) for line in sidecar.read_text().splitlines() if line.strip()]
        headers = [row for row in rows if row.get('kind') == 'header']
        units = [row for row in rows if row.get('kind') == 'access-unit']
        packets, stream = demux(file_path)
        row = verify_source(units, packets, [row for row in rows if row.get('kind') == 'segment'])
        row.update(sourceId=source['sourceId'], file=source['file'], timingFile=source['timingFile'],
                   fileSha256=before[0], timingSha256=before[1], stream=stream)
        if len(headers) != 1 or headers[0].get('sourceId') != source['sourceId'] or headers[0].get('captureId') != manifest['captureId']:
            row['issues'].append('Sidecar identity does not match the capture manifest.')
        if before != [sha256(path) for path in paths]:
            row['issues'].append('Capture files changed during verification.')
        if row['issues']:
            row.update(packetCorrespondenceVerified=False, referenceMappingAvailable=False)
        result['sources'].append(row)
    if len(result['sources']) != 2 or len({row['sourceId'] for row in result['sources']}) != 2:
        result['issues'].append('Exactly two distinct source recordings are required.')
    if sha256(manifest_path) != manifest_hash:
        result['issues'].append('Capture manifest changed during verification.')
    result['sharedClock'] = shared_clock(result['sources']) if not result['issues'] else {'status': 'unqualified'}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--capture', help='Capture directory name under .spark/city/media, or its absolute path')
    choice.add_argument('--inspect-file', type=Path, help='Read-only packet-clock summary for capture helper')
    args = parser.parse_args()
    if args.inspect_file:
        print(json.dumps(inspect_file(args.inspect_file)))
        return 0
    directory = Path(args.capture)
    directory = directory if directory.is_absolute() else MEDIA / directory
    directory = directory.resolve()
    if directory.parent != MEDIA.resolve():
        parser.error('Capture must be a direct child of .spark/city/media.')
    result = verify(directory)
    output = directory / f'clock-verification-{time.time_ns()}.json'
    with output.open('x') as target:
        json.dump(result, target, indent=2)
        target.write('\n')
    print(json.dumps({'receipt': str(output), 'sharedClock': result['sharedClock'], 'replayAlignmentQualified': False}))
    return 0 if not result['issues'] and result['sharedClock']['status'] == 'verified-reference-offsets' else 1


if __name__ == '__main__':
    raise SystemExit(main())
