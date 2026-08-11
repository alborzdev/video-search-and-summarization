# RT-VLM Prometheus and OpenTelemetry runtime successor

This package binds official capability 366 to current-Thor runtime evidence.
It proves the live RT-VLM OpenTelemetry-backed Prometheus endpoint, the healthy
Prometheus bridge scrape and `up=1` query, plus local production OpenTelemetry
span and metric exports through the supported console exporters.

The default command is inert. Acknowledged execution performs four read-only
loopback requests and one isolated child process inside the RT-VLM container.
It makes no model, Agent, asset, stream, or service-lifecycle request.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 execute.py plan
PYTHONDONTWRITEBYTECODE=1 python3 execute.py execute \
  --ack I_ACK_LOCAL_RT_VLM_PROMETHEUS_AND_OTEL_EXPORT_PROOF
```
