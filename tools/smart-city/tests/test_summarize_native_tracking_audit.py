# SPDX-License-Identifier: Apache-2.0
from copy import deepcopy
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).parents[1]))
from summarize_native_tracking_audit import summarize


def frame(sequence=0, objects=True):
    return {'sourceId': 'camera', 'sourceSessionId': 'session', 'modelRevision': 'weights',
        'trackingEpoch': 'tracking', 'fusionEpoch': 'fusion', 'sequence': str(sequence),
        'sourceTimeNs': str(1_000_000_000 + sequence * 100_000_000),
        'objects': [{'class': 'person', 'localTrackId': '18446744073709551614', 'observedThisFrame': True}] if objects else [],
        'detectorTrackerAudit': {'schemaVersion': 'city.detector-tracker-audit.v1',
            'inputSnapshotComplete': True, 'outputSnapshotComplete': True, 'inputDetectionCount': 2,
            'inputs': [{'ordinal': 1, 'sdkClassId': 0, 'confidence': .8, 'bboxPx': [1, 2, 10, 20]},
                       {'ordinal': 2, 'sdkClassId': 0, 'confidence': .4, 'bboxPx': [10, 20, 20, 40]}],
            'rawSdkOutputCount': 1, 'outputs': [{'sdkTargetId': '18446744073709551614', 'sdkClassId': 0,
                'sdkDetectorConfidencePresent': True, 'stampPresent': True, 'currentDetectorStamp': True,
                'inputOrdinal': 1, 'untracked': False, 'idRejectedAsAmbiguous': False}]}}


class NativeTrackingAuditTest(unittest.TestCase):
    def test_unreturned_inputs_and_published_gaps_are_distinct(self):
        rows = [frame(i, objects=i != 1) for i in range(3)]
        result = summarize(rows)['sources']['camera']
        self.assertEqual(result['counts']['detectorInputs'], 6)
        self.assertEqual(result['counts']['currentDetectorOutputs'], 3)
        self.assertEqual(result['counts']['inputsNotReturnedAsCurrentSdkObject'], 3)
        self.assertEqual(result['continuityDiagnostic']['returnGapCount'], 1)
        self.assertEqual(result['continuityDiagnostic']['returnGapMedianMs'], 200)

    def test_confidence_does_not_substitute_for_exact_stamp(self):
        row = frame(); output = row['detectorTrackerAudit']['outputs'][0]
        output.update(currentDetectorStamp=False, inputOrdinal=None, stampPresent=False)
        counts = summarize([row])['sources']['camera']['counts']
        self.assertEqual(counts['sdkConfidenceWithoutCurrentStamp'], 1)
        self.assertEqual(counts['currentDetectorOutputs'], 0)
        self.assertEqual(counts['inputsNotReturnedAsCurrentSdkObject'], 2)

    def test_epoch_reset_never_bridges_an_id_gap(self):
        a, b = frame(), frame(2); b['trackingEpoch'] = 'new-tracking'
        summary = summarize([a, b])['sources']['camera']
        self.assertEqual(summary['epochCount'], 2)
        self.assertEqual(summary['continuityDiagnostic']['returnGapCount'], 0)

    def test_partial_duplicate_or_invalid_provenance_is_rejected(self):
        for change in ('partial', 'duplicate-input', 'invalid-output', 'wrong-class'):
            with self.subTest(change=change):
                row = frame(); audit = row['detectorTrackerAudit']
                if change == 'partial': audit['outputSnapshotComplete'] = False
                if change == 'duplicate-input': audit['inputs'][1]['ordinal'] = 1
                if change == 'invalid-output': audit['outputs'][0]['inputOrdinal'] = 3
                if change == 'wrong-class': audit['outputs'][0]['sdkClassId'] = 2
                with self.assertRaises(ValueError): summarize([row])
        with self.assertRaises(ValueError): summarize([frame(), deepcopy(frame())])


if __name__ == '__main__': unittest.main()
