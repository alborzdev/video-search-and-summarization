#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Compare simultaneous encoded-only capture paths without decoding any image.

Use the existing export-env Python (PyAV demux only). Matching AU hashes are
preferred; canonical VCL NAL hashes plus preserved native SEI identify AUs when
an intermediary adds/removes parameter sets or its own SEI. Clock differences
are reported, never rewritten or treated as physical exposure synchronization.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import statistics
import time
import uuid

MAX_PACKETS = 5000
MAX_FILE_BYTES = 128 * 1024 * 1024
MAX_AU_BYTES = 16 * 1024 * 1024
NTP_UNIX_NS = 2_208_988_800_000_000_000
NATIVE_UUID = uuid.uuid5(uuid.NAMESPACE_DNS, 'isaacsim.streaming.rtsp.sei_metadata').bytes


def avcc_nals(data, length_size=4):
    result, cursor = [], 0
    if length_size not in (1, 2, 4):
        raise ValueError('Unsupported AVCC NAL length field.')
    while cursor < len(data):
        if cursor + length_size > len(data):
            raise ValueError('Truncated AVCC length field.')
        size = int.from_bytes(data[cursor:cursor + length_size], 'big')
        cursor += length_size
        if size <= 0 or cursor + size > len(data):
            raise ValueError('Truncated/empty AVCC NAL.')
        result.append(data[cursor:cursor + size])
        cursor += size
    return result


def sei_payloads(nal):
    if not nal or nal[0] & 31 != 6:
        return []
    # Remove emulation-prevention bytes only in their defined 00 00 03 context.
    rbsp, zeros = bytearray(), 0
    for value in nal[1:]:
        if zeros >= 2 and value == 3:
            zeros = 0
            continue
        rbsp.append(value)
        zeros = zeros + 1 if value == 0 else 0
    cursor, result = 0, []
    while cursor < len(rbsp) and rbsp[cursor] != 0x80:
        kind, size = 0, 0
        for field in ('type', 'size'):
            total = 0
            while cursor < len(rbsp) and rbsp[cursor] == 255:
                total += 255
                cursor += 1
            if cursor >= len(rbsp):
                raise ValueError('Truncated SEI type/size.')
            total += rbsp[cursor]
            cursor += 1
            if field == 'type':
                kind = total
            else:
                size = total
        if cursor + size > len(rbsp):
            raise ValueError('Truncated SEI payload.')
        result.append((kind, bytes(rbsp[cursor:cursor + size])))
        cursor += size
    return result


def au_identity(data, length_size=4):
    nals = avcc_nals(data, length_size)
    vcl = [nal for nal in nals if nal[0] & 31 in (1, 2, 3, 4, 5)]
    digest = hashlib.sha256(b''.join(len(nal).to_bytes(4, 'big') + nal for nal in vcl)).hexdigest() if vcl else None
    native = []
    for nal in nals:
        for kind, value in sei_payloads(nal):
            if kind == 5 and value[:16] == NATIVE_UUID:
                item = json.loads(value[16:].rstrip(b'\x00').decode('utf-8'))
                native.append({key: item.get(key) for key in ('timestamp', 'frame_num', 'publish_sim_time_ns', 'timestamp_basis')})
    return {'vclSha256': digest, 'nalTypes': [nal[0] & 31 for nal in nals], 'nativeSei': native}


def reference_unix(row):
    ref = row.get('reference')
    if not ref or ref.get('timestampNs') is None:
        return None
    value = int(ref['timestampNs'])
    caps = ref['caps'].split(',', 1)[0].strip()
    if caps == 'timestamp/x-ntp':
        return value - NTP_UNIX_NS
    if caps == 'timestamp/x-unix':
        return value
    raise ValueError('Unknown reference clock caps.')


