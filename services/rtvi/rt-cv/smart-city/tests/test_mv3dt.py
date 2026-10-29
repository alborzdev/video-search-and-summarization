# SPDX-License-Identifier: Apache-2.0
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("prepare_mv3dt", Path(__file__).parents[1] / "prepare_mv3dt.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def fixture():
    # Explicit test fixture: these are synthetic measurements, not scene proof.
    p = [[100., 0., 0., 100.], [0., 100., 0., 100.], [0., 0., 1., 10.]]
    points = [[0., 0., 0.], [1., 0., 0.], [0., 1., 0.], [1., 1., 0.], [0., 0., 1.], [1., 1., 2.]]
    landmarks = []
    for point in points:
        q = [sum(row[j] * (point + [1.])[j] for j in range(4)) for row in p]
        landmarks.append({"worldM": point, "imagePx": [q[0] / q[2], q[1] / q[2]]})
    cameras = [{"sourceId": name, "width": 640, "height": 480, "projectionMatrix3x4": p,
                "calibrationRevision": "fixture-1", "lensModel": "pinhole-rectified", "landmarks": landmarks}
               for name in ("cam-a", "cam-b")]
    geometry = [{"class": name, "shape": "cylinder", "heightM": 1., "radiusM": .3,
                 "provenance": "synthetic test dimensions", "approximationAcknowledged": True} for name in module.CLASSES]
    package = {"schemaVersion": "city.mv3dt.preflight.v1", "siteId": "fixture-site", "units": "metres",
               "axes": "right-handed-x-y-ground-z-up", "cameras": cameras, "classGeometry": geometry,
               "overlapPolygonM": [[0., 0.], [1., 0.], [1., 1.], [0., 1.]]}
    evidence = {"kind": "test-fixture", "clockBasis": "recorded-common-clock", "pairs": [
        {"cam-a": str(1792641488000000000 + i * 33333333),
         "cam-b": str(1792641488010000000 + i * 33333333)} for i in range(100)]}
    return copy.deepcopy(package), copy.deepcopy(evidence)


class MV3DTPreflight(unittest.TestCase):
    def test_valid_fixture_is_never_qualification(self):
        package, evidence = fixture()
        with tempfile.TemporaryDirectory() as directory:
            result = module.prepare(package, evidence, Path(directory), allow_fixtures=True)
            self.assertTrue(result["fixtureOnly"])
            self.assertFalse(result["enabled"])
            self.assertFalse(result["runtimeQualified"])
            self.assertEqual(result["maximumSourceSkewMs"], 10)
            text = (Path(directory) / "tracker-mv3dt.experimental.yml").read_text()
            self.assertIn("poseEstimatorType: 0", text)
            self.assertIn("vpiBackend4DcfTracker: 1", text)
            self.assertIn("stateEstimatorType: 3", text)
            self.assertEqual(len(json.loads((Path(directory) / "pub-sub.yml").read_text())["pubBrokerTopicStr"]), 2)
            self.assertTrue(json.loads((Path(directory) / "pub-sub.yml").read_text())["pubBrokerTopicStr"][0].startswith('vss-city-mqtt:1883;'))
            self.assertIn("classID: 4", (Path(directory) / "camera-0.yml").read_text())

    def test_capture_clock_remains_diagnostic_and_requires_simulator_readout(self):
        package, evidence = fixture()
        evidence.update(kind='simulator-common-capture-clock', clockBasis='same-rendered-batch-unix-clock')
        with self.assertRaisesRegex(ValueError, 'explicit simulator'):
            module.validate(package, evidence)
        package['cameraGeometryQualification'] = 'simulator-usd-gf-readout'
        with tempfile.TemporaryDirectory() as directory:
            result = module.prepare(package, evidence, Path(directory), tracker_resolution=(320, 192))
            self.assertTrue(result['diagnosticOnly'])
            self.assertFalse(result['transportClockQualified'])
            self.assertFalse(result['runtimeQualified'])
            self.assertFalse(result['enabled'])
            text = (Path(directory) / 'camera-0.yml').read_text()
            self.assertIn('  - 50\n', text)
            self.assertIn('  - 40\n', text)
            tracker = (Path(directory) / 'tracker-mv3dt.experimental.yml').read_text()
            self.assertIn('outputFootLocation: 1\n  outputVisibility: 1', tracker)

    def reject(self, change, message):
        package, evidence = fixture(); change(package, evidence)
        with self.assertRaisesRegex(ValueError, message):
            module.validate(package, evidence, allow_fixtures=True)

    def test_fixture_not_silently_promoted(self):
        package, evidence = fixture()
        with self.assertRaisesRegex(ValueError, "test fixture"):
            module.validate(package, evidence)

    def test_missing_calibration(self):
        self.reject(lambda p, e: p["cameras"][0].pop("projectionMatrix3x4"), "K: matrix")

    def test_resolution_mismatch(self):
        self.reject(lambda p, e: p["cameras"][1].update(width=1280), "equal camera resolutions")

    def test_skew_limit(self):
        self.reject(lambda p, e: e["pairs"][-1].update({"cam-b": str(int(e["pairs"][-1]["cam-a"]) + 60000000)}), "skew")

    def test_repeated_samples_are_not_clock_measurements(self):
        self.reject(lambda p, e: e["pairs"].__setitem__(1, e["pairs"][0]), "increase strictly")

    def test_pixel_homography_not_full_3d_calibration(self):
        self.reject(lambda p, e: p["cameras"][0].update(landmarks=p["cameras"][0]["landmarks"][:4] * 2), "span 3D")

    def test_reprojection_error(self):
        self.reject(lambda p, e: p["cameras"][0]["landmarks"][0].update(imagePx=[300, 300]), "reprojection error")

    def test_no_default_bus_dimensions(self):
        self.reject(lambda p, e: p["classGeometry"].pop(), "all six")

    def test_vehicle_approximation_explicit(self):
        self.reject(lambda p, e: p["classGeometry"][-1].update(approximationAcknowledged=False), "approximation")

    def test_overlap_must_be_visible(self):
        self.reject(lambda p, e: p.update(overlapPolygonM=[[1000, 1000], [1001, 1000], [1001, 1001]]), "not visible")

    def test_arrival_clock_not_synchronized(self):
        self.reject(lambda p, e: e.update(clockBasis="arrival-pts-unsynchronized"), "common source clock")


if __name__ == "__main__":
    unittest.main()
