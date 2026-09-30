#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Stage a single-camera RT-DETR/NvDCF pipeline without changing shared templates."""

import argparse
import configparser
import hashlib
import json
from pathlib import Path
import shutil

import yaml

MODEL_NAME = 'rtdetr_warehouse_v1.0.2.fp16.onnx'
MODEL_SHA256 = '0a22264542514149bead6e8582499d9758d51e3fde2892d9d2cc378a60426267'


def configure(templates, storage):
    model = storage / MODEL_NAME
    with model.open('rb') as handle:
        digest = hashlib.file_digest(handle, 'sha256').hexdigest()
    if digest != MODEL_SHA256:
        raise RuntimeError('The Spark detector model does not match its published checksum.')
    configs = storage / 'configs'
    configs.mkdir(parents=True, exist_ok=True)
    for name in ('ds-detector-labels.txt', 'ds-kafka-config.txt'):
        shutil.copyfile(templates / name, configs / name)
    main = configparser.ConfigParser(interpolation=None, strict=False)
    main.read(templates / 'ds-main-config.txt')
    overrides = {
        'tiled-display': {'enable': '3', 'rows': '1', 'columns': '1', 'compute-hw': '1'},
        'source-list': {'num-source-bins': '0', 'max-batch-size': '1', 'http-ip': '127.0.0.1',
                        'http-port': '9000', 'low-latency-mode': '0'},
        'source-attr-all': {'select-rtp-protocol': '4', 'drop-on-latency': '0'},
        'streammux': {'batch-size': '1', 'width': '1280', 'height': '720', 'enable-padding': '1',
                      'attach-sys-ts-as-ntp': '1'},
        'primary-gie': {'batch-size': '1', 'config-file': str(configs / 'ds-pgie-config.yml')},
        'tracker': {'enable': '1', 'compute-hw': '1',
                    'll-config-file': str(configs / 'ds-nvdcf-accuracy-tracker-config.yml')},
        'text-embedder': {'enable': '0'},
        'visionencoder': {'enable': '0'},
        'secondary-gie0': {'enable': '0'},
        'sink0': {'enable': '0'},
        'sink1': {'enable': '1', 'msg-broker-config': str(configs / 'ds-kafka-config.txt')},
        'sink2': {'enable': '0'},
        'osd': {'enable': '0'},
    }
    for section, values in overrides.items():
        if not main.has_section(section):
            main.add_section(section)
        for key, value in values.items():
            main.set(section, key, value)
    pgie = yaml.safe_load((templates / 'ds-pgie-config.yml').read_text())
    pgie['property'].update({
        'batch-size': 1,
        'onnx-file': str(model),
        'model-engine-file': str(storage / (MODEL_NAME + '_b1_gpu0_fp16.engine')),
        'labelfile-path': str(configs / 'ds-detector-labels.txt'),
    })
    tracker = yaml.safe_load((templates / 'ds-nvdcf-accuracy-tracker-config.yml').read_text())
    # Legacy NvDCF uses CUDA directly. VPI backend options apply only to the
    # separate VPI tracker implementation and are unsupported by this image.
    tracker['VisualTracker']['visualTrackerType'] = 1
    tracker['VisualTracker'].pop('vpiBackend4DcfTracker', None)
    tracker['TargetManagement']['maxTargetsPerStream'] = 50
    tracker['ReID'].update({'reidType': 0, 'outputReidTensor': 0})
    for name, value in [('ds-pgie-config.yml', pgie), ('ds-nvdcf-accuracy-tracker-config.yml', tracker)]:
        target = configs / name
        if target.exists() and not target.with_suffix(target.suffix + '.bak').exists():
            shutil.copyfile(target, target.with_suffix(target.suffix + '.bak'))
            target.with_suffix(target.suffix + '.bak').chmod(0o600)
        target.write_text(yaml.safe_dump(value, sort_keys=False))
    target = configs / 'ds-main-config.txt'
    if target.exists() and not target.with_suffix('.txt.bak').exists():
        shutil.copyfile(target, target.with_suffix('.txt.bak'))
        target.with_suffix('.txt.bak').chmod(0o600)
    with target.open('w') as handle:
        main.write(handle, space_around_delimiters=False)
    print(json.dumps({'model_sha256': digest, 'source_capacity': 1, 'tracker': 'NvDCF CUDA',
                      'reid': False, 'recording_started': False, 'config': str(target)}))
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--templates', type=Path, default=Path('/opt/spark-detector-templates'))
    parser.add_argument('--storage', type=Path, default=Path('/opt/storage'))
    args = parser.parse_args()
    configure(args.templates, args.storage)
