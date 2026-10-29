#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Stage the evaluated Spark TrafficCamNet engine for an explicit simulation trial.

The evaluated engine remains on its original target GPU; this copies already
pinned local files without downloading or building. It does not select a model,
start a worker, or change the memory reserve.
"""
import argparse
import json
from pathlib import Path
import shutil

import model_profile


def stage(root: Path):
    root = root.resolve()
    city = model_profile._directory(root, 'spark')
    source = city/'challengers/nvidia-r18'
    built = city/'challengers/nvidia-r18-isolated-20261026-corrected'
    target = city/'models/trafficcamnet-transformer-r18'
    engine = city/'models/trafficcamnet-transformer-r18-fp16-b2.engine'
    lock = json.loads((root/'tools/smart-city/artifacts.lock.json').read_text())['trafficCamNetTransformer']
    sources = {
        engine: (built/'trafficcamnet-r18-fp16-b2.engine', lock['sparkObservedEngineSha256']),
        target/'model.onnx': (source/'resnet18_trafficcamnet_rtdetr.onnx', lock['onnxSha256']),
        target/'build-receipt.json': (built/'build-receipt.json', None),
        target/'positive-receipt.json': (built/'positive-receipt.json', None),
    }
    # Validate all sources before writing anything. Do not overwrite or follow links.
    for destination, (origin, expected) in sources.items():
        model_profile._controlled(origin, city); model_profile._controlled(destination, city)
        if not origin.is_file() or (expected and model_profile.digest(origin) != expected):
            raise model_profile.ProfileError(f'Invalid TrafficCamNet source {origin.name}')
        if destination.exists() and (not destination.is_file() or model_profile.digest(destination) != model_profile.digest(origin)):
            raise model_profile.ProfileError(f'Refusing to overwrite different staged file {destination.name}')
    target.mkdir(parents=True, exist_ok=True)
    for destination, (origin, _) in sources.items():
        if not destination.exists():
            # A hard link is deliberately not used: staged files must not share a mutable inode.
            with origin.open('rb') as src, destination.open('xb') as dst:
                shutil.copyfileobj(src, dst, 1024*1024)
    return model_profile.config_for_model(root, 'spark', model_profile.TRAFFIC)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=model_profile.ROOT)
    args=parser.parse_args()
    print(json.dumps(stage(args.root),indent=2))


if __name__ == '__main__':
    main()
