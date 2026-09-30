# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Read-only renderer and mocked startup checks for the opt-in Spark worker."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('spark_detector_bootstrap', Path(__file__).with_name('bootstrap.py'))
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)


class DetectorTests(unittest.TestCase):
    def test_actual_compose_opt_in_preserves_models_and_saved_settings(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(b, 'STATE', Path(temp)), contextlib.redirect_stdout(io.StringIO()):
            data = str(Path(temp) / 'data')
            b.render('192.0.2.10', data, '172.17.0.1', reserve_gib=24, cached_models=True)
            baseline = json.loads((b.STATE / 'compose.json').read_text())
            self.assertNotIn('spark-perception', baseline['services'])
            self.assertEqual(baseline['services']['vss-agent']['environment']['VSS_WAREHOUSE_RTVI_CV_URL'], '')
            b.render('192.0.2.10', data, '172.17.0.1', detector_enabled=True)
            enabled = json.loads((b.STATE / 'compose.json').read_text())
            services = enabled['services']
            worker = services['spark-perception']
            self.assertEqual(set(services), set(baseline['services']) | {'spark-perception'})
            self.assertFalse(any('perception' in name for name in services if name != 'spark-perception'))
            for name in baseline['services']:
                if name not in ('vss-agent', 'vss-ui'):
                    self.assertEqual(services[name], baseline['services'][name], name)
            for name, allowed in [('vss-agent', ('VSS_WAREHOUSE_RTVI_CV_URL', 'VSS_WAREHOUSE_MAX_SOURCES')),
                                  ('vss-ui', ('RTVI_CV_HEALTH_URL',))]:
                before, after = baseline['services'][name].copy(), services[name].copy()
                before['environment'] = {k: v for k, v in before['environment'].items() if k not in allowed}
                after['environment'] = {k: v for k, v in after['environment'].items() if k not in allowed}
                self.assertEqual(before, after)
            self.assertEqual(worker['image'], 'nvcr.io/nvidia/vss-core/vss-rt-cv:3.2.1-sbsa')
            self.assertEqual(worker['runtime'], 'nvidia')
            self.assertEqual(worker['network_mode'], 'host')
            self.assertEqual(worker['restart'], 'no')
            self.assertEqual(worker['command'], ['bash', '/opt/spark/detector-start.sh'])
            self.assertEqual(worker['environment']['NUM_SENSORS'], '1')
            self.assertEqual(worker['environment']['DS_TRACKER_REID'], 'false')
            self.assertEqual(worker['environment']['HARDWARE_PROFILE'], 'DGX-SPARK')
            self.assertEqual(worker['mem_limit'], '6g')
            self.assertEqual(worker['memswap_limit'], worker['mem_limit'])
            self.assertEqual(worker['shm_size'], '2g')
            self.assertEqual(float(worker['cpus']), 4)
            self.assertNotIn('privileged', worker)
            mounts = {m['target']: m for m in worker['volumes']}
            self.assertTrue(mounts['/opt/spark']['read_only'])
            self.assertTrue(mounts['/opt/spark-detector-templates']['read_only'])
            self.assertTrue(mounts['/opt/spark-detector-templates']['source'].endswith('/warehouse-2d-app/deepstream/configs'))
            self.assertEqual(mounts['/opt/storage']['source'], str(Path(data) / 'models/spark-detector'))
            self.assertFalse(mounts['/opt/storage']['bind']['create_host_path'])
            self.assertEqual(services['vss-agent']['environment']['VSS_WAREHOUSE_RTVI_CV_URL'], 'http://127.0.0.1:9000')
            self.assertEqual(services['vss-agent']['environment']['VSS_TRAFFIC_RTVI_CV_URL'], '')
            self.assertEqual(services['vss-agent']['environment']['VSS_WAREHOUSE_MAX_SOURCES'], '1')
            self.assertIn('127.0.0.1:9000', services['vss-ui']['environment']['RTVI_CV_HEALTH_URL'])
            self.assertEqual((b.STATE / 'compose.json').stat().st_mode & 0o777, 0o600)
            settings = json.loads((b.STATE / 'settings.json').read_text())
            self.assertEqual(settings['reserve_gib'], 24)
            self.assertTrue(settings['cached_models'])
            self.assertTrue(settings['detector_enabled'])
            b.render('192.0.2.10', data, '172.17.0.1')
            self.assertIn('spark-perception', json.loads((b.STATE / 'compose.json').read_text())['services'])
            b.render('192.0.2.10', data, '172.17.0.1', detector_enabled=False)
            disabled = json.loads((b.STATE / 'compose.json').read_text())
            self.assertEqual(disabled, baseline)

    def test_saved_invalid_detector_mode_fails_without_rendering(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(b, 'STATE', Path(temp)), patch.object(b, 'run') as run:
            (b.STATE / 'settings.json').write_text(json.dumps({'detector_enabled': 'true'}))
            with self.assertRaisesRegex(RuntimeError, 'detector_enabled must be a boolean'):
                b.render('192.0.2.10', str(b.STATE / 'data'), '172.17.0.1')
            run.assert_not_called()

    def test_worker_startup_after_models_and_admission_boundary(self):
        names = ['broker', 'spark-perception', 'spark-llm', 'rtvi-embed', 'rtvi-vlm',
                 'vss-agent', 'vss-ui', 'vss-haproxy-ingress', 'lvs-server', 'alert-bridge', 'vss-va-mcp']
        for detector_available, allowed in [(29.999, False), (30, True)]:
            with self.subTest(detector_available=detector_available), tempfile.TemporaryDirectory() as temp, \
                 patch.object(b, 'STATE', Path(temp)), patch.object(b, 'doctor'), patch.object(b, 'provision'), \
                 patch.object(b, 'await_service'), patch.object(b, 'reclaim_model_file_cache') as reclaim, \
                 patch.object(b, 'verify') as verify, patch.object(b, 'memory_reserve', return_value=24):
                (b.STATE / 'compose.json').write_text(json.dumps({'services': {name: {} for name in names}}))
                started = []

                def fake_run(args, **kwargs):
                    if 'up' in args:
                        started.append(args[-1])
                    return subprocess.CompletedProcess(args, 0)

                def available():
                    return detector_available if 'rtvi-vlm' in started else 100

                with patch.object(b, 'run', side_effect=fake_run), patch.object(b, 'available', side_effect=available):
                    if allowed:
                        b.up()
                        self.assertLess(started.index('rtvi-vlm'), started.index('spark-perception'))
                        self.assertLess(started.index('spark-perception'), started.index('vss-agent'))
                        verify.assert_called_once()
                    else:
                        with self.assertRaisesRegex(RuntimeError, 'Admission refused before spark-perception'):
                            b.up()
                        self.assertNotIn('spark-perception', started)
                        self.assertNotIn('vss-agent', started)
                        verify.assert_not_called()
                    self.assertEqual([c.args[0] for c in reclaim.call_args_list], ['spark-llm', 'rtvi-embed', 'rtvi-vlm'])

    def test_detector_cli_is_explicit_and_render_only(self):
        with patch.object(sys, 'argv', ['bootstrap.py', 'render', '--host-ip', '192.0.2.10', '--detector']), \
             patch.object(b, 'render') as render:
            b.main()
            self.assertIs(render.call_args.args[-1], True)
        with patch.object(sys, 'argv', ['bootstrap.py', 'render', '--host-ip', '192.0.2.10', '--no-detector']), \
             patch.object(b, 'render') as render:
            b.main()
            self.assertIs(render.call_args.args[-1], False)
        with patch.object(sys, 'argv', ['bootstrap.py', 'up', '--detector']), patch.object(b, 'up') as up, \
             contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                b.main()
            up.assert_not_called()


if __name__ == '__main__':
    unittest.main()
