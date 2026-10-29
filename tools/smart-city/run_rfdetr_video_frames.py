#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run a pinned RF-DETR ONNX graph on hash-pinned video JPEGs, CPU only.

The city.video-frames.v1 manifest provides image_id, source_id, frame_index,
file-PTS timestamp_ns, relative fileName, width, height and sha256. File PTS is
per-camera playback time; it is not a shared physical capture clock. The output
is an exact-coverage envelope usable by compare_detector_continuity.py.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path

from compare_detector_continuity import validate_manifest
from evaluate_detectors import ROAD, decode_rfdetr, preprocess_image, sha256
from evaluate_query_policy import one_city_class_per_query


def load_frames(manifest_path):
    raw = manifest_path.read_bytes()
    document = json.loads(raw)
    if document.get('schemaVersion') != 'city.video-frames.v1':
        raise ValueError('Expected city.video-frames.v1 manifest')
    ids, _ = validate_manifest(document)
    root = manifest_path.resolve().parent
    for frame in document['frames']:
        name = frame['fileName']
        if not isinstance(name, str) or not name or Path(name).is_absolute():
            raise ValueError('Frame filenames must be nonempty relative paths')
        path = (root / name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError('Frame path must be an existing file inside the manifest directory')
        expected = frame['sha256']
        if not isinstance(expected, str) or len(expected) != 64 or any(c not in '0123456789abcdef' for c in expected):
            raise ValueError('Frame sha256 must be a lowercase SHA256 digest')
        if sha256(path) != expected:
            raise ValueError(f'Frame hash mismatch for image {frame["image_id"]}')
        if any(isinstance(frame[k], bool) or not isinstance(frame[k], int) or frame[k] <= 0 for k in ('width', 'height')):
            raise ValueError('Frame dimensions must be positive integers')
    return document, ids, hashlib.sha256(raw).hexdigest()


def infer_frames(document, root, session, resolution, threshold, *, preprocess=preprocess_image,
                 decode=decode_rfdetr, policy=one_city_class_per_query):
    predictions, processed = [], []
    for frame in document['frames']:
        path = (root / frame['fileName']).resolve()
        # Recheck immediately before the actual pixel read after initial validation.
        if sha256(path) != frame['sha256']:
            raise ValueError(f'Frame changed during processing: {frame["image_id"]}')
        tensor = preprocess(path, resolution, (frame['width'], frame['height']))
        outputs = dict(zip(('dets', 'labels'), session.run(['dets', 'labels'], {'input': tensor.numpy()})))
        selected = policy(decode(outputs, frame['image_id'], frame['width'], frame['height'], threshold))
        predictions.extend(selected)
        processed.append(frame['image_id'])
    return processed, predictions


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--onnx', type=Path, required=True)
    p.add_argument('--model', choices=('small', 'medium'), required=True)
    p.add_argument('--expected-onnx-sha256', required=True)
    p.add_argument('--minimum-score', type=float, default=.35)
    p.add_argument('--threads', type=int, default=4)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if not 1 <= args.threads <= 4 or not math.isfinite(args.minimum_score) or not 0 <= args.minimum_score <= 1:
        p.error('Threads must be 1–4 and minimum score must be in [0,1]')
    if (len(args.expected_onnx_sha256) != 64 or
        any(c not in '0123456789abcdef' for c in args.expected_onnx_sha256)):
        p.error('Expected ONNX hash must be lowercase SHA256')
    document, expected_ids, manifest_hash = load_frames(args.manifest)
    model_hash = sha256(args.onnx)
    if model_hash != args.expected_onnx_sha256:
        raise ValueError('ONNX hash does not match the explicitly pinned model')
    if args.output.exists():
        raise FileExistsError('Output already exists; use a new receipt path')
    # Set before importing either framework. CPUExecutionProvider is selected explicitly.
    os.environ['CUDA_VISIBLE_DEVICES'] = ''
    import onnxruntime as ort
    import torch
    torch.set_num_threads(args.threads)
    options = ort.SessionOptions()
    options.intra_op_num_threads = args.threads
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(args.onnx), options, providers=['CPUExecutionProvider'])
    if session.get_providers() != ['CPUExecutionProvider']:
        raise RuntimeError('Unexpected ONNX Runtime provider')
    if len(session.get_inputs()) != 1 or session.get_inputs()[0].name != 'input' or {x.name for x in session.get_outputs()} != {'dets', 'labels'}:
        raise RuntimeError('ONNX input/output names differ from the pinned RF-DETR contract')
    resolution = 512 if args.model == 'small' else 576
    input_spec = session.get_inputs()[0]
    if input_spec.type != 'tensor(float)' or list(input_spec.shape[1:]) != [3, resolution, resolution]:
        raise RuntimeError('ONNX input type or dimensions do not match the declared model')
    processed, predictions = infer_frames(document, args.manifest.resolve().parent, session, resolution, args.minimum_score)
    if len(processed) != len(expected_ids) or set(processed) != expected_ids:
        raise RuntimeError('Inference did not cover each manifest frame exactly once')
    receipt = {'schemaVersion': 'city.detector-video-predictions.v1', 'processed_image_ids': processed,
        'predictions': predictions,
        'provenance': {'manifestSha256': manifest_hash, 'onnxSha256': model_hash, 'model': 'rfdetr-' + args.model,
            'runnerSha256': sha256(Path(__file__)), 'preprocessDecoderSha256': sha256(Path(__file__).with_name('evaluate_detectors.py')),
            'queryPolicySha256': sha256(Path(__file__).with_name('evaluate_query_policy.py')),
            'provider': 'CPUExecutionProvider', 'gpuUsed': False, 'ortVersion': ort.__version__,
            'torchVersion': str(torch.__version__), 'threads': args.threads, 'resolution': resolution,
            'minimumScore': args.minimum_score, 'supportedCocoCategoryIds': sorted(ROAD),
            'preprocess': 'RGB, direct bilinear square resize, antialias=false, ImageNet normalization, FP32 ONNX input',
            'postprocess': 'sigmoid global query/class top300, city class filter, one highest city class per query, no spatial NMS',
            'timestampBasis': 'per-camera recorded file PTS; not shared capture clock',
            'scope': 'CPU FP32 ONNX outputs on supplied JPEGs; not the live TensorRT engine, tracking or identity accuracy.'}}
    with args.output.open('x') as out:
        json.dump(receipt, out, separators=(',', ':'), allow_nan=False); out.write('\n')
    print(f'Wrote {len(processed)} processed frames and {len(predictions)} predictions to {args.output}')


if __name__ == '__main__':
    main()