def read_capture(directory):
    import av
    manifest = json.loads((directory / 'capture.json').read_text())
    if manifest.get('status') != 'complete' or not manifest.get('eosFinalized') or manifest.get('errors'):
        raise ValueError(f'Capture is not complete/error-free: {directory}')
    result = {}
    for source in manifest['sources']:
        path = directory / source['file']
        if path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError('Capture file exceeds analysis byte bound.')
        sidecar_path = directory / source['timingFile']
        if sidecar_path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError('Sidecar exceeds analysis byte bound.')
        rows = [json.loads(line) for line in sidecar_path.read_text().splitlines()]
        rows = [row for row in rows if row.get('kind') == 'access-unit']
        if len(rows) > MAX_PACKETS:
            raise ValueError('Sidecar exceeds analysis packet bound.')
        count = 0
        with av.open(str(path)) as container:
            if len(container.streams.video) != 1:
                raise ValueError('Expected one video stream.')
            stream = container.streams.video[0]
            extra = stream.codec_context.extradata
            if stream.codec_context.name != 'h264' or not extra or extra[0] != 1 or len(extra) < 5:
                raise ValueError('Expected H264 with AVCDecoderConfigurationRecord.')
            length_size = (extra[4] & 3) + 1
            for packet in container.demux(stream):
                if not packet.size:
                    continue
                if count >= len(rows) or packet.size > MAX_AU_BYTES:
                    raise ValueError('Packet count/size exceeds analysis bound.')
                payload = bytes(packet)
                row = rows[count]
                if row['index'] != count or hashlib.sha256(payload).hexdigest() != row['payloadSha256']:
                    raise ValueError('Stored packet/sidecar correspondence failed.')
                row.update(au_identity(payload, length_size))
                row['referenceUnixNs'] = reference_unix(row)
                count += 1
        if count != len(rows):
            raise ValueError('Stored packet/sidecar count differs.')
        result[source['sourceId']] = rows
    return manifest, result


def stats_ms(values):
    values = sorted(value / 1_000_000 for value in values)
    if not values:
        return None
    return {'count': len(values), 'min': round(values[0], 4), 'p50': round(statistics.median(values), 4),
            'p90': round(values[math.ceil(len(values) * .9) - 1], 4), 'max': round(values[-1], 4)}


def native_key(row):
    native = row.get('nativeSei', [])
    if len(native) == 1 and native[0].get('timestamp') is not None and native[0].get('frame_num') is not None:
        return (str(native[0]['timestamp']), str(native[0]['frame_num']))
    return None


def compare(origin, proxy):
    result = {}
    for source in sorted(origin.keys() & proxy.keys()):
        a, b = origin[source], proxy[source]
        a_full = Counter(row['payloadSha256'] for row in a)
        a_vcl = Counter(row['vclSha256'] for row in a if row['vclSha256'])
        a_native = Counter(native_key(row) for row in a if native_key(row))
        b_full, b_vcl, b_native = defaultdict(list), defaultdict(list), defaultdict(list)
        for row in b:
            b_full[row['payloadSha256']].append(row)
            if row['vclSha256']:
                b_vcl[row['vclSha256']].append(row)
            if native_key(row):
                b_native[native_key(row)].append(row)
        used, matches, methods = set(), [], Counter()
        for row in a:
            candidates, method = (b_full[row['payloadSha256']] if a_full[row['payloadSha256']] == 1 else []), 'full-AU-sha256'
            if len(candidates) != 1:
                candidates, method = (b_native.get(native_key(row), []) if a_native[native_key(row)] == 1 else []), 'native-SEI-plus-VCL-sha256'
            if len(candidates) != 1:
                candidates, method = (b_vcl.get(row['vclSha256'], []) if a_vcl[row['vclSha256']] == 1 else []), 'unique-VCL-sha256'
            if len(candidates) != 1:
                continue
            peer = candidates[0]
            if peer['index'] in used or row['vclSha256'] != peer['vclSha256']:
                continue
            used.add(peer['index'])
            methods[method] += 1
            matches.append((row, peer))
        refs = [(x, y) for x, y in matches if x['referenceUnixNs'] is not None and y['referenceUnixNs'] is not None]
        result[source] = {'originPackets': len(a), 'proxyPackets': len(b), 'matchedSameVclAccessUnits': len(matches),
            'matchMethods': dict(methods), 'matchedNativeSeiIdentical': sum(x['nativeSei'] == y['nativeSei'] and bool(x['nativeSei']) for x, y in matches),
            'proxyMinusOriginReceiveMs': stats_ms([int(y['receivedUnixNs']) - int(x['receivedUnixNs']) for x, y in matches]),
            'proxyMinusOriginReceiveWithBothReferencesMs': stats_ms([int(y['receivedUnixNs']) - int(x['receivedUnixNs']) for x, y in refs]),
            'proxyMinusOriginReferenceMs': stats_ms([y['referenceUnixNs'] - x['referenceUnixNs'] for x, y in refs]),
            'originReceiveMinusOwnReferenceMs': stats_ms([int(x['receivedUnixNs']) - x['referenceUnixNs'] for x in a if x['referenceUnixNs'] is not None]),
            'proxyReceiveMinusOwnReferenceMs': stats_ms([int(x['receivedUnixNs']) - x['referenceUnixNs'] for x in b if x['referenceUnixNs'] is not None]),
            'nativeSeiPackets': {'origin': sum(bool(x['nativeSei']) for x in a), 'proxy': sum(bool(x['nativeSei']) for x in b)},
            'examples': [{'originIndex': x['index'], 'proxyIndex': y['index'], 'originReferenceUnixNs': str(x['referenceUnixNs']),
                          'proxyReferenceUnixNs': str(y['referenceUnixNs']), 'originNativeSei': x['nativeSei'],
                          'proxyNativeSei': y['nativeSei']} for x, y in refs[:2]]}
    return result


