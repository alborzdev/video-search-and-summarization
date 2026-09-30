#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Check Spark hardware selection and model staging against the shared template."""

import configparser
import contextlib
import hashlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / 'deploy/docker/industry-profiles/warehouse-operations/warehouse-2d-app/deepstream/configs'
SPEC = importlib.util.spec_from_file_location('spark_detector_config', ROOT / 'deploy/docker/spark/configure-detector.py')
CONFIG = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONFIG)


class DetectorConfigTest(unittest.TestCase):
    def test_corrupt_model_refused_before_any_configuration_write(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = Path(directory)
            (storage / CONFIG.MODEL_NAME).write_bytes(b'corrupt download')
            with self.assertRaisesRegex(RuntimeError, 'checksum'):
                CONFIG.configure(TEMPLATES, storage)
            self.assertFalse((storage / 'configs').exists())

    def test_cuda_single_source_and_reusable_engine_without_template_changes(self):
        before = {path.name: path.read_bytes() for path in TEMPLATES.iterdir() if path.is_file()}
        with tempfile.TemporaryDirectory() as directory:
            storage = Path(directory)
            model_bytes = b'validated fixture model'
            (storage / CONFIG.MODEL_NAME).write_bytes(model_bytes)
            engine = storage / (CONFIG.MODEL_NAME + '_b1_gpu0_fp16.engine')
            engine.write_bytes(b'existing target engine')
            with patch.object(CONFIG, 'MODEL_SHA256', hashlib.sha256(model_bytes).hexdigest()):
                with contextlib.redirect_stdout(io.StringIO()):
                    main_path = CONFIG.configure(TEMPLATES, storage)
                    first = main_path.read_bytes()
                    CONFIG.configure(TEMPLATES, storage)
            self.assertEqual(engine.read_bytes(), b'existing target engine')
            self.assertEqual(main_path.read_bytes(), first)
            self.assertEqual(main_path.with_suffix('.txt.bak').read_bytes(), first)
            main = configparser.ConfigParser(interpolation=None)
            main.read(main_path)
            self.assertEqual(main['source-list']['max-batch-size'], '1')
            self.assertEqual(main['source-list']['num-source-bins'], '0')
            self.assertEqual(main['source-list']['http-ip'], '127.0.0.1')
            self.assertEqual(main['source-attr-all']['select-rtp-protocol'], '4')
            self.assertEqual(main['streammux']['batch-size'], '1')
            self.assertEqual(main['primary-gie']['batch-size'], '1')
            self.assertEqual(main['tracker']['enable'], '1')
            self.assertEqual(main['tracker']['compute-hw'], '1')
            self.assertEqual(main['tiled-display']['compute-hw'], '1')
            self.assertEqual(main['sink1']['enable'], '1')
            self.assertEqual(main['sink1']['topic'], 'mdx-raw')
            for section in ('visionencoder', 'text-embedder', 'secondary-gie0'):
                self.assertEqual(main[section]['enable'], '0')
            pgie = yaml.safe_load((storage / 'configs/ds-pgie-config.yml').read_text())
            self.assertEqual(pgie['property']['batch-size'], 1)
            self.assertEqual(pgie['property']['onnx-file'], str(storage / CONFIG.MODEL_NAME))
            tracker = yaml.safe_load((storage / 'configs/ds-nvdcf-accuracy-tracker-config.yml').read_text())
            self.assertEqual(tracker['VisualTracker']['visualTrackerType'], 1)
            self.assertNotIn('vpiBackend4DcfTracker', tracker['VisualTracker'])
            self.assertEqual(tracker['ReID']['reidType'], 0)
            self.assertEqual(tracker['ReID']['outputReidTensor'], 0)
        after = {path.name: path.read_bytes() for path in TEMPLATES.iterdir() if path.is_file()}
        self.assertEqual(before, after)


if __name__ == '__main__':
    unittest.main()
