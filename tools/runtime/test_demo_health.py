#!/usr/bin/env python3
"""The runtime preflight must catch red primaries before Docker's retry limit."""
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

path = Path(__file__).resolve().parents[2] / "artifacts/thor-memory-2026-09-09/manage.py"
spec = importlib.util.spec_from_file_location("thor_demo_manage", path)
manage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manage)


class ClusterReadinessTests(unittest.TestCase):
    def test_requires_all_primaries_while_accepting_single_node_yellow(self):
        for status, primaries, expected in [
            ("yellow", 0, True), ("green", 0, True),
            ("red", 1, False), ("red", 0, False), ("yellow", 1, False),
            ("yellow", None, False),
        ]:
            with self.subTest(status=status, primaries=primaries):
                response = io.StringIO(json.dumps({"status": status, "unassigned_primary_shards": primaries}))
                with patch.object(manage.urllib.request, "urlopen", return_value=response):
                    self.assertEqual(manage.elasticsearch_ready(), expected)

    def test_unreachable_cluster_is_not_ready(self):
        with patch.object(manage.urllib.request, "urlopen", side_effect=OSError("offline")):
            self.assertFalse(manage.elasticsearch_ready())

    def test_malformed_response_is_not_ready(self):
        with patch.object(manage.urllib.request, "urlopen", return_value=io.StringIO("not JSON")):
            self.assertFalse(manage.elasticsearch_ready())


if __name__ == "__main__":
    unittest.main()