def compare_same_render_frame(sources):
    """Compare existing SEI only; a shared sim tick is not exposure-time proof."""
    if len(sources) != 2:
        raise ValueError('Cross-camera comparison requires exactly two sources.')
    source_ids = sorted(sources)
    lookup = []
    for source in source_ids:
        groups = defaultdict(list)
        for row in sources[source]:
            native = row.get('nativeSei', [])
            if len(native) == 1 and all(native[0].get(key) is not None for key in ('frame_num', 'publish_sim_time_ns', 'timestamp')):
                groups[(str(native[0]['frame_num']), str(native[0]['publish_sim_time_ns']))].append(row)
        lookup.append(groups)
    pairs = [(a[0], lookup[1][key][0]) for key, a in lookup[0].items()
             if len(a) == 1 and len(lookup[1].get(key, [])) == 1]
    return {'sourceOrder': source_ids, 'basis': 'Exact same SEI frame_num AND publish_sim_time_ns, unique in both sources.',
            'matchedRenderTicks': len(pairs),
            'secondMinusFirstNativeHandoffMs': stats_ms([int(b['nativeSei'][0]['timestamp']) - int(a['nativeSei'][0]['timestamp']) for a, b in pairs]),
            'secondMinusFirstReceiveMs': stats_ms([int(b['receivedUnixNs']) - int(a['receivedUnixNs']) for a, b in pairs]),
            'secondMinusFirstReferenceMs': stats_ms([b['referenceUnixNs'] - a['referenceUnixNs'] for a, b in pairs
                                                  if a['referenceUnixNs'] is not None and b['referenceUnixNs'] is not None])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin', type=Path, required=True)
    parser.add_argument('--proxy', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    a_manifest, origin = read_capture(args.origin)
    b_manifest, proxy = read_capture(args.proxy)
    receipt = {'schemaVersion': 'city.rtsp-path-clock-comparison.v1', 'analyzedAtUnixNs': str(time.time_ns()),
               'originCapture': str(args.origin), 'proxyCapture': str(args.proxy),
               'captureStatus': [a_manifest['status'], b_manifest['status']], 'decodeUsed': False,
               'note': 'Receive time is parsed-AU observation after independent 200ms client jitter buffers. Reference differences compare identical VCL AUs, not physical exposure truth.',
               'sources': compare(origin, proxy),
               'sameNativeRenderFrame': {'origin': compare_same_render_frame(origin), 'proxy': compare_same_render_frame(proxy)}}
    with args.output.open('x') as output:
        output.write(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
