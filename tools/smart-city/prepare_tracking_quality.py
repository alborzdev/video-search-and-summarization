#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Prepare the measured car/truck + person-pose configuration; never activate it.

Only static calibration, class priors and NVIDIA model assets enter this bundle.
Reference actor identities/positions and comparison scores are never inputs.
"""
import argparse
import json
from pathlib import Path
import shutil

import yaml

import prepare_mv3dt_native as native

ONNX_SHA = '0452b785a70fcd6bc5bd4069249bdfd85eb139c9e9216bcf81f89df33945d028'
ONNX = 'bodypose3dnet/bodypose3dnet_accuracy.onnx'
ENGINE = ONNX + '_b1_gpu0_fp16.engine'


def prepare(root, snapshot, image, engine, confidence):
    if confidence not in (.5, .75, .925):
        raise ValueError('Select an explicitly evaluated keypoint confidence')
    result = native.prepare(root, snapshot, image)
    models = root/'.spark/city/models'
    onnx = models/ONNX
    engine = engine.resolve()
    receipt = json.loads((engine.parent/'receipt.json').read_text())
    trial = yaml.safe_load((engine.parent/'tracker.yml').read_text())
    if (receipt.get('result') != 'complete' or engine.name != 'bodypose.onnx_b1_gpu0_fp16.engine'
            or native.calibration.sha(onnx.read_bytes()) != ONNX_SHA
            or native.calibration.sha((engine.parent/'bodypose.onnx').read_bytes()) != ONNX_SHA
            or trial['PoseEstimator']['operateOnClassIds'] != [0]
            or trial['PoseEstimator']['poseInferenceInterval'] != -1
            or not 0 < engine.stat().st_size < 512*1024*1024):
        raise ValueError('Expected a completed person-only trial of the pinned NVIDIA ONNX model')
    engine_sha = native.calibration.sha(engine.read_bytes())
    cached = models/ENGINE
    if cached.exists():
        if native.calibration.sha(cached.read_bytes()) != engine_sha:
            raise ValueError('Existing cached pose engine differs; preserve it for review')
    else:
        with cached.open('xb') as output, engine.open('rb') as source:
            shutil.copyfileobj(source, output)
    pose = dict(trial['PoseEstimator'], onnxFile='/models/'+ONNX, modelEngineFile='/models/'+ENGINE)
    files = result['files']
    for name in ('tracker-mv3dt.experimental.yml', 'tracker-single-0.yml', 'tracker-single-1.yml'):
        tracker = yaml.safe_load(files[name])
        tracker['BaseConfig']['checkClassMatch'] = 1
        tracker['PoseEstimator'] = pose
        tracker['ObjectModelProjection']['minPoseConfidence'] = confidence
        files[name] = yaml.safe_dump(tracker, sort_keys=False).encode()
    policy = result['profile']['identityPolicyVariant']
    policy.update(trackingClassPolicy='car-truck-family-v1', rawDetectorClassesPreserved=True,
        personPose=dict(model='NVIDIA TAO BodyPose3DNet', classIds=[0], interval=-1,
            minKeypointConfidence=confidence, onnxSha256=ONNX_SHA, engineSha256=engine_sha),
        vehicleGeometry='Inherited class cylinder priors; long-vehicle accuracy remains unqualified',
        reidEnabled=False, productionQualified=False)
    manifest = json.loads(files['manifest.json'])
    manifest['identityPolicyVariant'] = policy
    files['manifest.json'] = native.calibration.encoded(manifest)
    profile = result['profile']
    profile.update(trackingClassPolicy='car-truck-family-v1', auxiliaryModelAssets={
        relative: dict(bytes=(models/relative).stat().st_size, sha256=native.calibration.sha((models/relative).read_bytes()))
        for relative in (ONNX, ENGINE)})
    profile['fileHashes'] = {result['prefix']+name: native.calibration.sha(data) for name,data in sorted(files.items())}
    result['modelRoot'] = models.resolve()
    result['receipt'].update(schemaVersion='city.tracking-quality-preparation.v1', policy=policy,
        candidateProfileSha256=native.calibration.sha(native.calibration.encoded(profile)),
        candidateFileHashes=profile['fileHashes'], auxiliaryModelAssets=profile['auxiliaryModelAssets'])
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--snapshot', required=True)
    parser.add_argument('--image-id', required=True)
    parser.add_argument('--engine', type=Path, required=True)
    parser.add_argument('--pose-confidence', type=float, choices=(.5, .75, .925), required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.root.resolve(), args.snapshot, args.image_id, args.engine, args.pose_confidence)
    native.write_review(args.output.resolve(), result)
    path = args.output/'receipt.json'
    receipt = json.loads(path.read_text())
    receipt['generatorSha256'] = native.calibration.sha(Path(__file__).read_bytes())
    path.write_bytes(native.calibration.encoded(receipt))
    print(json.dumps(receipt, indent=2))
