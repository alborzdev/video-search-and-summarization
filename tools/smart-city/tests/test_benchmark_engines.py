# SPDX-License-Identifier: Apache-2.0
import importlib.util
from pathlib import Path
import sys
import unittest
import numpy as np

spec = importlib.util.spec_from_file_location('benchmark_engines', Path(__file__).parents[1] / 'benchmark_engines.py')
module = importlib.util.module_from_spec(spec);sys.modules[spec.name] = module;spec.loader.exec_module(module)


def values():
    boxes = np.array([[[.2,.5,.1,.4], [.6,.5,.3,.3]]], dtype=np.float32)
    logits = np.full((1, 2, 91), -100., dtype=np.float32)
    logits[0, 0, 1] = 5.;logits[0, 1, 6] = 4.
    return {'dets': boxes, 'labels': logits}


class BenchmarkControls(unittest.TestCase):
    def test_query_permutation_does_not_change_prediction_set(self):
        ref = values();actual = {name: value[:, ::-1].copy() for name, value in ref.items()}
        report = module.compare_outputs(ref, actual, 1)
        self.assertTrue(report['passed'])
        self.assertFalse(report['rawTensorDiagnostics']['dets']['elementwiseAllcloseAtol0_002Rtol0_001'])

    def test_class_change_fails(self):
        ref = values();actual = {k: v.copy() for k, v in ref.items()}
        actual['labels'][0, 0, 1] = -100;actual['labels'][0, 0, 8] = 5.
        self.assertFalse(module.compare_outputs(ref, actual, 1)['passed'])

    def test_box_displacement_fails(self):
        ref = values();actual = {k: v.copy() for k, v in ref.items()}
        actual['dets'][0, 0, 0] = .8
        self.assertFalse(module.compare_outputs(ref, actual, 1)['passed'])

    def test_score_shift_fails(self):
        ref = values();actual = {k: v.copy() for k, v in ref.items()}
        actual['labels'][0, 0, 1] = 1
        self.assertFalse(module.compare_outputs(ref, actual, 1)['passed'])

    def test_empty_positive_fails(self):
        ref = values();actual = {k: v.copy() for k, v in ref.items()};actual['labels'][:] = -100
        with self.assertRaisesRegex(ValueError, 'no city detections'):
            module.compare_outputs(ref, actual, 1)

    def test_nan_fails(self):
        ref = values();actual = {k: v.copy() for k, v in ref.items()};actual['labels'][0, 0, 0] = np.nan
        with self.assertRaisesRegex(ValueError, 'non-finite'):
            module.compare_outputs(ref, actual, 1)

    def test_second_batch_checked(self):
        ref = values();actual = {k: np.repeat(v, 2, 0) for k, v in ref.items()}
        actual['dets'][1, 0, 0] = .8
        report = module.compare_outputs(ref, actual, 2)
        self.assertTrue(report['predictionSetSamples'][0]['passed'])
        self.assertFalse(report['predictionSetSamples'][1]['passed'])
        self.assertFalse(report['passed'])

    def test_timing_summary(self):
        records = [{'computeMs': value, 'latencyMs': value + .5, 'h2dMs': .3, 'd2hMs': .2} for value in [1.,2.,3.]]
        result = module.summarize_times(records)
        self.assertEqual(result['sampleCount'], 3)
        self.assertEqual(result['computeMs']['p50'], 2)
        self.assertAlmostEqual(result['computeMs']['p95'], 2.9)
        with self.assertRaisesRegex(ValueError, 'no timing samples'):
            module.summarize_times([])


if __name__ == '__main__':
    unittest.main()
