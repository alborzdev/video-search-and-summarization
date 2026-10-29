#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""CPU-only comparison of tracker query exclusivity on cached TensorRT outputs."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from evaluate_detectors import ROAD, coarse_predictions, decode_rfdetr, evaluate, sha256


def one_city_class_per_query(predictions):
    """Highest city-label score per image/query; never suppress spatial overlap."""
    selected = {}
    for prediction in predictions:
        key = (prediction['image_id'], prediction['queryIndex'])
        current = selected.get(key)
        if current is None or (-prediction['score'], prediction['category_id']) < (-current['score'], current['category_id']):
            selected[key] = prediction
    # Native reference order is score descending, then query/class on a tie.
    return sorted(selected.values(), key=lambda p: (p['image_id'], -p['score'], p['queryIndex'], p['category_id']))


def compare(subset, outputs, result):
    import numpy as np
    subset_file, run_file = subset / 'subset-manifest.json', outputs / 'run-receipt.json'
    manifest, run = json.loads(subset_file.read_text()), json.loads(run_file.read_text())
    if sha256(subset_file) != run['subsetManifestSha256']:
        raise ValueError('Cached outputs do not match the pinned subset')
    gt, coarse_gt = subset / 'instances_road_subset.json', subset / 'instances_coarse_road_subset.json'
    if sha256(gt) != manifest['selectedGroundTruthSha256'] or sha256(coarse_gt) != manifest['coarseGroundTruthSha256']:
        raise ValueError('Pinned annotations changed')
    files = {item['id']: item for item in run['outputs']}
    if len(files) != len(run['outputs']) or set(files) != {item['id'] for item in manifest['images']}:
        raise ValueError('Cached outputs do not cover the pinned image set exactly once')
    predictions = []
    for image in manifest['images']:
        item = files[image['id']]
        path = outputs / item['fileName']
        if sha256(path) != item['sha256']:
            raise ValueError('Cached TensorRT output hash changed')
        with np.load(path, allow_pickle=False) as arrays:
            predictions.extend(decode_rfdetr(arrays, image['id'], image['width'], image['height'], .001))
    result.mkdir(parents=True, exist_ok=False)
    candidates = {'reference-multilabel': predictions, 'one-city-class-per-query': one_city_class_per_query(predictions)}
    scores = {}
    for name, values in candidates.items():
        target = result / name
        target.mkdir()
        prediction_file = target / 'predictions.json'
        prediction_file.write_text(json.dumps(values, separators=(',', ':')) + '\n')
        live = [item for item in values if item['score'] >= .35]
        scores[name] = {
            'sixRoadClasses': evaluate(gt, values, ROAD, target / 'coco-eval.txt'),
            'coarseRoadClasses': evaluate(coarse_gt, coarse_predictions(values), [1, 2, 3], target / 'coarse-coco-eval.txt'),
            'predictionCountAtScore0001': len(values), 'predictionCountAtLiveScore035': len(live),
            'extraCityLabelsForSameQueryAtLiveScore035': len(live) - len({(p['image_id'], p['queryIndex']) for p in live}),
            'predictionsSha256': sha256(prediction_file),
        }
    baseline, candidate = scores.values()
    deltas = {
        taxonomy: {key: (candidate[taxonomy]['metrics'][key] - value) * 100
                   for key, value in baseline[taxonomy]['metrics'].items() if value is not None}
        for taxonomy in ('sixRoadClasses', 'coarseRoadClasses')
    }
    receipt = {
        'schemaVersion': 'city.query-policy-comparison.v1', 'writtenAt': datetime.now(timezone.utc).isoformat(),
        'model': run['model'], 'engineSha256': run['engineSha256'], 'batch': run['batch'], 'imageCount': len(files),
        'subsetManifestSha256': sha256(subset_file), 'cachedRunReceiptSha256': sha256(run_file),
        'comparisonSourceSha256': sha256(Path(__file__)),
        'referencePostprocessorSourceSha256': sha256(Path(__file__).with_name('evaluate_detectors.py')),
        'scores': scores, 'candidateDeltaPercentagePoints': deltas, 'gpuUsedForThisComparison': False,
        'policy': 'Reference global query/class top300 and city capability filtering, then one highest-scoring city class per query. Different queries are never spatially merged.',
        'scope': 'Paired CPU rescoring of cached actual TensorRT outputs on the same100-image COCO proxy. This does not correct fine-class mistakes or qualify live tracking/event accuracy.',
    }
    (result / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--subset', type=Path, required=True)
    parser.add_argument('--outputs', type=Path, required=True)
    parser.add_argument('--result', type=Path, required=True)
    args = parser.parse_args()
    receipt = compare(args.subset, args.outputs, args.result)
    print(json.dumps({'result': str(args.result), 'deltaPercentagePoints': receipt['candidateDeltaPercentagePoints']}, indent=2))
