# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'thor-local/vios-codecs/rtvi33_codec_closure.py'
SPEC = importlib.util.spec_from_file_location('rtvi33_codec_closure', SCRIPT)
closure = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(closure)


class CodecSupplementTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        package_root = self.root / 'package'
        (package_root / 'DEBIAN').mkdir(parents=True)
        (package_root / 'DEBIAN/control').write_text(
            'Package: libsodium23\nVersion: 1.0.18-1ubuntu0.24.04.1\n'
            'Architecture: arm64\nMaintainer: Test <test@example.invalid>\n'
            'Description: Archive integrity fixture\n')
        self.archive = self.root / 'libsodium23_1.0.18-1ubuntu0.24.04.1_arm64.deb'
        subprocess.run(['dpkg-deb', '--build', str(package_root), str(self.archive)],
                       check=True, capture_output=True, timeout=15)
        self.lock, self.package = closure.load_lock(closure.DEFAULT_LOCK)
        self.package['size'] = self.archive.stat().st_size
        self.package['sha256'] = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        self.lock_path = self.root / 'lock.json'
        self.write_lock()
        self.bundle = self.root / 'bundle'

    def write_lock(self):
        self.lock_path.write_text(json.dumps(self.lock, indent=2) + '\n')

    def stage_local(self):
        with patch.object(closure.urllib.request, 'urlopen', side_effect=AssertionError('Unexpected network')):
            closure.stage(self.bundle, self.lock_path, self.archive)

    def test_local_stage_verifies_debian_metadata_and_publishes_exact_manifest(self):
        self.stage_local()
        closure.verify_bundle(self.bundle, self.lock_path)
        self.assertEqual((self.bundle / 'manifest.json').read_bytes(), self.lock_path.read_bytes())
        self.assertFalse(self.bundle.with_name('bundle.partial').exists())

    def test_same_size_corrupt_archive_never_publishes_bundle(self):
        data = bytearray(self.archive.read_bytes())
        data[-1] ^= 1
        self.archive.write_bytes(data)
        with self.assertRaisesRegex(ValueError, 'checksum'):
            self.stage_local()
        self.assertFalse(self.bundle.exists())
        self.assertFalse(self.bundle.with_name('bundle.partial').exists())

    def test_wrong_debian_identity_is_rejected_even_with_valid_archive_hash(self):
        self.package['version'] = 'unexpected-version'
        self.write_lock()
        with self.assertRaisesRegex(ValueError, 'Debian Version'):
            self.stage_local()
        self.assertFalse(self.bundle.exists())

    def test_symlink_archive_is_rejected(self):
        link = self.root / 'archive-link.deb'
        link.symlink_to(self.archive)
        with self.assertRaisesRegex(ValueError, 'regular file'):
            closure.verify_archive(link, self.package)

    def test_unlisted_archive_is_rejected_without_touching_existing_data(self):
        self.stage_local()
        extra = self.bundle / 'unreviewed.deb'
        extra.write_bytes(b'unreviewed')
        with self.assertRaisesRegex(ValueError, 'Unexpected supplement bundle contents'):
            closure.verify_bundle(self.bundle, self.lock_path)
        self.assertEqual(extra.read_bytes(), b'unreviewed')

    def test_manifest_changes_are_rejected(self):
        self.stage_local()
        (self.bundle / 'manifest.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'canonical lock'):
            closure.verify_bundle(self.bundle, self.lock_path)

    def test_install_refuses_host_invocation_before_package_extraction(self):
        with patch.object(closure.Path, 'is_file', return_value=False), \
             patch.dict(closure.os.environ, {'VSS_CODEC_IMAGE_BUILD': '0'}), \
             patch.object(closure.subprocess, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'container image build'):
                closure.install(self.bundle, self.lock_path)
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
