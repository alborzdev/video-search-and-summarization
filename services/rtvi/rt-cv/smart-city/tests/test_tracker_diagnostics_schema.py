#!/usr/bin/env python3
"""Validate CPU production-callback output from tracker-diagnostics-test stdin."""
import json
from pathlib import Path
import sys

from jsonschema import Draft202012Validator


def reject_nonfinite(value):
    raise ValueError(f'Non-finite JSON token: {value}')


schema = json.loads((Path(__file__).parents[1] / 'schemas/tracker-diagnostics-v1.schema.json').read_text())
Draft202012Validator.check_schema(schema)
validator = Draft202012Validator(schema)
rows = [json.loads(line, parse_constant=reject_nonfinite) for line in sys.stdin if line.startswith('{')]
assert len(rows) == 4, 'Expected three production observations and one bounded serializer control'
assert 'trackerDiagnostics' not in rows[0]
assert rows[0]['objects'] == rows[1]['objects'], 'Diagnostics must preserve production objects'
assert len(rows[0]['objects']) == 1 and rows[0]['objects'][0]['class'] == 'bus'
for row in rows[1:3]:
    value = row['trackerDiagnostics']
    validator.validate(value)
    assert value['sdkFrameNumber'] == row['sourceFrameId'] == '7'
    assert value['sdkNtpTimestampNs'] == row['sourceTimeNs']
    assert value['sdkBufPtsNs'] == row['rawSourcePtsNs']
    assert value['sourceImageSize'] == [1920, 1080]
    assert value['processingImageSize'] == [960, 540]
    assert value['rawObjectCount'] == value['exportedObjectCount'] == 3 and not value['truncated']
    assert sorted(obj['sdkClassId'] for obj in value['objects']) == [0, 2, 4]
    for obj in value['objects']:
        assert obj['detectorBboxPx'] == [20, 40, 60, 80]
        assert obj['trackerBboxPx'] == [22, 42, 62, 82]
        assert obj['rectBboxPx'] == [24, 44, 64, 84]
        assert obj['nativeWorldFootM'] == [1.25, 2.5] and obj['nativeImageFootPx'] == [30, 50]
    assert next(obj for obj in value['objects'] if obj['sdkClassId'] == 4)['sdkTargetId'] == '9007199254740993', 'Do not round 64-bit IDs'
assert {obj['sdkClassId']: obj['idRejectedAsAmbiguous'] for obj in rows[1]['trackerDiagnostics']['objects']} == {0: True, 2: True, 4: False}
assert len(rows[2]['objects']) == 3, 'Diagnostic mode preserves its previous raw-object contract'
validator.validate(rows[3])
assert rows[3]['rawObjectCount'] == 257 and rows[3]['exportedObjectCount'] == 256 and rows[3]['truncated']
assert rows[3]['sdkNtpTimestampNs'] is None
for obj in rows[3]['objects']:
    assert obj['sdkTargetId'] == '18446744073709551615'
    assert all(obj[key] is None for key in ('detectorBboxPx', 'rectBboxPx', 'nativeWorldFootM', 'nativeVisibility'))
print(json.dumps({'status': 'passed', 'scope': 'CPU production callback plus strict JSON schema; no GPU',
                  'controls': ['default-off', 'production-objects-unchanged', 'all-class-raw-IDs', 'collision-provenance',
                               'independent-bboxes', 'native-feet', 'clock-frame-identity', '64-bit-ID-strings',
                               'finite-or-null', '256-object-bound']}))
