#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Evaluate reviewed ONNX detectors on a pinned COCO road subset, CPU only.

This is a class-stratified proxy, not the full COCO benchmark or final city test.
No TensorRT/GPU provider is selected. Use the saved annotation/image manifest.
"""
from __future__ import annotations
import argparse
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import time

ROAD = {1: 'person', 2: 'bicycle', 3: 'car', 4: 'motorcycle', 6: 'bus', 8: 'truck'}
COARSE = {1: 1, 2: 2, 4: 2, 3: 3, 6: 3, 8: 3}
COCO_IDS = [1,2,3,4,5,6,7,8,9,10,11,13,14,15,16,17,18,19,20,21,22,23,24,25,27,28,31,32,33,34,35,36,37,38,39,40,41,42,43,44,46,47,48,49,50,51,52,53,54,55,56,57,58,59,60,61,62,63,64,65,67,70,72,73,74,75,76,77,78,79,80,81,82,84,85,86,87,88,89,90]


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def box_from_cxcywh(box, width, height):
    cx, cy, w, h = map(float, box)
    x1 = max(0., min(width, (cx - w / 2) * width));y1 = max(0., min(height, (cy - h / 2) * height))
    x2 = max(0., min(width, (cx + w / 2) * width));y2 = max(0., min(height, (cy + h / 2) * height))
    return [x1, y1, x2-x1, y2-y1]


def preprocess_image(path, resolution, expected_size):
    """Shared FP32 input generation for CPU ONNX and actual TensorRT corpus."""
    import torch
    from torchvision.transforms import functional as F
    from PIL import Image
    with Image.open(path) as opened:
        rgb = opened.convert('RGB')
        if rgb.size != expected_size:
            raise RuntimeError('COCO image dimensions disagree with decoded pixels')
        tensor = F.to_tensor(rgb)
    tensor = F.resize(tensor, [resolution,resolution], antialias=False)
    return F.normalize(tensor, [.485,.456,.406], [.229,.224,.225]).unsqueeze(0)


def decode_rfdetr(outputs, image_id, width, height, threshold):
    import numpy as np
    boxes, logits = outputs['dets'][0], outputs['labels'][0]
    if logits.shape != (boxes.shape[0], 91) or boxes.shape[1] != 4:
        raise ValueError('RF-DETR sparse COCO output contract mismatch')
    if not np.isfinite(boxes).all() or not np.isfinite(logits).all():
        raise ValueError('Non-finite detector outputs')
    scores = np.exp(-np.logaddexp(0., -logits))
    indices = np.argsort(-scores.ravel(), kind='stable')[:300]
    predictions = []
    for index in indices:
        query, category = divmod(int(index), 91)
        score = float(scores.ravel()[index])
        if category not in ROAD or score < threshold:
            continue
        bbox = box_from_cxcywh(boxes[query], width, height)
        if bbox[2] > 0 and bbox[3] > 0:
            predictions.append({'image_id': image_id, 'category_id': category, 'bbox': bbox, 'score': score, 'queryIndex': query})
    return predictions


def coarse_predictions(predictions):
    # Upcast class labels only; no invented bus/truck subclasses. Collapse the
    # same RF query's competing labels inside one new coarse class to its max.
    result = []
    indexed = {}
    for pred in predictions:
        if pred['category_id'] not in COARSE:
            continue
        new = {**pred, 'category_id': COARSE[pred['category_id']]}
        if 'queryIndex' not in pred:
            result.append(new);continue
        key = (pred['image_id'], new['category_id'], pred['queryIndex'])
        if key not in indexed or new['score'] > indexed[key]['score']:
            indexed[key] = new
    return result + list(indexed.values())


def evaluate(gt_path, predictions, category_ids, output):
    import numpy as np
    from pycocotools.coco import COCO
    from pycocotools.cocoeval import COCOeval
    log = io.StringIO()
    with redirect_stdout(log):
        gt = COCO(str(gt_path))
        clean = [{k:v for k,v in pred.items() if k != 'queryIndex'} for pred in predictions]
        if not clean:
            raise RuntimeError('No predictions; fail the positive-control evaluation rather than report a misleading valid run')
        detected = gt.loadRes(clean)
        evaluator = COCOeval(gt, detected, 'bbox')
        evaluator.params.catIds = list(category_ids)
        evaluator.params.imgIds = sorted(gt.getImgIds())
        evaluator.params.maxDets = [1, 10, 100]
        evaluator.evaluate();evaluator.accumulate();evaluator.summarize()
    output.write_text(log.getvalue())
    per_class = {}
    for index, category in enumerate(category_ids):
        precision = evaluator.eval['precision'][:, :, index, 0, -1]
        valid = precision[precision > -1]
        per_class[gt.cats[category]['name']] = {'AP': float(valid.mean()) if valid.size else None}
    names = ['AP','AP50','AP75','APsmall','APmedium','APlarge','AR1','AR10','AR100','ARsmall','ARmedium','ARlarge']
    return {'metrics': {name: float(value) if value >= 0 else None for name,value in zip(names,evaluator.stats)},
            'perClass': per_class, 'maxDets': [1,10,100], 'iouThresholds': [.5,.55,.6,.65,.7,.75,.8,.85,.9,.95],
            'imageCount': len(evaluator.params.imgIds), 'categories': list(category_ids)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--onnx', type=Path, required=True)
    parser.add_argument('--model', choices=['rfdetr-small','rfdetr-medium','rfdetr-large'], required=True)
    parser.add_argument('--subset', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--threads', type=int, default=4)
    parser.add_argument('--minimum-score', type=float, default=.001)
    args = parser.parse_args()
    import numpy as np
    import onnxruntime as ort
    import torch
    if not 1 <= args.threads <= 4:
        raise ValueError('CPU evaluation is limited to one through four threads')
    torch.set_num_threads(args.threads)
    options = ort.SessionOptions();options.intra_op_num_threads=args.threads;options.inter_op_num_threads=1
    session = ort.InferenceSession(str(args.onnx), options, providers=['CPUExecutionProvider'])
    if session.get_providers() != ['CPUExecutionProvider']:
        raise RuntimeError('Unexpected non-CPU inference provider')
    manifest_path = args.subset / 'subset-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    gt_path = args.subset / 'instances_road_subset.json'
    coarse_gt = args.subset / 'instances_coarse_road_subset.json'
    if sha256(gt_path) != manifest['selectedGroundTruthSha256'] or sha256(coarse_gt) != manifest['coarseGroundTruthSha256']:
        raise RuntimeError('Evaluation ground truth changed after subset staging')
    resolution = {'rfdetr-small':512,'rfdetr-medium':576,'rfdetr-large':704}[args.model]
    names = [v.name for v in session.get_outputs()]
    if len(session.get_inputs()) != 1 or session.get_inputs()[0].name != 'input' or set(names) != {'dets','labels'}:
        raise RuntimeError('Model input/output names do not match the reviewed RF-DETR export')
    args.output.mkdir(parents=True, exist_ok=True)
    predictions = [];durations = [];started = time.perf_counter()
    for image in manifest['images']:
        path = args.subset / 'images' / image['fileName']
        if sha256(path) != image['sha256']:
            raise RuntimeError('Evaluation image changed after subset staging')
        tensor = preprocess_image(path, resolution, (image['width'],image['height']))
        before = time.perf_counter()
        outputs = dict(zip(names, session.run(None, {'input': tensor.numpy()})))
        durations.append(time.perf_counter()-before)
        predictions.extend(decode_rfdetr(outputs, image['id'], image['width'], image['height'], args.minimum_score))
    prediction_path = args.output / 'predictions.json'
    prediction_path.write_text(json.dumps(predictions,separators=(',',':'))+'\n')
    metrics = evaluate(gt_path, predictions, ROAD, args.output/'coco-eval.txt')
    coarse = evaluate(coarse_gt, coarse_predictions(predictions), [1,2,3], args.output/'coarse-coco-eval.txt')
    receipt = {'schemaVersion':'city.coco-road-evaluation.v1','model':args.model,'onnx':str(args.onnx),
        'onnxSha256':sha256(args.onnx),'subsetManifestSha256':sha256(manifest_path),
        'groundTruthSha256':sha256(gt_path),'predictionsSha256':sha256(prediction_path),
        'evaluatorSourceSha256':sha256(Path(__file__)),'provider':session.get_providers(),'cpuThreads':args.threads,
        'precision':'FP32 ONNX CPU','inputResolution':[resolution,resolution],'minimumScore':args.minimum_score,
        'preprocess':'RGB float tensor; direct bilinear resize, antialias=false; per-channel ImageNet normalization',
        'postprocess':'Sigmoid; global query x sparse-COCO-class top300; keep six road categories; no NMS',
        'imageCount':len(manifest['images']),'predictionCount':len(predictions), 'sixRoadClasses':metrics,
        'coarseRoadClasses':coarse,'coarsePolicy':'Person; bicycle/motorcycle upcast to two-wheeler; car/bus/truck upcast to vehicle; competing same-query class labels within a coarse class collapse to maximum score.',
        'crowdPolicy':manifest['crowdPolicy'],'ortVersion':ort.__version__, 'gpuUsed':False,
        'wallSeconds':time.perf_counter()-started,
        'cpuInferenceSeconds':{'mean':float(np.mean(durations)),'p50':float(np.percentile(durations,50)), 'p95':float(np.percentile(durations,95))},
        'scope':'Deterministic class-stratified 100-image COCO validation proxy using official GT and pycocotools. Not full COCO, elevated-camera/night/event accuracy, TensorRT precision accuracy or final-city qualification.'}
    (args.output/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt,indent=2))


if __name__ == '__main__':
    main()
