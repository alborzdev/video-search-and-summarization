# Retained evidence

- Target: NVIDIA VSS 3.2.1 on arm64 Thor.
- Captured: 2026-08-10 through the local host-network Redis broker.
- Receipt SHA-256: `356960435b16060d3ff879aeff1ace27988379993833f43ccb8989a5346dcb0d`.
- Fixture contract SHA-256: `bb96e55fe28f1c480175086e4f6cfc1dc1b0216d72a825fb73eb6c9f2722953f`.
- Official evidence SHA-256: `66ed95ec555d38d32a745c14e6ff8a1af4af0e56c6874f0fb1c6d2975444b44a`.
- Capability oracle SHA-256: `e82640a315847718181cb67eff191e6206ec3e903b531016f5086545fc1c4b1a`.

The exact mounted NVIDIA Alert Bridge WebSocket modules completed a real HTTP
Upgrade on loopback. The client observed pong, one alert, and status in order.
The qualifier-owned Redis entry preserved its fields and message identity; the
consumer callback completed before `XACK`, leaving zero pending entries. A
non-JSON adjacent-negative frame produced no application response and left the
socket usable. Disconnect removed the registered connection.

The isolated container and listener, both owned streams, and their derived
consumer group were absent afterward. The non-owned Redis key-name set and the
normal alert service state matched pre-state, and Redis remained healthy. No
credentials, payload bodies beyond fixed qualifier fields, dynamic consumer
identity, Redis message ID, external requests, Warehouse data, VSS Agent calls,
or VIOS/RT-CV mutations are retained.
