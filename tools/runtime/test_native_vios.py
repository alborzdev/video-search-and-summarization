"""Small fixtures execute the production resume verifier without Docker."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
import importlib.util
from unittest.mock import patch

_spec = importlib.util.spec_from_file_location("native_recipe", Path(__file__).with_name("build_vios_native.py"))
recipe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(recipe)


class ResumeVerifierTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.scratch = self.root / 'scratch'
        self.scratch.mkdir()
        (self.scratch / 'src').mkdir()
        (self.scratch / 'src/code.cpp').write_text('original source')
        self.manifest = dict(tree_sha256='fixture', files={'src/code.cpp': dict(sha256=hashlib.sha256(b'original source').hexdigest())})
        self.frozen = self.root / 'source-manifest.json'
        self.frozen.write_text(json.dumps(self.manifest))
        (self.scratch / 'source-manifest.json').write_text(json.dumps(self.manifest))
        recipe = (Path(__file__).resolve().parents[2] / 'deploy/docker/vios-native33/build-native.sh').read_text()
        self.code = re.findall("python3 - <<'PY'\n(.*?)\nPY", recipe, re.S)[1]
        self.code = self.code.replace("Path('/source/source-manifest.json')", f'Path({str(self.frozen)!r})')

    def verify(self):
        before = Path.cwd()
        try:
            os.chdir(self.scratch)
            with contextlib.redirect_stdout(io.StringIO()):
                exec(compile(self.code, 'production-resume-verifier', 'exec'), {})
        finally:
            os.chdir(before)

    def test_accepts_unchanged_source_and_allowed_generated_objects(self):
        (self.scratch / 'src/code.o').write_bytes(b'generated object')
        (self.scratch / 'src/code.d').write_text('dependency')
        self.verify()

    def test_rejects_altered_original_source(self):
        (self.scratch / 'src/code.cpp').write_text('changed source')
        with self.assertRaises(AssertionError):
            self.verify()

    def test_rejects_unexpected_new_source(self):
        (self.scratch / 'src/extra.cpp').write_text('unreviewed source')
        with self.assertRaises(AssertionError):
            self.verify()

    def test_rejects_modified_scratch_receipt(self):
        (self.scratch / 'source-manifest.json').write_text('{}')
        with self.assertRaises(AssertionError):
            self.verify()

    def test_rejects_generated_library_symlink_escaping_scratch(self):
        native = self.scratch / 'prebuilts/aarch64'
        native.mkdir(parents=True)
        (native / 'libbad.so').symlink_to(self.frozen)
        with self.assertRaises(AssertionError):
            self.verify()


class ResourceGuardTest(unittest.TestCase):
    def verify(self, memory='4294967296', cpu='200000 100000', gpu=False, drm=False):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'cgroup').mkdir()
            (root / 'cgroup/memory.max').write_text(memory)
            (root / 'cgroup/cpu.max').write_text(cpu)
            (root / 'dev').mkdir()
            if gpu:
                (root / 'dev/nvidiactl').touch()
            if drm:
                (root / 'dev/dri').mkdir()
            text = (recipe.RECIPES / 'build-native.sh').read_text()
            code = re.findall("python3 - <<'PY'\n(.*?)\nPY", text, re.S)[0]
            for original, replacement in [('/sys/fs/cgroup', root / 'cgroup'), ('/dev/dri', root / 'dev/dri'), ('/dev', root / 'dev'), ('/build/vios', root / 'scratch'), ('/out', root / 'out')]:
                code = code.replace(f"Path('{original}')", f'Path({str(replacement)!r})')
            with patch.dict(os.environ, {'VSS_NATIVE_RESUME': '0'}):
                exec(compile(code, 'production-resource-guard', 'exec'), {})

    def test_accepts_bounded_cpu_only_fixture(self):
        self.verify()

    def test_rejects_unlimited_or_excess_memory(self):
        for memory in ('max', '8589934592'):
            with self.assertRaisesRegex(AssertionError, 'memory limit'):
                self.verify(memory=memory)

    def test_rejects_unlimited_or_excess_cpu(self):
        for cpu in ('max 100000', '300000 100000'):
            with self.assertRaisesRegex(AssertionError, 'CPU quota'):
                self.verify(cpu=cpu)

    def test_rejects_any_nvidia_or_drm_device(self):
        for keyword in ('gpu', 'drm'):
            with self.assertRaisesRegex(AssertionError, 'devices'):
                self.verify(**{keyword: True})


class PackagingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.work = self.root / 'work'
        self.work.mkdir()
        self.addCleanup(patch.stopall)
        patch.object(recipe, 'REPO', self.root).start()

    def source(self):
        source = self.root / 'services/vios'
        for name in recipe.SOURCE_PATHS:
            path = source / name
            if name.startswith('Makefile'):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('fixture makefile')
            else:
                path.mkdir(parents=True, exist_ok=True)
        (source / 'src/code.cpp').write_text('source')
        return source

    def output(self):
        self.source()
        frozen = recipe.snapshot(self.work / 'freeze')
        source = Path(frozen['source'])
        output = self.work / 'output'
        output.mkdir()
        (output / 'prebuilts/aarch64').mkdir(parents=True)
        (output / 'launch_vst').write_bytes(b'\x7fELFexecutable')
        (output / 'prebuilts/aarch64/libexample.so.1').write_bytes(b'\x7fELFlibrary')
        (output / 'prebuilts/aarch64/libexample.so').symlink_to('libexample.so.1')
        (output / 'prebuilts/aarch64/libskip.a').write_bytes(b'static archive')
        (output / 'source-manifest.json').write_text((source / 'source-manifest.json').read_text())
        (output / 'builder-linker.txt').write_text('libc.so.6 => /lib/libc.so.6')
        checksums = {str(p.relative_to(output)): recipe.digest(p) for p in output.rglob('*') if p.is_file() and not p.is_symlink() and p.name not in ('source-manifest.json', 'builder-linker.txt')}
        recipe.write_json(output / 'output-checksums.json', checksums)
        return output, source

    def test_snapshot_excludes_private_and_generated_inputs(self):
        source = self.source()
        (source / '.private').write_text('excluded')
        (source / 'src/code.o').write_text('stale object')
        result = recipe.snapshot(self.work)
        target = Path(result['source'])
        self.assertFalse((target / '.private').exists())
        self.assertFalse((target / 'src/code.o').exists())
        self.assertEqual(recipe.manifest_files(target), recipe.manifest_files(source))

    def test_snapshot_rejects_symlink_escaping_public_source(self):
        source = self.source()
        (source / 'src/outside.cpp').symlink_to(self.root / 'private')
        with self.assertRaisesRegex(ValueError, 'escapes'):
            recipe.snapshot(self.work)

    def test_runtime_filters_static_archives_preserves_safe_symlink_and_public_pin(self):
        output, source = self.output()
        def stage(context, *unused):
            (context / '.dockerignore').write_text('*\n!Dockerfile\n')
            return {'locks': {'fixture': 'locked'}}
        with patch.object(recipe, 'stage_codecs', side_effect=stage):
            result = recipe.runtime(self.work, output, source, None, None, None)
        context = Path(result['context'])
        self.assertFalse((context / 'runtime/prebuilts/aarch64/libskip.a').exists())
        self.assertTrue((context / 'runtime/prebuilts/aarch64/libexample.so').is_symlink())
        self.assertIn('FROM ' + recipe.PUBLIC_BASE, (context / 'Dockerfile').read_text())
        self.assertNotIn('FROM sha256:', (context / 'Dockerfile').read_text())
        self.assertGreater(result['skipped_static_bytes'], 0)

    def test_altered_output_and_source_receipt_fail(self):
        output, source = self.output()
        (output / 'launch_vst').write_bytes(b'changed executable')
        with self.assertRaisesRegex(ValueError, 'native output'):
            recipe.verify_output(output, source)
        (output / 'source-manifest.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'receipt differs'):
            recipe.verify_output(output, source)

    def test_changed_frozen_source_fails(self):
        output, source = self.output()
        (source / 'src/code.cpp').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'snapshot has changed'):
            recipe.verify_output(output, source)

    def test_generation_refuses_external_or_existing_directory(self):
        with self.assertRaisesRegex(ValueError, 'ignored work'):
            recipe.new_directory(self.root / 'outside')
        with self.assertRaises(FileExistsError):
            recipe.new_directory(self.work)

    def test_locks_are_unique_official_and_builder_matches_pin(self):
        for kind, path in recipe.LOCK_PATHS.items():
            lock = recipe.VERIFY.load_lock(path)
            self.assertTrue(lock['packages'], kind)
        self.assertEqual(recipe.VERIFY.load_lock(recipe.LOCK_PATHS['dev'])['base_image'], recipe.BUILDER_BASE)


if __name__ == '__main__':
    unittest.main()
