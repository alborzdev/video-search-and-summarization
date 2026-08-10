# VIOS SDR Compose runtime qualification

This qualifier locks the missing VSS camera-event dispatcher into the
Thor-local Compose and operator contracts. It verifies the pinned NVIDIA SDR
image, one-shot Redis consumer-group initialization, producer startup order,
Docker stream-processor target, loopback-only health listener, private Redis
bind, security limits, health/doctor gates, and the retained 2026-08-10 runtime
receipt.

The runtime run used an owned local NvStreamer file as an RTSP camera. It
proved current-event dispatch, generated proxy and VOD URLs, actual proxy
decode, live snapshot, always-on recording, restart persistence without Redis
backlog replay, exact sensor/proxy/recording cleanup, and removal of both
temporary fixture containers. It did not use the warehouse sample or an
external camera.

Run the networkless verifier and focused tests from the repository root:

```bash
python3 deploy/docker/thor-local/qualification/vios-sdr-compose-runtime/verify.py
pytest -q deploy/docker/thor-local/qualification/vios-sdr-compose-runtime/tests
```

The verifier validates retained evidence and current source wiring. It does not
recreate the stateful camera fixture or claim that a historical receipt is a
fresh live run.
