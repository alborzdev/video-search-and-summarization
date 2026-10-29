# SPDX-License-Identifier: Apache-2.0
import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from evaluate_peoplenet_cpu import decode

class PeopleNetDecodeTests(unittest.TestCase):
    def test_box_geometry_restoration_threshold_and_class(self):
        cov=np.zeros((1,3,34,60),np.float32);boxes=np.zeros((1,12,34,60),np.float32)
        cov[0,0,2,3]=.9;cov[0,1,2,3]=1.;cov[0,0,1,1]=.01
        boxes[0,:4,2,3]=[.4,.2,.6,.8]
        result=decode(cov,boxes,42,1920,1088,.05)
        self.assertEqual(len(result),1);self.assertEqual(result[0]['category_id'],1);self.assertEqual(result[0]['image_id'],42)
        np.testing.assert_allclose(result[0]['bbox'],[69,51,70,70],atol=1e-5)
    def test_stable_nms_suppresses_same_box(self):
        cov=np.zeros((1,3,34,60),np.float32);boxes=np.zeros((1,12,34,60),np.float32)
        cov[0,0,0,0]=.8;cov[0,0,0,1]=.9
        boxes[0,:4,0,0]=[0,0,1,1];boxes[0,:4,0,1]=[16/35,0,19/35,1]
        result=decode(cov,boxes,1,960,544,.05,.5)
        self.assertEqual(len(result),1);self.assertAlmostEqual(result[0]['score'],.9,places=5)
    def test_trafficcamnet_native_class_mapping(self):
        cov=np.zeros((1,4,34,60),np.float32); boxes=np.zeros((1,16,34,60),np.float32)
        cov[0,:,1,1]=.9
        for i in range(4): boxes[0,i*4:i*4+4,1,1]=[.2,.2,.2,.2]
        result=decode(cov,boxes,1,960,544,.05,.5,'trafficcamnet')
        self.assertEqual([x['category_id'] for x in result],[3,2,1])
    def test_bad_shapes_and_nan_rejected(self):
        cov=np.zeros((1,3,34,60));boxes=np.zeros((1,12,34,60));cov[0,0,0,0]=float('nan')
        with self.assertRaises(ValueError): decode(cov,boxes,1,1,1)
        with self.assertRaises(ValueError): decode(cov[:,:,:1],boxes,1,1,1)
if __name__=='__main__':unittest.main()
