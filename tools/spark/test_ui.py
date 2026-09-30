import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('spark_ui', Path(__file__).with_name('ui.py'))
ui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui)


class SparkUiTests(unittest.TestCase):
    def workspace(self, root):
        source = root / 'ui'
        source.mkdir()
        (source / 'package.json').write_text(json.dumps({'workspaces': ['apps/*']}))
        (source / 'package-lock.json').write_text('{}')
        app = source / 'apps' / ui.APP
        app.mkdir(parents=True)
        (app / 'package.json').write_text('{}')
        state = root / 'state'
        state.mkdir()
        return source, state, app

    def test_actual_compose_merge_preserves_saved_data_backend_and_other_services(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, state, _ = self.workspace(root)
            reports = root / 'reports'
            reports.mkdir()
            original = {'services': {
                'vss-ui': {'image': 'vss-spark-vss-ui:source', 'network_mode': 'host',
                           'environment': {'PORT': '3001', 'BACKEND_URL': 'http://127.0.0.1:8100',
                                           'PRIVATE_TEST_VALUE': 'do-not-print'},
                           'volumes': [{'type': 'bind', 'source': str(reports), 'target': '/data/reports'}]},
                'model': {'image': 'model:test', 'command': ['unchanged'], 'mem_limit': '1g'},
            }}
            base = state / 'compose.json'
            base.write_text(json.dumps(original))
            before = base.read_bytes()
            with patch.object(ui, 'UI', source), patch.object(ui, 'STATE', state), patch.object(ui.os, 'getgid', return_value=1000):
                override = state / 'dev.json'
                ui.bootstrap.private_write(override, json.dumps(ui.dev_override(original['services']['vss-ui'])))
                result = subprocess.run(ui.compose(override) + ['config', '--format', 'json'],
                                        capture_output=True, text=True, check=True)
            graph = json.loads(result.stdout)
            service = graph['services']['vss-ui']
            self.assertEqual(base.read_bytes(), before)
            self.assertEqual(override.stat().st_mode & 0o777, 0o600)
            self.assertEqual(service['environment']['BACKEND_URL'], 'http://127.0.0.1:8100')
            self.assertEqual(service['environment']['PRIVATE_TEST_VALUE'], 'do-not-print')
            self.assertEqual(service['user'], '65532:1000')
            self.assertEqual(service['runtime'], 'runc')
            self.assertEqual(int(service['mem_limit']), 4 * 1024**3)
            self.assertEqual(int(service['memswap_limit']), int(service['mem_limit']))
            self.assertEqual(service['network_mode'], 'host')
            self.assertTrue(any(m['target'] == '/data/reports' and m['source'] == str(reports)
                                for m in service['volumes']))
            self.assertEqual(graph['services']['model']['command'], ['unchanged'])
            self.assertEqual(int(graph['services']['model']['mem_limit']), 1024**3)

    def test_dependency_changes_require_reinstall_and_default_ignores_bundled_traces(self):
        with tempfile.TemporaryDirectory() as temp:
            source, state, app = self.workspace(Path(temp))
            with patch.object(ui, 'UI', source), patch.object(ui, 'STATE', state):
                with self.assertRaisesRegex(RuntimeError, 'dependencies'):
                    ui.validate_dependencies()
                for name in ('next/dist/bin/next', '@next/swc-linux-arm64-gnu/next-swc.linux-arm64-gnu.node'):
                    required = source / 'node_modules' / name
                    required.parent.mkdir(parents=True, exist_ok=True)
                    required.write_bytes(b'installed')
                (state / 'ui-deps.json').write_text(json.dumps({'fingerprint': ui.dependency_fingerprint()}))
                ui.validate_dependencies()
                (app / 'package.json').write_text('{"new_dependency":"changed"}')
                with self.assertRaisesRegex(RuntimeError, 'stale'):
                    ui.validate_dependencies()

    def test_dev_admission_preserves_saved_reserve(self):
        with patch.object(ui.bootstrap, 'doctor') as doctor, patch.object(ui, 'run') as run, \
                patch.object(ui.bootstrap, 'memory_reserve', return_value=24), \
                patch.object(ui.bootstrap, 'available', return_value=27.9):
            with self.assertRaisesRegex(RuntimeError, '28 GiB'):
                ui.preflight(True)
            doctor.assert_called_once()
            run.assert_called_once_with(['systemctl', '--user', 'is-active', '--quiet', 'vss-spark-guard.service'])

    def test_install_reuses_ui_image_and_preserves_lockfile_without_stopping_workloads(self):
        with tempfile.TemporaryDirectory() as temp:
            source, state, _ = self.workspace(Path(temp))
            lock_before = (source / 'package-lock.json').read_bytes()
            with patch.object(ui, 'UI', source), patch.object(ui, 'STATE', state), \
                    patch.object(ui, 'current_mode', return_value='built'), patch.object(ui, 'run') as run, \
                    patch.object(ui, 'validate_dependencies'):
                ui.install_dependencies({'npm_registry': 'https://registry.npmjs.org'}, {'image': 'vss-spark-vss-ui:source'})
            command = run.call_args.args[0]
            self.assertIn('vss-spark-vss-ui:source', command)
            self.assertIn('--include=dev', command)
            self.assertIn('--prefer-offline', command)
            self.assertIn('NODE_ENV=development', command)
            self.assertEqual(command[command.index('--runtime') + 1], 'runc')
            self.assertNotIn('stop', command)
            self.assertNotIn('build', command)
            self.assertEqual((source / 'package-lock.json').read_bytes(), lock_before)

    def test_dev_failure_rolls_back_only_ui_and_built_uses_base_graph(self):
        with tempfile.TemporaryDirectory() as temp:
            source, state, _ = self.workspace(Path(temp))
            calls = []

            def run(command, **kwargs):
                calls.append(command)
                if 'up' in command and 'compose-ui-dev.json' in ' '.join(command):
                    raise subprocess.CalledProcessError(1, command)

            with patch.object(ui, 'UI', source), patch.object(ui, 'STATE', state), \
                    patch.object(ui, 'run', side_effect=run), patch.object(ui, 'validate_dependencies'), \
                    patch.object(ui, 'prepare_cache'):
                with self.assertRaises(subprocess.CalledProcessError):
                    ui.switch('dev', {'environment': {'PORT': '3001'}})
                up = [command for command in calls if 'up' in command]
                self.assertEqual(len(up), 2)
                self.assertTrue(all(command[-1] == 'vss-ui' and '--no-deps' in command for command in up))
                self.assertNotIn('compose-ui-dev.json', ' '.join(up[-1]))
                calls.clear()
                ui.switch('built', {})
                self.assertTrue(all('compose-ui-dev.json' not in ' '.join(command) for command in calls))

    def test_reinstall_refuses_active_dev_and_secrets_are_not_inherited(self):
        with patch.object(ui, 'current_mode', return_value='dev'), patch.object(ui, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'built mode'):
                ui.install_dependencies({}, {})
            run.assert_not_called()
        with patch.dict(os.environ, {'NGC_API_KEY': 'secret', 'NPM_TOKEN': 'secret'}):
            self.assertNotIn('NGC_API_KEY', ui.clean_env())
            self.assertNotIn('NPM_TOKEN', ui.clean_env())


if __name__ == '__main__':
    unittest.main()
