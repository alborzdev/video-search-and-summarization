# SPDX-License-Identifier: Apache-2.0
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from predict_detectnet_video import allowed_categories, verified_frame
from compare_detector_continuity import validate_manifest, validate_predictions

class VideoPredictionTests(unittest.TestCase):
    def test_categories_do_not_treat_two_wheeler_as_bicycle(self):
        self.assertEqual(allowed_categories('trafficcamnet'),{1,3});self.assertEqual(allowed_categories('peoplenet'),{1})
    def test_hash_and_path_are_enforced(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); (base/'a').write_bytes(b'a')
            frame={'fileName':'a','sha256':hashlib.sha256(b'a').hexdigest()}
            self.assertEqual(verified_frame(base,frame),base/'a')
            with self.assertRaises(ValueError):verified_frame(base,{**frame,'sha256':'bad'})
            with self.assertRaises(ValueError):verified_frame(base,{**frame,'fileName':'../other'})
    def test_exact_frame_coverage(self):
        manifest={'frames':[{'image_id':1,'source_id':'a','frame_index':0,'timestamp_ns':1},{'image_id':2,'source_id':'a','frame_index':1,'timestamp_ns':2}]}
        ids,_=validate_manifest(manifest)
        validate_predictions({'processed_image_ids':[1,2],'predictions':[]},ids,{1})
        with self.assertRaises(ValueError):validate_predictions({'processed_image_ids':[1],'predictions':[]},ids,{1})
if __name__=='__main__':unittest.main()
