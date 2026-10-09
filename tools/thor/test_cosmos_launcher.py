import hashlib
import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('thor_cosmos_launcher',
                                            Path(__file__).with_name('cosmos_launcher.py'))
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class CosmosLauncherTest(unittest.TestCase):
    def test_unknown_vendor_bytes_are_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'vendor launcher changed'):
            launcher.without_private_mps(b'changed image launcher')

    def test_ambiguous_mps_function_is_rejected_even_with_matching_digest(self):
        script = launcher.FUNCTION * 2
        with patch.object(launcher, 'VENDOR_SHA256', hashlib.sha256(script).hexdigest()):
            with self.assertRaisesRegex(RuntimeError, 'ambiguous'):
                launcher.without_private_mps(script)

    def test_vendor_remaining_startup_runs_but_mps_command_does_not(self):
        script = (b'start_cuda_mps_server() {\n    echo unexpected-private-MPS\n}\n'
                  b'start_cuda_mps_server\necho "model-decoder-startup:$1"\n')
        with patch.object(launcher, 'VENDOR_SHA256', hashlib.sha256(script).hexdigest()):
            adapted = launcher.without_private_mps(script)
        result = subprocess.run(['bash', '-s', '--', 'forwarded-argument'],
                                input=adapted, capture_output=True, check=True)
        self.assertNotIn(b'unexpected-private-MPS', result.stdout)
        self.assertIn(b'model-decoder-startup:forwarded-argument', result.stdout)


if __name__ == '__main__':
    unittest.main()
