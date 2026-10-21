import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools.runtime import legacy_rtvi as legacy


class LegacySourceTests(unittest.TestCase):
    def test_staged_rebuild_preserves_exact_custom_source_and_verifies_offline(self):
        with tempfile.TemporaryDirectory() as temporary:
            context = Path(temporary) / 'legacy-source'
            manifest = legacy.stage(context=context)
            self.assertEqual(len(manifest['files']), 54)
            self.assertEqual(sum(item['size'] for item in manifest['files']), 1120328)
            path = 'server/rtvi_stream_handler.py'
            self.assertEqual((context / 'src' / path).read_bytes(),
                             legacy.read_frozen_blob(legacy.ROOT, legacy.SOURCE_PREFIX + path))
            self.assertNotEqual((context / 'src' / path).read_bytes(),
                                (legacy.ROOT / legacy.SOURCE_PREFIX / path).read_bytes())
            with patch.object(legacy, 'git_read', side_effect=AssertionError('offline verifier cannot call Git')):
                self.assertEqual(legacy.verify(context), manifest)
                self.assertEqual(legacy.stage(context=context), manifest)
            subprocess.run(['python3', str(Path(legacy.__file__)), 'verify', '--context', str(context)],
                           check=True, capture_output=True)
            # Match the packaged helper's path shape and also allow a shallow
            # relocation: verification must not depend on checkout discovery.
            for target in (Path(temporary) / 'usr/local/libexec/vss-thor/legacy_rtvi.py',
                           Path(temporary) / 'verify.py'):
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(Path(legacy.__file__).read_bytes())
                subprocess.run(['python3', str(target), 'verify', '--context', str(context)],
                               check=True, capture_output=True)

    def test_changed_bytes_extra_files_forged_manifest_and_links_are_rejected(self):
        for mutation in ('bytes', 'extra', 'manifest', 'symlink'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                context = Path(temporary) / 'legacy-source'
                legacy.stage(context=context)
                manifest_path = context / 'manifest.json'
                manifest = json.loads(manifest_path.read_text())
                target = context / manifest['files'][0]['path']
                if mutation == 'extra':
                    (context / 'credential.txt').write_text('unrelated build input')
                elif mutation == 'symlink':
                    target.unlink()
                    target.symlink_to('/etc/hosts')
                else:
                    target.write_bytes(b'current source must not substitute')
                    if mutation == 'manifest':
                        manifest['files'][0].update(size=target.stat().st_size,
                            sha256=hashlib.sha256(target.read_bytes()).hexdigest())
                        manifest_path.write_text(json.dumps(manifest))
                with self.assertRaises(RuntimeError):
                    legacy.verify(context)
                # Existing invalid preparation is preserved, never overwritten.
                with self.assertRaises(RuntimeError):
                    legacy.stage(context=context)

    def test_rejects_parent_links_and_unapproved_git_paths_before_reading(self):
        with patch.object(legacy, 'git_read') as git:
            for path in ('../.spark/settings.json', '/etc/hosts', 'services/agent/server.py',
                         legacy.SOURCE_PREFIX + '../secrets'):
                with self.subTest(path=path), self.assertRaises(RuntimeError):
                    legacy.read_frozen_blob(legacy.ROOT, path)
            git.assert_not_called()
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            (parent / 'redirect').symlink_to(parent, target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError, 'symlink'):
                legacy.stage(context=parent / 'redirect' / 'source')

    def test_missing_history_fails_without_current_source_fallback(self):
        with patch.object(legacy.subprocess, 'check_output',
                          side_effect=subprocess.CalledProcessError(128, ['git'])):
            with self.assertRaisesRegex(RuntimeError, 'Current 3.3 source cannot substitute'):
                legacy.read_frozen_blob(legacy.ROOT, legacy.CODEC_INSTALLER)

    def test_original_codec_source_retains_trusted_hash(self):
        frozen = legacy.read_frozen_blob(legacy.ROOT, legacy.CODEC_INSTALLER)
        self.assertEqual(hashlib.sha256(frozen).hexdigest(),
                         '20f1c024c11405ed88192ed9e26a2841348249b8c4238bccd5cce355f7051238')

    def test_legacy_dockerfile_only_copies_verified_staged_source(self):
        path = legacy.ROOT / 'deploy/docker/thor-local/audio/Dockerfile.rtvi-vlm-codecs'
        dockerfile = path.read_text()
        self.assertIn('COPY deploy/docker/thor-local/audio/legacy-rtvi-src/', dockerfile)
        self.assertNotIn('COPY services/rtvi/', dockerfile)
        self.assertLess(dockerfile.index('legacy_rtvi.py verify --context'),
                        dockerfile.index('cp -a /tmp/legacy-rtvi-src/src/.'))
        ignores = path.with_suffix(path.suffix + '.dockerignore').read_text().splitlines()
        self.assertIn('**', ignores)
        self.assertIn('!deploy/docker/thor-local/audio/legacy-rtvi-src/**', ignores)
        self.assertIn('!tools/runtime/legacy_rtvi.py', ignores)
        self.assertFalse(any(line.startswith('!services') for line in ignores))


if __name__ == '__main__':
    unittest.main()
