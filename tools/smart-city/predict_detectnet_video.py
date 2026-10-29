#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Predict fixed recorded frames on CPU; no ground truth or identity claims."""
import argparse
import json
from pathlib import Path
import time
import numpy as np
from evaluate_detectors import sha256
from evaluate_peoplenet_cpu import HEIGHT, WIDTH, decode, start_memory_watchdog
from compare_detector_continuity import validate_manifest, validate_predictions


def allowed_categories(model):
    # Native TrafficCamNet two-wheeler combines bicycle/motorcycle, while this
    # continuity tool's ID 2 means bicycle. Exclude it from exact-class checks.
    return {'peoplenet':{1}, 'trafficcamnet':{1,3}}[model]


def verified_frame(base, frame):
    path=(base/frame['fileName']).resolve()
    if not path.is_relative_to(base.resolve()) or not path.is_file():
        raise ValueError('Invalid video frame path')
    if sha256(path)!=frame['sha256']: raise ValueError('Frame hash mismatch')
    return path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model',choices=['peoplenet','trafficcamnet'],required=True)
    parser.add_argument('--onnx',type=Path,required=True);parser.add_argument('--manifest',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--threads',type=int,default=2);parser.add_argument('--minimum-score',type=float,default=.001);parser.add_argument('--nms-iou',type=float,default=.5)
    args=parser.parse_args()
    if not 1 <= args.threads <= 2: raise ValueError('Use one or two CPU threads')
    memory_low=start_memory_watchdog()
    import onnxruntime as ort
    from PIL import Image
    options=ort.SessionOptions();options.intra_op_num_threads=args.threads;options.inter_op_num_threads=1
    session=ort.InferenceSession(str(args.onnx),options,providers=['CPUExecutionProvider'])
    if session.get_providers()!=['CPUExecutionProvider']: raise RuntimeError('Unexpected provider')
    inputs=session.get_inputs();outputs=session.get_outputs()
    if len(inputs)!=1 or inputs[0].name!='input_1:0' or {o.name for o in outputs}!={'output_cov/Sigmoid:0','output_bbox/BiasAdd:0'}: raise ValueError('Unexpected graph')
    manifest=json.loads(args.manifest.read_text()); ids,_=validate_manifest(manifest)
    predictions=[];processed=[];start=time.monotonic();categories=allowed_categories(args.model)
    for frame in manifest['frames']:
        path=verified_frame(args.manifest.parent,frame)
        with Image.open(path) as image:
            image=image.convert('RGB')
            if image.size!=(frame['width'],frame['height']): raise ValueError('Frame dimensions mismatch')
            rgb=np.asarray(image.resize((WIDTH,HEIGHT),Image.Resampling.BILINEAR),dtype=np.float32)/255.
        tensor=np.ascontiguousarray(rgb.transpose(2,0,1)[None])
        out=dict(zip([o.name for o in outputs],session.run(None,{'input_1:0':tensor})))
        predictions.extend(x for x in decode(out['output_cov/Sigmoid:0'],out['output_bbox/BiasAdd:0'],frame['image_id'],frame['width'],frame['height'],args.minimum_score,args.nms_iou,args.model) if x['category_id'] in categories)
        processed.append(frame['image_id'])
    document={'processed_image_ids':processed,'predictions':predictions}
    validate_predictions(document,ids,categories)
    args.output.mkdir(parents=True,exist_ok=True)
    output=args.output/'predictions.json';output.write_text(json.dumps(document,separators=(',',':'))+'\n')
    receipt={'schemaVersion':'city.detectnet-video-predictions.v1','model':args.model,'onnxSha256':sha256(args.onnx),'frameManifestSha256':sha256(args.manifest),'predictionsSha256':sha256(output),'predictorSha256':sha256(Path(__file__)),'decoderSha256':sha256(Path(__file__).with_name('evaluate_peoplenet_cpu.py')),'frames':len(processed),'predictionCount':len(predictions),'supportedCategories':sorted(categories),'input':'RGB 960x544 direct bilinear resize; 1/255, float NCHW','postprocessing':'DetectNet grid decode plus deterministic NMS; not native DeepStream hybrid DBSCAN+NMS','minimumScore':args.minimum_score,'nmsIoU':args.nms_iou,'ortVersion':ort.__version__,'provider':session.get_providers(),'cpuThreads':args.threads,'gpuUsed':False,'memoryStopFloorGiB':24,'minimumSampledAvailableGiB':memory_low[0]/2**30,'elapsedSeconds':time.monotonic()-start,'scope':'Predictions on fixed frames; no ground truth, AP, identity accuracy, or native MV3DT measurement. TrafficCamNet two-wheeler omitted because it is not a bicycle-only class.'}
    (args.output/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt,indent=2))
if __name__=='__main__': main()
