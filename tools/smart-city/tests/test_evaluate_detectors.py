# SPDX-License-Identifier: Apache-2.0
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
import numpy as np
spec=importlib.util.spec_from_file_location('evaluate_detectors',Path(__file__).parents[1]/'evaluate_detectors.py')
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)


class EvaluationTests(unittest.TestCase):
    def test_sparse_coco_and_original_box_geometry(self):
        logits=np.full((1,1,91),-100,dtype=np.float32);logits[0,0,6]=4
        predictions=m.decode_rfdetr({'dets':np.array([[[.5,.5,.2,.4]]]),'labels':logits},7,1000,500,.001)
        self.assertEqual(predictions[0]['category_id'],6)
        np.testing.assert_allclose(predictions[0]['bbox'],[400,150,200,200])
    def test_bad_output_fails(self):
        logits=np.full((1,1,91),np.nan)
        with self.assertRaisesRegex(ValueError,'Non-finite'):
            m.decode_rfdetr({'dets':np.array([[[.5,.5,.2,.4]]]),'labels':logits},7,1000,500,.001)
    def test_coarse_query_duplicates_merge_without_inventing_subclass(self):
        p=[{'image_id':1,'category_id':3,'bbox':[1,2,3,4],'score':.8,'queryIndex':2},
           {'image_id':1,'category_id':8,'bbox':[1,2,3,4],'score':.4,'queryIndex':2}]
        new=m.coarse_predictions(p);self.assertEqual(len(new),1);self.assertEqual(new[0]['category_id'],3);self.assertEqual(new[0]['score'],.8)
    def test_official_coco_evaluator_respects_crowd_ignore(self):
        gt={'info':{},'images':[{'id':1,'width':100,'height':100},{'id':2,'width':100,'height':100}],
            'categories':[{'id':1,'name':'person'}],
            'annotations':[{'id':1,'image_id':1,'category_id':1,'bbox':[10,10,10,10],'area':100,'iscrowd':0},
                           {'id':2,'image_id':2,'category_id':1,'bbox':[0,0,100,100],'area':10000,'iscrowd':1}]}
        p=[{'image_id':1,'category_id':1,'bbox':[10,10,10,10],'score':.9},
           {'image_id':2,'category_id':1,'bbox':[10,10,10,10],'score':.8}]
        with tempfile.TemporaryDirectory()as d:
            path=Path(d)/'gt.json';path.write_text(json.dumps(gt))
            r=m.evaluate(path,p,[1],Path(d)/'log.txt')
            self.assertAlmostEqual(r['metrics']['AP'],1)
            p[0]['bbox']=[80,80,10,10]
            r=m.evaluate(path,p,[1],Path(d)/'bad-log.txt')
            self.assertEqual(r['metrics']['AP'],0)


if __name__=='__main__':unittest.main()
