"""Cold UI readiness must allow compilation while retaining backend timeouts."""
import contextlib
import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

spec = importlib.util.spec_from_file_location('thor_manage', Path(__file__).with_name('manage.py'))
manage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manage)


class ReadinessTests(unittest.TestCase):
    def test_cold_ui_gets_compilation_budget_and_other_apis_keep_five_seconds(self):
        seen = {}

        def open_url(url, timeout):
            seen[url] = timeout
            if url == 'http://ui.test/' and timeout < 8.55:
                raise TimeoutError('cold page compilation exceeds probe deadline')
            response = MagicMock()
            response.__enter__.return_value.status = 200
            return response

        with patch.object(manage.subprocess, 'check_output', return_value=b'[]'), \
             patch.object(manage, 'elasticsearch_ready', return_value=True), \
             patch.object(manage, 'public_ui_url', return_value='http://ui.test/'), \
             patch.object(manage, 'available', return_value=54), \
             patch.object(manage.urllib.request, 'urlopen', side_effect=open_url), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(manage.status())
        self.assertEqual(seen.pop('http://ui.test/'), 15)
        self.assertTrue(seen)
        self.assertEqual(set(seen.values()), {5})

    def test_longer_budget_does_not_hide_failed_ui(self):
        with patch.object(manage.urllib.request, 'urlopen', side_effect=TimeoutError):
            self.assertFalse(manage.healthy('http://ui.test/', timeout=15))
        response = MagicMock()
        response.__enter__.return_value.status = 503
        with patch.object(manage.urllib.request, 'urlopen', return_value=response):
            self.assertFalse(manage.healthy('http://ui.test/', timeout=15))


if __name__ == '__main__':
    unittest.main()
