import hashlib
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('restore_codecs', Path(__file__).with_name('restore_codecs.py'))
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


class RestoreCodecTests(unittest.TestCase):
    def test_missing_live_archive_uses_snapshot_without_changing_the_pin(self):
        data = b'locked archive bytes'
        package = {'url': 'https://ports.ubuntu.com/ubuntu-ports/pool/main/a/archive/archive_arm64.deb',
                   'filename': 'archive_arm64.deb', 'size': len(data),
                   'sha256': hashlib.sha256(data).hexdigest()}
        for valid in (True, False):
            with self.subTest(valid=valid), tempfile.TemporaryDirectory() as folder:
                destination = Path(folder) / package['filename']
                def download(command, **kwargs):
                    if command[-1] == package['url']:
                        raise subprocess.CalledProcessError(22, ['curl'])
                    self.assertEqual(command[-1], 'https://snapshot.ubuntu.com/ubuntu/20261007T000000Z/'
                                     'pool/main/a/archive/archive_arm64.deb')
                    destination.write_bytes(data if valid else b'changed archive')
                with patch.object(r.subprocess, 'run', side_effect=download) as fetch:
                    if valid:
                        r.download_archive(package, destination)
                        self.assertEqual(destination.read_bytes(), data)
                    else:
                        with self.assertRaisesRegex(RuntimeError, 'checksum mismatch'):
                            r.download_archive(package, destination)
                    self.assertEqual(fetch.call_count, 2)


if __name__ == '__main__':
    unittest.main()
