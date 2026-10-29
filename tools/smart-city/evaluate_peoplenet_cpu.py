#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""CPU-only PeopleNet and TrafficCamNet comparison. NMS is a distinct policy from DeepStream hybrid clustering."""
from __future__ import annotations
import argparse
import os
import threading
import json
from pathlib import Path
import time
import numpy as np
from evaluate_detectors import evaluate, sha256

WIDTH, HEIGHT = 960, 544

def available_bytes():
    with open('/proc/meminfo') as handle:
        for line in handle:
            if line.startswith('MemAvailable:'):
                return int(line.split()[1]) * 1024
    raise RuntimeError('MemAvailable unavailable')

def start_memory_watchdog(floor_gib=24):
    observed = [available_bytes()]
    if observed[0] < floor_gib * 2**30: raise RuntimeError('Host memory below evaluation floor')
    def watch():
        while True:
            observed[0] = min(observed[0], available_bytes())
            if observed[0] < floor_gib * 2**30:
                print('Stopping CPU evaluation: host memory fell below 24 GiB', flush=True)
                os._exit(2)
            threading.Event().wait(.5)
    threading.Thread(target=watch,daemon=True).start()
    return observed

def decode(coverage, boxes, image_id, image_width, image_height, threshold=.05, iou=.5, model='peoplenet'):
    """Decode selected classes using DeepStream 9.2 grid geometry, then deterministic NMS.

    DeepStream's example hybrid DBSCAN+NMS is intentionally NOT reproduced.
    Input image was stretched to 960x544, so x/y restoration is independent.
    """
    cov = np.asarray(coverage); bbox = np.asarray(boxes)
    classes = {'peoplenet': [(0,1)], 'trafficcamnet': [(0,3),(1,2),(2,1)]}
    if model not in classes: raise ValueError('Unsupported model')
    count = 3 if model == 'peoplenet' else 4
    if cov.shape != (1,count,34,60) or bbox.shape != (1,count*4,34,60):
        raise ValueError('PeopleNet output tensor shape mismatch')
    if not np.isfinite(cov).all() or not np.isfinite(bbox).all():
        raise ValueError('Non-finite PeopleNet output')
    if image_width <= 0 or image_height <= 0 or not 0 <= threshold <= 1 or not 0 <= iou <= 1:
        raise ValueError('Invalid image dimensions or thresholds')
    result=[]
    for class_index, category in classes[model]:
        result.extend(_decode_class(cov,bbox,image_id,image_width,image_height,threshold,iou,class_index,category))
    return result

