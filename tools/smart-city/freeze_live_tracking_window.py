#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Freeze a completed reference capture's live diagnostic observations for scoring.

This is a read-only consumer of the managed detector log. It neither starts
inference nor changes clocks, identities, simulator state or retained logs.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze(capture, output):
    manifest = json.loads((capture/'manifest.json').read_text())
    if manifest.get('result') != 'complete':
        raise ValueError('A completed independent reference capture is required')
    profile_path = ROOT/'.spark/city/state/native/mv3dt-demo/active.json'
    if sha(profile_path) != manifest['nativeProfileSha256']:
        raise ValueError('The native configuration changed during this window')
    tuning_path = ROOT/'.spark/city/state/runtime-tuning.json'
    if manifest.get('runtimeTuningSha256') and sha(tuning_path) != manifest['runtimeTuningSha256']:
        raise ValueError('Runtime tuning changed after the reference capture')
    samples = [json.loads(line) for line in (capture/'reference.ndjson').read_text().splitlines()]
    first = int(samples[0]['sampleEndUnixNs'])+100_000_000
    last = int(samples[-1]['sampleStartUnixNs'])-100_000_000
    with urllib.request.urlopen('http://127.0.0.1:9184/api/v1/city/snapshot', timeout=3) as response:
        snapshot = json.load(response)
    sources = manifest['cameraOrder']
    current = {source['id']: source for source in snapshot['sources']}
    if any(source not in current or current[source].get('status') != 'live'
           or int(current[source].get('lastSourceTimeNs', '0')) <= last for source in sources):
        raise ValueError('Both live clocks must have advanced past the completed capture')
    state = ROOT/'.spark/city/state'
    rotation = json.loads((state/'live-observations.ndjson.manifest.json').read_text())
    rows = []
    inputs = []
    for item in sorted(rotation['files'], key=lambda value: int(value['generation'])):
        path = state/item['name']
        stat = path.stat()
        if str(stat.st_ino) != item['inode'] or str(stat.st_dev) != item['device']:
            raise ValueError('Observation log rotated while opening the frozen window; retry')
        inputs.append(dict(name=path.name, inode=item['inode'], generation=item['generation']))
        with path.open() as source:
            for line in source:
                if not line.endswith('\n'):
                    break  # Only the current writer's unfinished final record.
                row = json.loads(line)
                if row['sourceId'] in sources and first <= int(row['sourceTimeNs']) <= last:
                    if (row['timestampBasis'] != 'source-native-sei' or not row.get('detectorTrackerAudit', {}).get('inputSnapshotComplete')
                            or row.get('trackingArchitecture') != 'mv3dt-native-v1'):
                        raise ValueError('Current native clock, architecture and raw detector diagnostics are required')
                    rows.append(row)
    if len({row['fusionEpoch'] for row in rows}) != 1:
        raise ValueError('A single uninterrupted native tracking epoch is required')
    for source in sources:
        selected = [row for row in rows if row['sourceId'] == source]
        if (len(selected) < 30 or len({row['sourceSessionId'] for row in selected}) != 1
                or len({row['modelRevision'] for row in selected}) != 1
                or int(selected[0]['sourceTimeNs'])-first > 500_000_000
                or last-int(selected[-1]['sourceTimeNs']) > 500_000_000
                or any(not 0 < int(b['sourceTimeNs'])-int(a['sourceTimeNs']) <= 500_000_000 for a,b in zip(selected,selected[1:]))):
            raise ValueError('Live window has a session/model change, clock gap or incomplete coverage')
    if len({(row['sourceId'], row['sourceSessionId'], row['sequence']) for row in rows}) != len(rows):
        raise ValueError('Duplicate observation records in the live window')
    output.mkdir(parents=True, exist_ok=False)
    observations = output/'observations.ndjson'
    observations.write_text(''.join(json.dumps(row)+'\n' for row in rows))
    receipt = dict(schemaVersion='city.live-tracking-window.v1', result='complete',
        capture=str(capture), clockBasis='source-native-sei', firstCaptureNs=str(first), lastCaptureNs=str(last),
        sourceRows=dict(Counter(row['sourceId'] for row in rows)),
        activeProfileSha256=sha(profile_path), referenceManifestSha256=sha(capture/'manifest.json'),
        referenceSha256=sha(capture/'reference.ndjson'), observationsSha256=sha(observations),
        runtimeTuningSha256=sha(tuning_path), runtimeTuningBoundAtCapture=bool(manifest.get('runtimeTuningSha256')),
        logGenerations=inputs,
        collectorSha256=sha(Path(__file__)),
        limits='Conditional raw-image correspondence only. Different live windows contain different traffic; not a paired model benchmark.')
    (output/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(receipt, indent=2))
    return observations


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    freeze(args.capture.resolve(), args.output.resolve())
