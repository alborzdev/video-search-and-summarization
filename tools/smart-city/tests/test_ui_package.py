# SPDX-License-Identifier: Apache-2.0
"""CPU-only controls; no actual Docker command, service or build is invoked."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location("city_ui_package_tested", Path(__file__).parents[1] / "ui_package.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class UiPackagingControls(unittest.TestCase):
    def installed_fixture(self, source):
        packages = {
            '': {'name': 'test-workspace', 'version': '1.0.0'},
            'packages/widget': {'version': '1.0.0'},
            'node_modules/widget': {'resolved': 'packages/widget', 'link': True},
            'node_modules/react': {'version': '18.3.1', 'resolved': 'https://registry.npmjs.org/react/-/react-18.3.1.tgz', 'integrity': 'sha512-recorded-metadata'},
            'packages/widget/node_modules/helper': {'version': '2.0.0', 'resolved': 'https://registry.npmjs.org/helper/-/helper-2.0.0.tgz', 'integrity': 'sha512-other-recorded-metadata'},
            'node_modules/foreign-optional': {'version': '1.0.0', 'optional': True, 'os': ['darwin']},
        }
        source.mkdir()
        (source / 'package-lock.json').write_text(json.dumps({'lockfileVersion': 3, 'packages': packages}))
        for relative in ['packages/widget', 'node_modules/react', 'packages/widget/node_modules/helper']:
            directory = source / relative; directory.mkdir(parents=True)
            (directory / 'package.json').write_text(json.dumps({'name': Path(relative).name, 'version': packages[relative]['version']}))
            (directory / 'index.js').write_text('module.exports = {};')
        (source / 'node_modules/widget').symlink_to('../packages/widget')
        (source / 'node_modules/.bin').mkdir()
        (source / 'node_modules/.bin/react').symlink_to('../react/index.js')
        installed = {key: value for key, value in packages.items() if key and not value.get('optional')}
        (source / 'node_modules/.package-lock.json').write_text(json.dumps({'lockfileVersion': 3, 'packages': installed}))

    def test_source_snapshot_excludes_environment_credentials_and_generated_state(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); source = root / "source"; source.mkdir()
            for name in ["package.json", "package-lock.json", ".env", ".env.local", ".npmrc", "__ENV.js", "compile.log"]:
                (source / name).write_text('{}' if name.endswith('.json') else 'private-test-value')
            for name in ["node_modules", ".next", ".turbo", "lib", "lib-src"]:
                (source / name).mkdir(); (source / name / "file").write_text(name)
            output = root / "snapshot"; module.source_copy(source, output)
            self.assertEqual({p.name for p in output.iterdir()}, {"package.json", "package-lock.json", "lib-src"})
            first = module.tree_digest(output); (output / "lib-src/file").write_text("changed")
            self.assertNotEqual(first, module.tree_digest(output))

    def test_source_symlink_is_rejected_instead_of_following_private_data(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); source = root / "source"; source.mkdir()
            private = root / "private"; private.write_text("secret-test-only")
            (source / "public.js").symlink_to(private)
            with self.assertRaisesRegex(RuntimeError, "symlink"):
                module.source_copy(source, root / "copy")

    def test_artifact_hash_accepts_only_internal_traced_links(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); context = root / "context"; context.mkdir()
            (context / "target").write_text("traced")
            (context / "link").symlink_to("target")
            module.tree_digest(context, internal_links=True)
            (context / "link").unlink(); (context / "link").symlink_to("../outside")
            with self.assertRaises(RuntimeError): module.tree_digest(context, internal_links=True)

    def test_builder_commands_are_cpu_only_bounded_sequential_and_offline_for_compile(self):
        manifest = {"builderImageId": "sha256:" + "a" * 64, "registry": "https://registry.npmjs.org"}
        for stage in ("dependencies", "compile"):
            command = module.container_command(Path('/private/package'), manifest, stage, Path('/private/cache'))
            for flag, value in [("--runtime", "runc"), ("--memory", "4g"), ("--memory-swap", "4g"), ("--cpus", "2")]:
                self.assertEqual(command[command.index(flag) + 1], value)
            self.assertNotIn('--gpus', command); self.assertIn('NVIDIA_VISIBLE_DEVICES=void', command)
            self.assertIn('CIRCLE_NODE_TOTAL=2', command); self.assertIn(manifest['builderImageId'], command)
            self.assertNotIn('HISTORY_METADATA_TOKEN', ' '.join(command))
            if stage == 'compile':
                self.assertEqual(command[command.index('--network') + 1], 'none')
                self.assertIn('--concurrency=1 --env-mode=loose', command[-1])
                self.assertIn('--filter=nv-metropolis-bp-vss-ui...', command[-1])
            else:
                self.assertEqual(command[command.index('--network') + 1], 'host')
                self.assertIn('npm ci --include=dev --prefer-offline', command[-1])

    def test_overlay_inherits_private_environment_and_data_without_copying_secrets(self):
        override = module.production_override('vss-spark-vss-ui:test')
        service = override['services']['vss-ui']; rendered = json.dumps(override)
        self.assertEqual(set(override['services']), {'vss-ui'})
        self.assertNotIn('volumes', service); self.assertNotIn('/workspace', rendered)
        self.assertNotIn('HISTORY_METADATA_TOKEN', rendered)
        self.assertEqual(service['command'], ['node', 'custom-server.js'])
        self.assertEqual(service['environment']['NODE_ENV'], 'production')
        self.assertEqual(service['environment']['VSS_CITY_ANALYTICS_URL'], 'http://127.0.0.1:9184')
        self.assertEqual(service['mem_limit'], service['memswap_limit'])

    def test_saved_floor_has_no_additional_startup_allowance(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); (root / '.spark').mkdir()
            (root / '.spark/settings.json').write_text('{"reserve_gib":20}')
            (root / '.spark/guard-status.json').write_text('{}')
            with patch.object(module, 'run') as run, patch.object(module, 'available_gib', return_value=19.99):
                with self.assertRaisesRegex(RuntimeError, 'saved 20'): module.require_guard(root)
                run.assert_called_once()
            with patch.object(module, 'run'), patch.object(module, 'available_gib', return_value=20):
                self.assertEqual(module.require_guard(root), 20)
            (root / '.spark/settings.json').write_text('{"reserve_gib":0}')
            self.assertEqual(module.saved_floor(root), 0)
            with patch.object(module, 'run'), patch.object(module, 'available_gib', return_value=0.5):
                self.assertEqual(module.require_guard(root), 0)
            (root / '.spark/settings.json').write_text('{"reserve_gib":-1}')
            with self.assertRaisesRegex(RuntimeError, 'nonnegative'): module.saved_floor(root)

    def test_registry_credentials_and_external_package_paths_are_rejected(self):
        for value in ['http://registry.test', 'https://user:secret@registry.test', 'https://registry.test?token=secret']:
            with self.assertRaises(ValueError): module.registry_url(value)
        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaises(ValueError): module.package_directory(Path(raw), Path('/tmp/outside'))

    def test_changed_snapshot_cannot_start_any_docker_build(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); output = root / '.spark/smart-city-ui/test'; (output / 'workspace').mkdir(parents=True)
            (output / 'workspace/package.json').write_text('{}')
            (output / 'manifest.json').write_text(json.dumps({'status': 'prepared', 'sourceSha256': 'wrong'}))
            with patch.object(module, 'run') as run:
                with self.assertRaisesRegex(RuntimeError, 'inputs changed'): module.build(root, output)
                run.assert_not_called()

    def test_total_deadline_is_twenty_minutes(self):
        self.assertEqual(module.MAX_SECONDS, 1200)
        self.assertEqual(module.MEMORY_GIB, 4)

    def test_expired_deadline_never_launches_a_compiler(self):
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(module, 'require_guard'), patch.object(module.time, 'monotonic', return_value=100), patch.object(module.subprocess, 'Popen') as start:
                with self.assertRaisesRegex(RuntimeError, '20-minute'):
                    module.bounded_run(['docker', 'run'], Path(raw) / 'compile.log', Path(raw), 100)
                start.assert_not_called()

    def test_deadline_terminates_client_and_removes_named_compiler(self):
        process = Mock(); process.poll.return_value = None
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(module, 'require_guard'), patch.object(module.time, 'monotonic', side_effect=[0, 101]), patch.object(module.subprocess, 'Popen', return_value=process), patch.object(module.subprocess, 'run') as cleanup:
                with self.assertRaisesRegex(RuntimeError, '20-minute'):
                    module.bounded_run(['docker', 'run'], Path(raw) / 'compile.log', Path(raw), 100, 'city-ui-compile-test')
                process.terminate.assert_called_once(); process.wait.assert_called_once_with(timeout=5)
                self.assertEqual(cleanup.call_args.args[0], ['docker', 'rm', '--force', 'city-ui-compile-test'])

    def test_offline_reuse_copies_root_and_workspace_dependencies_and_preserves_internal_links(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); source = root / 'source'; self.installed_fixture(source)
            workspace = root / 'snapshot'; module.source_copy(source, workspace)
            source_hash = module.tree_digest(workspace, exclude_dependencies=True)
            receipt = module.reuse_installed_dependencies(source, workspace)
            self.assertEqual(receipt['installedPackageCount'], 4); self.assertEqual(receipt['absentOptionalPackageCount'], 1)
            self.assertEqual(receipt['dependencyRoots'], ['node_modules', 'packages/widget/node_modules'])
            self.assertEqual(len(receipt['dependencyTreeSha256']), 64); self.assertEqual(len(receipt['installedManifestsSha256']), 64)
            self.assertIn('not recomputed', receipt['provenance'])
            self.assertTrue((workspace / 'node_modules/widget').is_symlink())
            self.assertEqual((workspace / 'node_modules/widget').resolve(), workspace / 'packages/widget')
            self.assertEqual(os.readlink(workspace / 'node_modules/.bin/react'), '../react/index.js')
            self.assertEqual(source_hash, module.tree_digest(workspace, exclude_dependencies=True))
            (workspace / 'node_modules/react/index.js').write_text('changed unpacked bytes')
            self.assertNotEqual(receipt['dependencyTreeSha256'], module.dependencies_digest(workspace, receipt['dependencyRoots']))

    def test_offline_reuse_rejects_installed_lock_metadata_mismatch_and_actual_version_drift(self):
        with tempfile.TemporaryDirectory() as raw:
            source = Path(raw) / 'source'; self.installed_fixture(source)
            hidden = source / 'node_modules/.package-lock.json'; original = hidden.read_text()
            for field in ['version', 'resolved', 'integrity']:
                with self.subTest(field=field):
                    changed = json.loads(original); changed['packages']['node_modules/react'][field] = 'mismatch'
                    hidden.write_text(json.dumps(changed))
                    with self.assertRaisesRegex(RuntimeError, 'differs'): module.validate_installed_dependencies(source)
            hidden.write_text(original)
            (source / 'node_modules/react/package.json').write_text('{"version":"wrong"}')
            with self.assertRaisesRegex(RuntimeError, 'version differs'): module.validate_installed_dependencies(source)

    def test_offline_reuse_rejects_missing_required_lock_entry_or_manifest(self):
        with tempfile.TemporaryDirectory() as raw:
            source = Path(raw) / 'source'; self.installed_fixture(source)
            hidden = source / 'node_modules/.package-lock.json'; original = hidden.read_text(); changed = json.loads(original)
            del changed['packages']['node_modules/react']; hidden.write_text(json.dumps(changed))
            with self.assertRaisesRegex(RuntimeError, 'Required installed lock entry is absent'): module.validate_installed_dependencies(source)
            hidden.write_text(original); (source / 'node_modules/react/package.json').unlink()
            with self.assertRaisesRegex(RuntimeError, 'manifest is absent'): module.validate_installed_dependencies(source)

    def test_offline_reuse_rejects_external_absolute_and_broken_dependency_links(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); source = root / 'source'; self.installed_fixture(source)
            outside = root / 'outside'; outside.write_text('test private bytes')
            link = source / 'node_modules/react/unsafe'
            for target in ['../../../outside', str(source / 'node_modules/react/index.js'), 'missing-file']:
                with self.subTest(target=target):
                    link.symlink_to(target)
                    with self.assertRaisesRegex(RuntimeError, 'dependency symlink'): module.validate_installed_dependencies(source)
                    link.unlink()

    def test_offline_build_starts_only_the_bounded_offline_compile_stage(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); source = root / 'source'; self.installed_fixture(source)
            package = root / '.spark/smart-city-ui/test'; package.mkdir(parents=True)
            workspace = package / 'workspace'; module.source_copy(source, workspace)
            receipt = module.reuse_installed_dependencies(source, workspace)
            (package / 'context').mkdir(); dockerfile = package / 'context/Dockerfile'; dockerfile.write_text('FROM cached')
            manifest = {'status': 'prepared', 'sourceSha256': module.tree_digest(workspace, exclude_dependencies=True),
                        'dockerfileSha256': module.sha256(dockerfile), 'fallbackReference': 'fallback', 'baseImageId': 'sha256:test',
                        'builderImageId': 'sha256:test', 'registry': 'https://registry.npmjs.org',
                        'dependencyMode': 'reuse-installed', 'reusedDependencies': receipt}
            (package / 'manifest.json').write_text(json.dumps(manifest))
            with patch.object(module, 'inspect_image', return_value={'id': 'sha256:test'}), patch.object(module, 'require_guard'), patch.object(module, 'bounded_run', side_effect=RuntimeError('test stops before any compile')) as bounded:
                with self.assertRaisesRegex(RuntimeError, 'test stops'): module.build(root, package)
                self.assertEqual(bounded.call_count, 1)
                command = bounded.call_args.args[0]
                self.assertIn('city-ui-compile-test', command); self.assertNotIn('npm ci', command[-1])
                self.assertEqual(command[command.index('--network') + 1], 'none')


if __name__ == '__main__':
    unittest.main()
