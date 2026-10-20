import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import bootstrap
from platforms import identify


class DispatchTests(unittest.TestCase):
    def test_supported_hardware(self):
        self.assertEqual(identify('NVIDIA GB10, 580.142', 'aarch64'), 'spark')
        self.assertEqual(identify('NVIDIA Thor, 580.00', 'aarch64'), 'thor')

    def test_unsupported_and_ambiguous_hardware(self):
        for gpu, arch in [('NVIDIA GB10', 'x86_64'), ('NVIDIA H100', 'aarch64'),
                          ('NVIDIA GB10\nNVIDIA Thor', 'aarch64'), ('', 'aarch64')]:
            with self.subTest(gpu=gpu, arch=arch):
                self.assertEqual(identify(gpu, arch), 'unsupported')

    def test_all_entrypoints_select_the_actual_device_and_forward_arguments(self):
        for device in ('spark', 'thor'):
            for tool in ('bootstrap', 'desktop', 'ui'):
                hardware = {'platform': device, 'gpu': 'test GPU', 'architecture': 'aarch64'}
                args = ['render', '--data-dir', '/path with spaces', '--reserve-gib', '24']
                with self.subTest(device=device, tool=tool), \
                     patch.object(bootstrap, 'inventory', return_value=hardware), \
                     patch.object(bootstrap.os, 'execv') as execute, \
                     contextlib.redirect_stdout(io.StringIO()):
                    bootstrap.dispatch(tool, args)
                    helper = Path(bootstrap.__file__).resolve().parents[1] / device / f'{tool}.py'
                    execute.assert_called_once_with(sys.executable,
                        [sys.executable, str(helper), *args])

    def test_unsupported_host_never_launches_a_runtime(self):
        hardware = {'platform': 'unsupported', 'gpu': 'NVIDIA H100', 'architecture': 'aarch64'}
        with patch.object(bootstrap, 'inventory', return_value=hardware), \
             patch.object(bootstrap.os, 'execv') as execute:
            with self.assertRaisesRegex(RuntimeError, 'No deployment profile'):
                bootstrap.dispatch()
            execute.assert_not_called()

    def test_unknown_tool_is_rejected_before_hardware_access(self):
        with patch.object(bootstrap, 'inventory') as inventory:
            with self.assertRaisesRegex(RuntimeError, 'Unknown runtime tool'):
                bootstrap.dispatch('../other')
            inventory.assert_not_called()


if __name__ == '__main__':
    unittest.main()
