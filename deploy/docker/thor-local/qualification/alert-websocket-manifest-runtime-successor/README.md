# Alert WebSocket manifest runtime successor

This read-only package binds one isolated Thor Alert Bridge transaction to the
generic alert WebSocket protocol row and VSS 3.2.1 real-time WebSocket-delivery
row. A real HTTP Upgrade received pong, alert, and status frames in order; the
Redis entry was acknowledged only after callback delivery; malformed input
produced no application frame while the socket stayed usable; and all owned
state was removed.

The run did not call the VSS Agent, change the normal alert streams, touch
VIOS/RT-CV streams, use Warehouse data, contact Slack, or make external calls.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/alert-websocket-manifest-runtime-successor/compiler.py check
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  deploy/docker/thor-local/qualification/alert-websocket-manifest-runtime-successor/tests/test_compiler.py
```
