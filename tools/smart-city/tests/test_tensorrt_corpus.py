"""CPU controls of actual-engine corpus provenance and quality gates; no GPU."""
import argparse
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import evaluate_tensorrt_corpus as corpus
from evaluate_detectors import ROAD, sha256


class ScoreControls(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.subset=self.root/'subset';self.outputs=self.root/'outputs'
        self.subset.mkdir();self.outputs.mkdir()
        gt={'info':{},'images':[{'id':1,'width':100,'height':100}],
            'categories':[{'id':key,'name':name} for key,name in ROAD.items()],
            'annotations':[{'id':1,'image_id':1,'category_id':1,'bbox':[30,30,40,40],
                            'area':1600,'iscrowd':0}]}
        gt_path=self.subset/'instances_road_subset.json';gt_path.write_text(json.dumps(gt))
        coarse={**gt,'categories':[{'id':1,'name':'person'},{'id':2,'name':'two-wheeler'},{'id':3,'name':'vehicle'}]}
        coarse_path=self.subset/'instances_coarse_road_subset.json';coarse_path.write_text(json.dumps(coarse))
        manifest={'images':[{'id':1,'width':100,'height':100}],
            'selectedGroundTruthSha256':sha256(gt_path),'coarseGroundTruthSha256':sha256(coarse_path)}
        self.manifest=self.subset/'subset-manifest.json';self.manifest.write_text(json.dumps(manifest))
        self.write_output([.5,.5,.4,.4])
        reference={'model':'rfdetr-small','subsetManifestSha256':sha256(self.manifest),'onnxSha256':'cpu-fixture',
            'sixRoadClasses':{'metrics':{key:1. for key in ('AP','AP50','AP75','APsmall','APmedium','APlarge','AR1','AR10','AR100','ARsmall','ARmedium','ARlarge')},
                'perClass':{name:{'AP':1. if name=='person' else None} for name in ROAD.values()}}}
        self.cpu=self.root/'cpu.json';self.cpu.write_text(json.dumps(reference))

    def tearDown(self):
        self.tmp.cleanup()

    def write_output(self,box):
        logits=np.full((1,1,91),-30,dtype=np.float32);logits[0,0,1]=10
        target=self.outputs/'000000000001.npz'
        np.savez(target,dets=np.array([[box]],dtype=np.float32),labels=logits)
        receipt={'model':'rfdetr-small','engineSha256':'explicit-cpu-scoring-fixture','batch':1,
            'precision':'fixture outputs, no engine inference','subsetManifestSha256':sha256(self.manifest),
            'outputs':[{'id':1,'fileName':target.name,'sha256':sha256(target)}]}
        (self.outputs/'run-receipt.json').write_text(json.dumps(receipt))

    def args(self):
        return argparse.Namespace(subset=self.subset,outputs=self.outputs,result=self.root/'result',
                                  cpu_receipt=self.cpu,maximum_ap_drop=1.)

    def test_matching_outputs_pass_and_preserve_provenance(self):
        with redirect_stdout(io.StringIO()):corpus.score(self.args())
        receipt=json.loads((self.root/'result/receipt.json').read_text())
        self.assertTrue(receipt['precisionRetentionGate']['passed'])
        self.assertAlmostEqual(receipt['sixRoadClasses']['metrics']['AP'],1.)
        self.assertIsNone(receipt['fp32Reference']['perClassApDeltaPercentagePoints']['bus'])
        self.assertFalse(receipt['gpuUsedForInference'])

    def test_wrong_boxes_fail_retention_with_receipt_saved(self):
        self.write_output([.1,.1,.1,.1])
        with self.assertRaisesRegex(RuntimeError,'retention gate failed'):
            with redirect_stdout(io.StringIO()):corpus.score(self.args())
        receipt=json.loads((self.root/'result/receipt.json').read_text())
        self.assertFalse(receipt['precisionRetentionGate']['passed'])

    def test_changed_gpu_artifact_is_rejected(self):
        (self.outputs/'000000000001.npz').write_bytes(b'changed')
        with self.assertRaisesRegex(RuntimeError,'changed after inference'):
            corpus.score(self.args())

    def test_duplicate_image_receipt_is_rejected(self):
        path=self.outputs/'run-receipt.json';receipt=json.loads(path.read_text())
        receipt['outputs'].append(receipt['outputs'][0]);path.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(RuntimeError,'exactly once'):
            corpus.score(self.args())


if __name__=='__main__':
    unittest.main()