def _decode_class(cov,bbox,image_id,image_width,image_height,threshold,iou,class_index,category):
    rows, cols = np.nonzero(cov[0,class_index] >= threshold)
    if len(rows) == 0: return []
    score = cov[0,class_index,rows,cols]
    cx = cols * 16. + .5; cy = rows * 16. + .5
    b = bbox[0,class_index*4:class_index*4+4,rows,cols]
    x1 = np.clip(cx - b[:,0] * 35., 0, WIDTH-1)
    y1 = np.clip(cy - b[:,1] * 35., 0, HEIGHT-1)
    x2 = np.clip(cx + b[:,2] * 35., 0, WIDTH-1)
    y2 = np.clip(cy + b[:,3] * 35., 0, HEIGHT-1)
    valid = (x2 > x1) & (y2 > y1)
    x1,y1,x2,y2,score = (a[valid] for a in (x1,y1,x2,y2,score))
    order = np.argsort(-score, kind='stable'); kept = []
    while len(order) and len(kept) < 100:
        i = order[0]; kept.append(i); remaining = order[1:]
        if not len(remaining): break
        intersection = np.maximum(0, np.minimum(x2[i], x2[remaining]) - np.maximum(x1[i],x1[remaining])) * np.maximum(0, np.minimum(y2[i], y2[remaining]) - np.maximum(y1[i],y1[remaining]))
        area_i=(x2[i]-x1[i])*(y2[i]-y1[i]); area_r=(x2[remaining]-x1[remaining])*(y2[remaining]-y1[remaining])
        union=area_i+area_r-intersection
        overlap=np.divide(intersection,union,out=np.zeros_like(intersection),where=union>0)
        order=remaining[overlap <= iou]
    sx,sy=image_width/WIDTH,image_height/HEIGHT
    return [{'image_id':image_id,'category_id':category,'bbox':[float(x1[i]*sx),float(y1[i]*sy),float((x2[i]-x1[i])*sx),float((y2[i]-y1[i])*sy)],'score':float(score[i])} for i in kept]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--onnx',type=Path,required=True);p.add_argument('--subset',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--model',choices=['peoplenet','trafficcamnet'],default='peoplenet');p.add_argument('--limit',type=int,default=0,help='Positive control only; do not calculate corpus metrics')
    p.add_argument('--threads',type=int,default=4);p.add_argument('--minimum-score',type=float,default=.05);p.add_argument('--nms-iou',type=float,default=.5)
    a=p.parse_args()
    if not 1 <= a.threads <= 4: raise ValueError('Use one to four CPU threads')
    memory_low=start_memory_watchdog()
    import onnxruntime as ort
    from PIL import Image
    options=ort.SessionOptions();options.intra_op_num_threads=a.threads;options.inter_op_num_threads=1
    session=ort.InferenceSession(str(a.onnx),options,providers=['CPUExecutionProvider'])
    if session.get_providers()!=['CPUExecutionProvider']: raise RuntimeError('Unexpected inference provider')
    inputs=session.get_inputs();outputs=session.get_outputs()
    if len(inputs)!=1 or inputs[0].name!='input_1:0' or {x.name for x in outputs}!={'output_cov/Sigmoid:0','output_bbox/BiasAdd:0'}: raise ValueError('PeopleNet graph mismatch')
    manifest_path=a.subset/'subset-manifest.json';manifest=json.loads(manifest_path.read_text());gt=a.subset/'instances_road_subset.json'
    if sha256(gt)!=manifest['selectedGroundTruthSha256']: raise RuntimeError('Ground truth hash mismatch')
    a.output.mkdir(parents=True,exist_ok=True);predictions=[]; durations=[];started=time.monotonic()
    for im in manifest['images'][:a.limit or None]:
        path=a.subset/'images'/im['fileName']
        if sha256(path)!=im['sha256']: raise RuntimeError('Image hash mismatch')
        with Image.open(path) as image:
            image=image.convert('RGB')
            if image.size!=(im['width'],im['height']): raise RuntimeError('Image size mismatch')
            rgb=np.asarray(image.resize((WIDTH,HEIGHT),Image.Resampling.BILINEAR),dtype=np.float32)/255.
        tensor=np.ascontiguousarray(rgb.transpose(2,0,1)[None])
        t=time.monotonic();out=dict(zip([x.name for x in outputs],session.run(None,{'input_1:0':tensor})));durations.append(time.monotonic()-t)
        predictions.extend(decode(out['output_cov/Sigmoid:0'],out['output_bbox/BiasAdd:0'],im['id'],im['width'],im['height'],a.minimum_score,a.nms_iou,a.model))
    prediction_path=a.output/'predictions.json';prediction_path.write_text(json.dumps(predictions,separators=(',',':'))+'\n')
    metrics=None; coarse=None
    if not a.limit:
        categories=[1] if a.model=='peoplenet' else [1,3]
        relevant=[x for x in predictions if x['category_id'] in categories]
        metrics=evaluate(gt,relevant,categories,a.output/'coco-eval.txt')
        if a.model=='trafficcamnet':
            coarse_gt=a.subset/'instances_coarse_road_subset.json'
            if sha256(coarse_gt)!=manifest['coarseGroundTruthSha256']: raise RuntimeError('Coarse ground truth hash mismatch')
            coarse=evaluate(coarse_gt,[x for x in predictions if x['category_id']==2],[2],a.output/'coarse-two-wheeler-eval.txt')
    receipt={'schemaVersion':'city.peoplenet-cpu-evaluation.v1','model':a.model,'onnxSha256':sha256(a.onnx),'subsetManifestSha256':sha256(manifest_path),'groundTruthSha256':sha256(gt),'predictionsSha256':sha256(prediction_path),'evaluatorSourceSha256':sha256(Path(__file__)),'provider':session.get_providers(),'ortVersion':ort.__version__,'cpuThreads':a.threads,'gpuUsed':False,'memoryStopFloorGiB':24,'minimumSampledAvailableGiB':memory_low[0]/2**30,'imageCount':len(manifest['images'][:a.limit or None]),'predictionCount':len(predictions),'input':'RGB 960x544 direct bilinear resize, float32 NCHW 1/255; no mean subtraction','postprocess':'DeepStream DetectNet_v2 grid geometry; selected native classes; deterministic score-sorted NMS, not DeepStream hybrid DBSCAN+NMS','minimumScore':a.minimum_score,'nmsIoU':a.nms_iou,'maxDetectionsPerClassPerImage':100,'personAndCarMetrics':metrics,'coarseTwoWheelerMetrics':coarse,'taxonomy':'PeopleNet: person only. TrafficCamNet: native car->COCO car, person->COCO person; two-wheeler->coarse bicycle/motorcycle. Road sign ignored; no fabricated bus/truck classes.','wallSeconds':time.monotonic()-started,'meanCpuInferenceSeconds':float(np.mean(durations)),'scope':'Fixed 100-image class-stratified COCO road proxy; model-dependent selected classes. Not tracking, actual TensorRT/DeepStream pipeline, city-scene, or full COCO qualification.'}
    (a.output/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt,indent=2))
if __name__=='__main__':main()
