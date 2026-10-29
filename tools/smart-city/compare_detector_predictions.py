#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Compare COCO-format detector predictions against one labeled image set.

Predictions are JSON lists with image_id, category_id, bbox [x,y,w,h], score.
Category IDs must use the ground-truth taxonomy; map predictions explicitly
before using this tool. Counts of model-to-model matches are diagnostic only.
Empty prediction lists are valid. Inputs alone cannot prove every image was run.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import hashlib
import io
import json
import math
from collections import defaultdict
from pathlib import Path


def read(path):
    data = path.read_bytes()
    return json.loads(data), hashlib.sha256(data).hexdigest()


def validate(gt, predictions, supported, image_ids):
    cats = {c['id'] for c in gt['categories']}
    images = {i['id'] for i in gt['images']}
    if not supported or not set(supported) <= cats:
        raise ValueError('Supported categories must be a non-empty subset of GT categories')
    if not image_ids or not set(image_ids) <= images:
        raise ValueError('Image IDs must be a non-empty subset of GT images')
    for pred in predictions:
        if pred['image_id'] not in images or pred['category_id'] not in supported:
            raise ValueError('Prediction has unknown image or unsupported category')
        box = pred['bbox']
        if len(box) != 4 or any(not isinstance(x, (int, float)) or not math.isfinite(x) for x in box):
            raise ValueError('Prediction bbox must have four finite numbers')
        if box[2] <= 0 or box[3] <= 0:
            raise ValueError('Prediction bbox must have positive width and height')
        score = pred['score']
        if not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError('Prediction score must be finite and between zero and one')


def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
    intersection = max(0, x2-x1) * max(0, y2-y1)
    return intersection / (a[2]*a[3] + b[2]*b[3] - intersection)


def agreement(a, b, image_ids, categories, min_score, min_iou):
    """Greedy highest-IoU matching within each image and category."""
    images, cats = set(image_ids), set(categories)
    grouped_a, grouped_b = defaultdict(list), defaultdict(list)
    for rows, groups in ((a, grouped_a), (b, grouped_b)):
        for pred in rows:
            if pred['image_id'] in images and pred['category_id'] in cats and pred['score'] >= min_score:
                groups[(pred['image_id'], pred['category_id'])].append(pred)
    totals = {'matched': 0, 'onlyA': 0, 'onlyB': 0}
    per_class = {str(c): dict(totals) for c in sorted(cats)}
    per_image = {str(i): dict(totals) for i in sorted(images)}
    for key in sorted(set(grouped_a) | set(grouped_b)):
        aa, bb = grouped_a[key], grouped_b[key]
        candidates = sorted(((iou(x['bbox'], y['bbox']), i, j) for i, x in enumerate(aa) for j, y in enumerate(bb)),
                            key=lambda item: (-item[0], item[1], item[2]))
        used_a, used_b = set(), set()
        for overlap, i, j in candidates:
            if overlap < min_iou:
                break
            if i not in used_a and j not in used_b:
                used_a.add(i); used_b.add(j)
        counts = {'matched': len(used_a), 'onlyA': len(aa)-len(used_a), 'onlyB': len(bb)-len(used_b)}
        for name, value in counts.items():
            totals[name] += value
            per_class[str(key[1])][name] += value
            per_image[str(key[0])][name] += value
    return {'totals': totals, 'perCategory': per_class, 'perImage': per_image,
            'minimumScore': min_score, 'minimumIoU': min_iou,
            'matching': 'greedy highest IoU, one-to-one, same image and category',
            'scope': 'Detector agreement only, not precision, recall, accuracy, or tracking quality.'}


def coco_score(gt_path, predictions, image_ids, categories):
    if not categories:
        return None
    try:
        from pycocotools.coco import COCO
        from pycocotools.cocoeval import COCOeval
    except ImportError as exc:
        raise RuntimeError('pycocotools is required for COCO scoring; use the isolated city evaluation environment') from exc
    with redirect_stdout(io.StringIO()):
        gt = COCO(str(gt_path))
        # COCO.loadRes indexes the first result and cannot accept an empty list.
        # An explicitly indexed empty result dataset yields zero AP where GT exists.
        if predictions:
            results = gt.loadRes([{k: p[k] for k in ('image_id', 'category_id', 'bbox', 'score')} for p in predictions])
        else:
            results = COCO()
            results.dataset = {'images': list(gt.dataset['images']), 'categories': list(gt.dataset['categories']), 'annotations': []}
            results.createIndex()
        evaluator = COCOeval(gt, results, 'bbox')
        evaluator.params.imgIds = sorted(image_ids)
        evaluator.params.catIds = sorted(categories)
        evaluator.evaluate(); evaluator.accumulate(); evaluator.summarize()
    precision = evaluator.eval['precision']
    per_class = {}
    for index, category in enumerate(sorted(categories)):
        values = precision[:, :, index, 0, -1]
        valid = values[values > -1]
        per_class[str(category)] = float(valid.mean()) if valid.size else None
    return {'AP50_95': float(evaluator.stats[0]) if evaluator.stats[0] >= 0 else None,
            'AP50': float(evaluator.stats[1]) if evaluator.stats[1] >= 0 else None,
            'perCategoryAP50_95': per_class, 'categories': sorted(categories), 'imageCount': len(image_ids)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ground-truth', type=Path, required=True)
    p.add_argument('--a', type=Path, required=True)
    p.add_argument('--b', type=Path, required=True)
    p.add_argument('--a-categories', type=int, nargs='+', required=True)
    p.add_argument('--b-categories', type=int, nargs='+', required=True)
    p.add_argument('--image-ids', type=Path, help='Optional JSON list; default is every GT image')
    p.add_argument('--agreement', action='store_true')
    p.add_argument('--minimum-score', type=float, default=.3)
    p.add_argument('--minimum-iou', type=float, default=.5)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if not 0 <= args.minimum_score <= 1 or not 0 <= args.minimum_iou <= 1:
        p.error('Thresholds must be between zero and one')
    gt, gt_hash = read(args.ground_truth)
    a, a_hash = read(args.a); b, b_hash = read(args.b)
    images, ids_hash = read(args.image_ids) if args.image_ids else ([i['id'] for i in gt['images']], None)
    if len(set(images)) != len(images):
        raise ValueError('Duplicate selected image IDs')
    sa, sb = set(args.a_categories), set(args.b_categories)
    validate(gt, a, sa, images); validate(gt, b, sb, images)
    common = sa & sb
    receipt = {'schemaVersion': 'city.detector-comparison.v1',
               'inputSha256': {'groundTruth': gt_hash, 'a': a_hash, 'b': b_hash, 'imageIds': ids_hash,
                               'evaluator': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
               'imageIds': sorted(images), 'supportedCategories': {'a': sorted(sa), 'b': sorted(sb), 'common': sorted(common)},
               'scope': 'Scores use supplied labeled frames; absent prediction rows do not prove inference coverage. No category mapping is inferred.',
               'coco': {'aSupported': coco_score(args.ground_truth, a, images, sa),
                        'bSupported': coco_score(args.ground_truth, b, images, sb),
                        'aCommon': coco_score(args.ground_truth, a, images, common),
                        'bCommon': coco_score(args.ground_truth, b, images, common)}}
    if args.agreement:
        receipt['agreement'] = agreement(a, b, images, common, args.minimum_score, args.minimum_iou)
    with args.output.open('x') as f:
        json.dump(receipt, f, indent=2, allow_nan=False); f.write('\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
