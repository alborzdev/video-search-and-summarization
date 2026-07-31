# Thor runtime-infrastructure coverage — 2026-07-31

## Outcome

The source-safe runtime tier now covers all selected HTTP-readable
infrastructure surfaces: Elasticsearch, Kibana, Phoenix, Logstash,
Prometheus, Grafana, node-exporter, cAdvisor, and the Thor tegrastats exporter.
The complete inventory is 21 services and 30 GET-only loopback probes. No
container was started, stopped, built, or downloaded during this work.

Prometheus qualification is not a generic HTTP check. A bounded read of
`/api/v1/targets` requires exactly one healthy target for each versioned job:
`prometheus`, `node-exporter`, `cadvisor`, `tegrastats-exporter`, `rtvi-vlm`,
`rtvi-embed`, and `lvs`. Missing, extra, repeated, or unhealthy jobs fail with
counts and a drift fingerprint; live target URLs and response bodies are not
emitted. Grafana is required to serve the provisioned
`thor-vss-observability` dashboard by UID.

Phoenix and Logstash's direct management APIs are now Thor-loopback only.
Host-mode HAProxy receives explicit `PHOENIX_HOST=127.0.0.1`; the shared
Compose default remains `${HOST_IP}` for every non-Thor profile. Kibana retains
its host binding because the bridged UI server uses `host.docker.internal` for
server-side dashboard discovery; its port is explicitly covered by the Thor
firewall/listener audit. The staged Kibana 9.3.3 config schemas show telemetry,
newsfeed, and Fleet network features default enabled; the VSS air-gapped
configuration disables usage telemetry, OpenTelemetry export, the remote
newsfeed, and Fleet registry activity. Phoenix 14.15.0's staged source
establishes `/readyz` as a database-backed readiness route and documents that
telemetry and external resources default enabled. Thor explicitly sets
`PHOENIX_TELEMETRY_ENABLED=false` and
`PHOENIX_ALLOW_EXTERNAL_RESOURCES=false`. Phoenix joins the host network and
removes its inherited bridge port publication, so its `127.0.0.1` bind is the
same loopback reached by host-mode HAProxy and Agent rather than an isolated
container loopback.

## AGX Thor GPU telemetry decision

Read-only host inspection found:

- `nvidia-smi` identifies `NVIDIA Thor` and reports utilization and GPU
  temperature, but framebuffer memory and supported clocks are `N/A` on this
  integrated GPU;
- neither `dcgmi` nor `nv-hostengine` is installed, and the released
  `nvidia/dcgm-exporter:3.3.6-3.4.2-ubuntu22.04` image is not staged;
- `/usr/bin/tegrastats` is installed by the Jetson/L4T stack and a bounded
  sample reports RAM, CPU utilization/frequencies, GPU temperature, GPU power,
  system power, and SoC temperatures.

Therefore DCGM remains excluded from the Thor profile. The stdlib-only local
`tegrastats` exporter is now integrated as the authoritative GPU/power
telemetry path for this host. It reuses the locked VSS Agent image, listens
only on `127.0.0.1:19101`, accepts at most 16 KiB per sample, caps dynamic
labels, emits numeric metrics only, and fails readiness when samples are
missing or stale. Its host binary runs through read-only mounts of the exact
host loader, libc, and libm rather than relying on the image ABI. Its nine
parser/state/HTTP/ABI tests and Compose/Prometheus static contracts pass; the
container and live scrape remain runtime-unqualified.

## Reproduction

```bash
bash deploy/docker/test-scripts/test-thor-runtime-infrastructure.sh
python3 -m unittest discover \
  -s deploy/docker/thor-local/qualification/tests -v
deploy/docker/scripts/thor-local.sh qualify \
  --tier runtime --timeout 0.5 --compact
```

Static results:

```text
All Thor runtime-infrastructure static contracts passed.
Ran 23 tests ... OK
```

The final command ran against the deliberately stopped stack and returned
`result: unavailable`, exactly 30 unavailable probes, zero
passes/failures/skips, and exit status 2. That current count includes the
tegrastats exporter. It remains absence evidence, not a runtime pass; current
live qualification still requires the operator-approved unified stack start.
