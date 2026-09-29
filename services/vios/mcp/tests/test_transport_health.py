"""Run in the VIOS MCP runtime: python < tests/test_transport_health.py."""
import logging
import unittest

from starlette.testclient import TestClient
from src.server import mcp


class TransportHealthTest(unittest.TestCase):
    def test_repeated_liveness_probes_do_not_retain_mcp_sessions(self):
        logging.disable(logging.CRITICAL)
        try:
            with TestClient(mcp.streamable_http_app()) as client:
                for _ in range(100):
                    response = client.get('/health')
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json(), {'status': 'healthy'})
                self.assertEqual(len(mcp.session_manager._server_instances), 0)
        finally:
            logging.disable(logging.NOTSET)


if __name__ == '__main__':
    unittest.main()
