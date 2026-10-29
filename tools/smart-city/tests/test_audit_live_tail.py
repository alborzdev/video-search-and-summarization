# SPDX-License-Identifier: Apache-2.0
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('audit_live_tail', Path(__file__).resolve().parents[1] / 'audit_live_tail.py')
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)
H = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
CAL = {source: {'calibrationRevision': 'cal', 'imageToGroundHomography': H} for source in ('a', 'b')}
READ = {'readEndUnixNs': '2000000000'}


def obj(name='person', target='7'):
    return {'class': name, 'localTrackId': target, 'observedThisFrame': True, 'bboxPx': [0, 0, 2, 2],
            'native3D': {'targetId': target, 'visibility': .8, 'worldPositionM': [1, 2],
                         'imageFootPx': [1, 2], 'calibrationRevision': 'cal'}}


def row(source, timestamp=1000000000, epoch='epoch', objects=None):
    return {'sourceId': source, 'sourceSessionId': source+'session', 'sourceTimeNs': str(timestamp),
            'timestampBasis': 'source-rtcp', 'fusionEpoch': epoch, 'objects': [obj()] if objects is None else objects}


class TailAuditTests(unittest.TestCase):
    def test_exact_same_class_id_pair(self):
        result = audit.analyze([row('a'), row('b')], CAL, READ)
        self.assertEqual(result['classes']['person']['50']['candidatePairs'], 1)
        self.assertEqual(result['classes']['person']['50']['worldWithin1M'], 1)

    def test_epoch_change_prevents_pair(self):
        result = audit.analyze([row('a', epoch='old'), row('b', epoch='new')], CAL, READ)
        self.assertEqual(result['classes']['person'], {})

    def test_native_capture_clocks_are_analyzed_without_relabeling_them(self):
        rows = [row('a'), row('b')]
        for value in rows:
            value.update(timestampBasis='source-native-sei', rawSourcePtsNs='123')
            value['sourceClockEvidence'] = dict(schemaVersion='city.source-native-sei.v1',
                method='isaac-native-sei-wall-capture', correlation='exact-au-pts',
                captureTimeNs=value['sourceTimeNs'], auPtsNs='123', frameCounter='42')
        result = audit.analyze(rows, CAL, READ)
        self.assertEqual(result['timestampBasis'], 'source-native-sei')
        self.assertEqual(result['classes']['person']['50']['candidatePairs'], 1)
        rows[1]['sourceClockEvidence']['captureTimeNs'] = '999'
        with self.assertRaisesRegex(ValueError, 'exact-AU'):
            audit.analyze(rows, CAL, READ)

    def test_mixed_clock_bases_cannot_create_pairs(self):
        rows = [row('a'), row('b')]
        rows[1]['timestampBasis'] = 'source-native-sei'
        result = audit.analyze(rows, CAL, READ)
        self.assertIsNone(result['timestampBasis'])
        self.assertEqual(result['classes']['person'], {})

    def test_skew_window_not_widened(self):
        rows = [row('a', 900000000), row('b', 1000000000), row('a', 1100000000), row('b', 1200000000)]
        result = audit.analyze(rows, CAL, READ)
        self.assertEqual(result['classes']['person']['50']['candidatePairs'], 0)
        self.assertEqual(result['classes']['person']['150']['candidatePairs'], 1)

    def test_cross_class_sdk_collision_is_not_joined(self):
        result = audit.analyze([row('a'), row('b', objects=[obj('car')])], CAL, READ)
        self.assertEqual(result['classes']['person']['50']['candidatePairs'], 0)
        self.assertEqual(result['pairing']['crossClassSameSdkId50Ms'], {'person/car': 1})

    def test_same_frame_ambiguous_sdk_id_is_rejected(self):
        result = audit.analyze([row('a', objects=[obj(), obj('car')]), row('b')], CAL, READ)
        self.assertEqual(result['classes']['person']['50']['candidatePairs'], 0)

    def test_tail_discards_partial_prefix_and_unfinished_last_row(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'observations.ndjson'
            raw = b'garbage' * 100 + b'\n' + json.dumps(row('a')).encode() + b'\n' + b'{"unfinished":'
            path.write_bytes(raw)
            rows, tail, read = audit.read_tail(path, maximum_bytes=500, maximum_rows=500)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['sourceId'], 'a')
            self.assertLessEqual(read['bytesRead'], 500)


if __name__ == '__main__':
    unittest.main()
