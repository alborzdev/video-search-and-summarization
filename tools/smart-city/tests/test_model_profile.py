"""CPU-only controls for device-local detector selection and config generation."""
import configparser
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import model_profile as profile


class ModelProfiles(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.directory=self.root/'.spark/city';self.directory.mkdir(parents=True)
        original=Path(__file__).resolve().parents[3]
        shutil.copytree(original/'services/rtvi/rt-cv/smart-city/configs',
                        self.root/'services/rtvi/rt-cv/smart-city/configs')
        self.lock={'classes':profile.CLASSES,'cocoSlots':profile.COCO_SLOTS,'models':{}}
        for size,resolution in profile.RESOLUTIONS.items():
            engine=self.directory/f'models/rfdetr-{size}-fp16-b2.engine';engine.parent.mkdir(exist_ok=True)
            engine.write_bytes(f'explicit-unit-test-{size}-engine'.encode())
            graph=self.directory/f'models/rfdetr-{size}/rfdetr-{size}.onnx';graph.parent.mkdir()
            graph.write_bytes(f'explicit-unit-test-{size}-graph'.encode())
            engine_hash=profile.digest(engine);graph_hash=profile.digest(graph)
            self.lock['models'][size]={'resolution':resolution,'onnxSha256':graph_hash,
                                      'sparkObservedEngineSha256':engine_hash}
            self.write(graph.parent/'export-receipt.json',{'model':size,'onnxSha256':graph_hash,
                'spatialResolution':resolution,'dynamicBatch':True})
            if size in ('medium', 'large'):
                self.write(engine.with_suffix('.build.json'),{'schemaVersion':'city.engine-build.v1',
                    'device':'spark','model':size,'engineSha256':engine_hash,'onnxSha256':graph_hash,
                    'batchRange':[1,2],'precision':'FP16 internal, FP32 input/output'})
            for batch in (1,2):
                run=self.directory/f'runtime/corpus-outputs/rfdetr-{size}-fp16-b{batch}/run-receipt.json'
                self.write(run,{'schemaVersion':'city.tensorrt-corpus-run.v1','model':f'rfdetr-{size}',
                    'engineSha256':engine_hash,'batch':batch,'imageCount':100,'gpuUsed':True,
                    'subsetManifestSha256':'a'*64,'gpu':'NVIDIA GB10, explicit unit-test fixture'})
                self.write(self.quality_path(size,batch),{'schemaVersion':'city.tensorrt-corpus-quality.v1',
                    'model':f'rfdetr-{size}','engineSha256':engine_hash,'batch':batch,'imageCount':100,
                    'gpuUsedForInference':True,'subsetManifestSha256':'a'*64,'runReceiptSha256':profile.digest(run),
                    'sixRoadClasses':{'metrics':{'AP':.5},'imageCount':100,'categories':profile.COCO_SLOTS,
                                     'perClass':{name:{'AP':.5} for name in profile.CLASSES}},
                    'fp32Reference':{'onnxSha256':graph_hash,'metricDeltaPercentagePoints':{'AP':0.}},
                    'precisionRetentionGate':{'passed':True,'maximumApDropPercentagePoints':1.}})
        self.write(self.root/'tools/smart-city/artifacts.lock.json',self.lock)

    def tearDown(self):self.temp.cleanup()

    def write(self,path,value):
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))

    def quality_path(self,size,batch):
        return self.directory/f'eval/results/rfdetr-{size}-fp16-b{batch}/receipt.json'

    def test_small_default_and_idempotent_generated_config(self):
        selected=profile.selected_model(self.root,'spark')
        self.assertEqual(selected['size'],'small');self.assertEqual(selected['selectionSource'],'default-small')
        first=profile.config_for_launch(self.root,'spark');target=Path(first['hostConfigDir'])
        before=(target/'infer.ini').stat().st_mtime_ns
        second=profile.config_for_launch(self.root,'spark')
        self.assertEqual(first['nativeArgs'],second['nativeArgs'])
        self.assertEqual((target/'infer.ini').stat().st_mtime_ns,before)
        self.assertIn('small',first['modelRevision']);self.assertIn(selected['engineSha256'],first['modelRevision'])
        self.assertEqual(first['nativeArgs'][2],'--model-revision')

    def test_medium_preview_does_not_select_and_generates_576(self):
        result=profile.config_for_model(self.root,'spark','medium')
        self.assertEqual(profile.selection_name(self.root,'spark'),'small')
        target=Path(result['hostConfigDir']);prep=configparser.ConfigParser();prep.read(target/'preprocess.ini')
        self.assertEqual(prep['property']['network-input-shape'],'2;3;576;576')
        self.assertEqual(prep['property']['processing-width'],'576')
        self.assertEqual(prep['property']['processing-height'],'576')
        infer=configparser.ConfigParser();infer.read(target/'infer.ini')
        self.assertEqual(infer['property']['onnx-file'],'/models/rfdetr-medium/rfdetr-medium.onnx')
        self.assertEqual(infer['property']['model-engine-file'],'/models/rfdetr-medium-fp16-b2.engine')
        self.assertEqual(infer['property']['labelfile-path'],result['configDir']+'/labels.txt')
        self.assertEqual((target/'labels.txt').read_text().splitlines(),profile.CLASSES)
        self.assertEqual((target/'tracker.yml').read_bytes(),(self.root/'services/rtvi/rt-cv/smart-city/configs/tracker.yml').read_bytes())

    def test_explicit_medium_selection_is_pinned(self):
        selected=profile.select_model(self.root,'spark','medium')
        self.assertEqual(profile.selected_model(self.root,'spark')['modelRevision'],selected['modelRevision'])
        self.assertEqual(profile.selection_name(self.root,'spark'),'medium')
        profile.select_model(self.root,'spark','small')
        self.assertEqual(profile.selection_name(self.root,'spark'),'small')

    def test_large_704_profile_requires_build_and_quality_evidence(self):
        result=profile.config_for_model(self.root,'spark','large')
        self.assertEqual(profile.selection_name(self.root,'spark'),'small')
        prep=configparser.ConfigParser();prep.read(Path(result['hostConfigDir'])/'preprocess.ini')
        self.assertEqual(prep['property']['network-input-shape'],'2;3;704;704')
        self.assertEqual(prep['property']['processing-width'],'704')
        build=self.directory/'models/rfdetr-large-fp16-b2.build.json'
        build.unlink()
        with self.assertRaisesRegex(profile.ProfileError,'build receipt'):
            profile.select_model(self.root,'spark','large')

    def test_large_cannot_select_without_batch_two_quality(self):
        self.quality_path('large',2).unlink()
        with self.assertRaises(profile.ProfileError):
            profile.select_model(self.root,'spark','large')

    def test_experimental_trafficcamnet_selection_and_config(self):
        engine=self.directory/'models/trafficcamnet-transformer-r18-fp16-b2.engine'
        graph=self.directory/'models/trafficcamnet-transformer-r18/model.onnx'
        graph.parent.mkdir(); engine.write_bytes(b'traffic-engine'); graph.write_bytes(b'traffic-onnx')
        eh,gh=profile.digest(engine),profile.digest(graph)
        self.lock['trafficCamNetTransformer']={'onnxSha256':gh,'sparkObservedEngineSha256':eh}
        self.write(self.root/'tools/smart-city/artifacts.lock.json',self.lock)
        self.write(graph.parent/'build-receipt.json',{'schemaVersion':'city.nvidia-isolated-engine-build.v1',
            'success':True,'engineSha256':eh,'onnxSha256':gh,'image':'fixture'})
        self.write(graph.parent/'positive-receipt.json',{'schemaVersion':'city.nvidia-positive-control.v1',
            'success':True,'engineSha256':eh,'image':'fixture'})
        adapter=self.directory/'runtime/trafficcam-adapter-20261026';adapter.mkdir(parents=True)
        for name in profile.ADAPTER_FILES:
            (adapter/name).write_bytes(name.encode())
        self.write(adapter/'receipt.json',{'schemaVersion':'city.trafficcam-adapter.v1','success':True,'buildImage':'fixture',
            'fileHashes':{name:profile.digest(adapter/name) for name in profile.ADAPTER_FILES}})
        selected=profile.select_model(self.root,'spark',profile.TRAFFIC)
        self.assertEqual(selected['supportedClasses'],['person','car','two-wheeler'])
        result=profile.config_for_launch(self.root,'spark');target=Path(result['hostConfigDir'])
        prep=configparser.ConfigParser();prep.read(target/'preprocess.ini')
        self.assertEqual(prep['property']['network-input-shape'],'2;3;544;960')
        self.assertEqual(prep['property']['tensor-name'],'inputs')
        self.assertEqual(prep['property']['maintain-aspect-ratio'],'1')
        self.assertEqual(prep['property']['custom-tensor-preparation-function'],'CustomTrafficCamTensorPreparation')
        infer=configparser.ConfigParser();infer.read(target/'infer.ini')
        self.assertEqual(infer['property']['parse-bbox-func-name'],'NvDsInferParseCityTrafficCamNet')
        self.assertEqual(infer['property']['output-blob-names'],'pred_logits;pred_boxes')
        self.assertEqual(infer['property']['maintain-aspect-ratio'],'1')
        self.assertEqual(infer['property']['num-detected-classes'],'7')
        self.assertEqual((target/'labels.txt').read_text().splitlines(),[*profile.CLASSES,'two-wheeler'])
        self.assertEqual(len(result['adapterMounts']),3)
        (adapter/'city-worker').write_bytes(b'mutated')
        with self.assertRaisesRegex(profile.ProfileError,'adapter artifact changed'):
            profile.selected_model(self.root,'spark')
        (adapter/'city-worker').write_bytes(b'city-worker')
        engine.write_bytes(b'changed')
        with self.assertRaisesRegex(profile.ProfileError,'pinned hashes'):
            profile.selected_model(self.root,'spark')
        profile.select_model(self.root,'spark','medium')
        self.assertEqual(profile.selection_name(self.root,'spark'),'medium')

    def test_tampered_engine_rejected_even_after_cached_hash(self):
        profile.selected_model(self.root,'spark')
        (self.directory/'models/rfdetr-small-fp16-b2.engine').write_bytes(b'tampered')
        with self.assertRaisesRegex(profile.ProfileError,'engine does not match'):
            profile.selected_model(self.root,'spark')

    def test_missing_medium_build_receipt_cannot_select(self):
        (self.directory/'models/rfdetr-medium-fp16-b2.build.json').unlink()
        with self.assertRaisesRegex(profile.ProfileError,'build receipt'):
            profile.select_model(self.root,'spark','medium')
        self.assertEqual(profile.selection_name(self.root,'spark'),'small')

    def test_missing_quality_receipt_cannot_select(self):
        self.quality_path('medium',2).unlink()
        with self.assertRaisesRegex(profile.ProfileError,'receipt is missing'):
            profile.select_model(self.root,'spark','medium')

    def test_wrong_run_or_failed_retention_cannot_select(self):
        path=self.quality_path('medium',2);value=json.loads(path.read_text())
        value['precisionRetentionGate']['passed']=False;self.write(path,value)
        with self.assertRaisesRegex(profile.ProfileError,'quality receipt'):
            profile.select_model(self.root,'spark','medium')
        value['precisionRetentionGate']['passed']=True;value['runReceiptSha256']='0'*64;self.write(path,value)
        with self.assertRaisesRegex(profile.ProfileError,'actual target-device'):
            profile.select_model(self.root,'spark','medium')

    def test_wrong_taxonomy_or_corrupt_quality_receipt_rejected(self):
        path=self.quality_path('medium',2);value=json.loads(path.read_text())
        value['sixRoadClasses']['categories']=[1,2,3];self.write(path,value)
        with self.assertRaisesRegex(profile.ProfileError,'quality receipt'):
            profile.select_model(self.root,'spark','medium')
        self.write(path,[])
        with self.assertRaisesRegex(profile.ProfileError,'must be an object'):
            profile.select_model(self.root,'spark','medium')

    def test_unknown_size_and_symlink_rejected(self):
        with self.assertRaisesRegex(profile.ProfileError,'Unknown detector size'):
            profile.select_model(self.root,'spark','xlarge')
        engine=self.directory/'models/rfdetr-small-fp16-b2.engine';copy=self.root/'outside.engine'
        engine.rename(copy);engine.symlink_to(copy)
        with self.assertRaisesRegex(profile.ProfileError,'symlinked'):
            profile.selected_model(self.root,'spark')

    def test_device_qualification_does_not_transfer(self):
        thor=self.root/'.thor/city';shutil.copytree(self.directory,thor)
        with self.assertRaisesRegex(profile.ProfileError,'Spark engine cannot qualify a Thor'):
            profile.selected_model(self.root,'thor')


if __name__=='__main__':unittest.main()
