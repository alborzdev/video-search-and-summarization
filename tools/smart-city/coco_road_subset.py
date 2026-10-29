#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Stage a deterministic class-balanced COCO road-user evaluation proxy.

Annotations remain official COCO. Sample only non-crowd positives; retain crowd
annotations for COCOeval's standard ignore matching. Image licenses vary.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import time
import urllib.request
import zipfile

ANNOTATIONS_URL = 'https://s3.amazonaws.com/images.cocodataset.org/annotations/annotations_trainval2017.zip'
ROAD_CLASSES = {1: 'person', 2: 'bicycle', 3: 'car', 4: 'motorcycle', 6: 'bus', 8: 'truck'}
SELECTION_REVISION = 'ct-city-coco-road-roundrobin-v1'


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def download(url: str, destination: Path) -> None:
    if destination.exists():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + '.partial')
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=90) as response, partial.open('wb') as output:
                shutil.copyfileobj(response, output, 1024 * 1024)
            partial.replace(destination)
            return
        except Exception:
            partial.unlink(missing_ok=True)
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def select(data: dict, count: int = 100, seed: str = '20261022') -> tuple[list[int], dict[int, int]]:
    if count < len(ROAD_CLASSES):
        raise ValueError('Subset must have at least one anchor image per road class')
    image_ids = {image['id'] for image in data['images']}
    candidates = {category: set() for category in ROAD_CLASSES}
    for annotation in data['annotations']:
        category = annotation['category_id']
        if category in candidates and not annotation.get('iscrowd', 0) and annotation.get('area', 0) > 0:
            bbox = annotation.get('bbox', [])
            if len(bbox) == 4 and bbox[2] > 0 and bbox[3] > 0 and annotation['image_id'] in image_ids:
                candidates[category].add(annotation['image_id'])
    if any(not ids for ids in candidates.values()):
        raise ValueError('Every target road class needs eligible non-crowd images')
    ranked = {category: sorted(ids, key=lambda image_id: hashlib.sha256(
        f'{SELECTION_REVISION}:{seed}:{category}:{image_id}'.encode()).hexdigest())
        for category, ids in candidates.items()}
    selected = []
    chosen = set()
    anchors = {}
    while len(selected) < count:
        progress = False
        for category in ROAD_CLASSES:
            next_id = next((image_id for image_id in ranked[category] if image_id not in chosen), None)
            if next_id is not None:
                chosen.add(next_id);selected.append(next_id);anchors[next_id] = category;progress = True
            if len(selected) == count:
                break
        if not progress:
            raise ValueError('Not enough unique class-positive images for the requested subset')
    return selected, anchors


def coarse_road(data: dict) -> dict:
    # A separate common-vocabulary comparison; never label it six-class AP.
    mapping = {1: 1, 2: 2, 4: 2, 3: 3, 6: 3, 8: 3}
    return {**data, 'categories': [{'id': 1, 'name': 'person'}, {'id': 2, 'name': 'two-wheeler'}, {'id': 3, 'name': 'vehicle'}],
            'annotations': [{**a, 'category_id': mapping[a['category_id']]} for a in data['annotations'] if a['category_id'] in mapping]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--count', default=100, type=int)
    parser.add_argument('--seed', default='20261022')
    parser.add_argument('--workers', default=4, type=int)
    parser.add_argument('--annotation-zip', type=Path)
    args = parser.parse_args()
    root = args.directory;root.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(root).free < 2 * 1024**3:
        raise RuntimeError('At least 2 GiB of free staging disk required')
    archive = args.annotation_zip or root / 'annotations_trainval2017.zip'
    download(ANNOTATIONS_URL, archive)
    with zipfile.ZipFile(archive) as source:
        info = source.getinfo('annotations/instances_val2017.json')
        if info.file_size > 100 * 1024**2:
            raise RuntimeError('Unexpected COCO validation annotation size')
        annotations = source.read(info)
    data = json.loads(annotations)
    selected, anchors = select(data, args.count, args.seed)
    selected_set = set(selected)
    image_by_id = {image['id']: image for image in data['images']}
    subset = {**data, 'images': [image_by_id[image_id] for image_id in selected],
              'annotations': [a for a in data['annotations'] if a['image_id'] in selected_set]}
    gt = root / 'instances_road_subset.json'
    gt.write_text(json.dumps(subset, separators=(',', ':')) + '\n')
    coarse = root / 'instances_coarse_road_subset.json'
    coarse.write_text(json.dumps(coarse_road(subset), separators=(',', ':')) + '\n')
    images_dir = root / 'images';images_dir.mkdir(exist_ok=True)
    def stage_image(image_id):
        image = image_by_id[image_id]
        name = image['file_name']
        if Path(name).name != name:
            raise RuntimeError('Unexpected image file path')
        url = f'https://s3.amazonaws.com/images.cocodataset.org/val2017/{name}'
        target = images_dir / name;download(url, target)
        from PIL import Image
        with Image.open(target) as pixels:
            pixels.verify()
        return {'id': image_id, 'fileName': name, 'sha256': sha256(target),
                'width': image['width'], 'height': image['height'], 'anchorClass': ROAD_CLASSES[anchors[image_id]],
                'licenseId': image['license'], 'license': next((v for v in data['licenses'] if v['id'] == image['license']), None),
                'sourceUrl': url, 'flickrUrl': image.get('flickr_url')}
    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 8))) as pool:
        images = list(pool.map(stage_image, selected))
    counts = {}
    for category, name in ROAD_CLASSES.items():
        positives = [a for a in subset['annotations'] if a['category_id'] == category and not a.get('iscrowd', 0)]
        counts[name] = {'anchorImages': sum(anchors[i] == category for i in selected),
                        'positiveImages': len({a['image_id'] for a in positives}), 'nonCrowdInstances': len(positives),
                        'crowdAnnotationsRetainedForIgnore': sum(a['category_id'] == category and bool(a.get('iscrowd')) for a in subset['annotations'])}
    receipt = {'schemaVersion': 'city.coco-subset.v1', 'selectionRevision': SELECTION_REVISION, 'seed': args.seed,
        'source': 'COCO 2017 validation', 'annotationUrl': ANNOTATIONS_URL,
        'annotationZipSha256': sha256(archive), 'officialValidationJsonSha256': hashlib.sha256(annotations).hexdigest(),
        'selectedGroundTruthSha256': sha256(gt), 'coarseGroundTruthSha256': sha256(coarse),
        'imageCount': len(images), 'classCounts': counts, 'images': images,
        'selection': 'Round-robin person/bicycle/car/motorcycle/bus/truck; deterministic SHA256 rank per class; each image chosen once; non-crowd positive anchors; all sizes retained.',
        'crowdPolicy': 'Crowds never qualify an anchor image; official crowd annotations retained and ignored by standard COCOeval matching.',
        'annotationTerms': 'COCO annotations under CC BY 4.0; each image retains its own COCO/Flickr license record.',
        'scope': 'Internal detector proxy evaluation. Not final intersection, elevated-camera, night, event or cross-camera accuracy. Do not use these images as booth content without checking individual image terms.',
        'gpuUsed': False}
    (root / 'subset-manifest.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({k: v for k, v in receipt.items() if k != 'images'}, indent=2))


if __name__ == '__main__':
    main()
