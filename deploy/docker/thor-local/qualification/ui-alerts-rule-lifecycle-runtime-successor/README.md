# Thor Alerts UI rule lifecycle runtime successor

This package qualifies official capability row 169, `runtime.ui.alerts-tab`,
against the deployed Thor-local VSS UI. It covers the advertised View/Manage
surface and executes a real rule lifecycle instead of relying on source or
mock evidence.

The harness is inert without the exact acknowledgement. An authorized run
publishes the checked-in 2.5 MB H.264 fixture to the existing local MediaMTX,
creates a uniquely owned RTSP sensor through Video Management, creates and
deletes one active real-time rule through Alerts, and deletes the sensor
through Video Management. The browser is restricted to numeric loopback HTTP
services and Agent `/generate` is forbidden.

The regression exercised here is specific: VIOS exposes one proxy URL from
`/v1/live/streams` and the already registered RT-VLM URL from
`/v1/sensor/streams`. The UI keeps the documented live catalog for names but
submits the canonical sensor-stream URL by exact `streamId`, avoiding the
Alert Bridge's intentional same-ID/different-URL conflict guard.

Cleanup removes only the owned rule, sensor, RT-VLM stream, Elasticsearch
incident documents, and VST temporary media. Hashes of every unrelated rule,
sensor, VIOS stream catalog, and RT-VLM stream catalog must match before and
after. The receipt retains no sensor/rule ID or RTSP URL.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/ui-alerts-rule-lifecycle-runtime-successor/verify.py
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  deploy/docker/thor-local/qualification/ui-alerts-rule-lifecycle-runtime-successor/tests
```

See `harness.mjs --ack I_AUTHORIZE_OWNED_UI_ALERT_RULE_LIFECYCLE` in the
retained source for the explicit runtime boundary and required arguments.
