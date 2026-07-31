# Thor-local observability wiring — 2026-07-31

## Scope

This milestone wires the released Prometheus/Grafana monitoring stack into the
unified `bp_developer_thor_full_2d` profile and stages its exact ARM64 images.
No monitoring or VSS container was started, and the runtime state remains
unqualified.

## Static result

- The resolved Thor-full graph grows from 27 to 32 services by selecting
  `prometheus`, `grafana`, `node-exporter`, `cadvisor`, and the Thor-only
  `tegrastats-exporter`.
- `dcgm-exporter` remains limited to its existing datacenter/warehouse
  profiles. It has not been proven compatible with this Jetson/Thor runtime,
  so the Thor profile does not silently claim that GPU-specific lane.
- The shared monitoring Compose preserves its prior non-Thor exposure behavior
  with an explicit `0.0.0.0` default. Thor must set
  `MONITORING_BIND_ADDRESS=127.0.0.1`; with that override, the four published
  endpoints resolve as:
  Prometheus `127.0.0.1:9090`, Grafana `127.0.0.1:35000`, node-exporter
  `127.0.0.1:19100`, and cAdvisor `127.0.0.1:18080`. Their host ports are
  independently overridable with `PROMETHEUS_PORT`, `GRAFANA_PORT`,
  `NODE_EXPORTER_PORT`, and `CADVISOR_PORT`.
- Prometheus now persists to a named volume with overridable bounds of seven
  days and 10 GB. All monitoring containers use bounded local Docker logs.
- Prometheus has an in-container `promtool` readiness check, and Grafana checks
  its `/api/health` endpoint with the curl client included in the pinned Ubuntu
  image. Grafana waits for healthy Prometheus rather than merely a started
  process.
- Scrape targets are profile-safe. The shared warehouse configuration keeps
  DCGM and contains no Thor-only service targets. The separate
  `deploy/docker/thor-local/observability/prometheus.yml` contains no DCGM
  target and scrapes Prometheus, node-exporter, cAdvisor, the tegrastats
  exporter, RT-VLM, RT-Embed, and LVS. `PROMETHEUS_CONFIG_FILE` can select
  this file at Compose resolution, or the Thor overlay can mount it at
  `/etc/prometheus/prometheus.yml`.
- The tegrastats exporter reuses the already locked ARM64 VSS Agent image and
  the host's L4T `/usr/bin/tegrastats`; it adds no package, image, or runtime
  download. The binary is invoked with read-only mounts of its exact host
  AArch64 loader, libc, and libm, isolating it from the image's Python runtime.
  Its HTTP server is hardcoded to loopback, while the deployment contract pins
  `TEGRASTATS_PORT=19101`; it rejects samples
  over 16 KiB, caps CPU/temperature/power label counts, and returns unready
  until the child process has supplied a fresh recognized sample.
- Grafana provisions the Prometheus datasource with the stable `prometheus`
  UID expected by the new Thor dashboard. Provisioning mounts are read-only,
  update/news/plugin checks and external snapshots are disabled, and the
  dashboard has no external URLs.
- The new `Thor-local VSS Observability` dashboard reports target state,
  scrape duration, and samples per scrape for the local VSS services and
  exporters, including LVS and the tegrastats target.

## Metrics endpoint audit

| Service | Source-proven endpoint | Thor scrape decision |
|---|---|---|
| RT-VLM | `/v1/metrics` in `services/rtvi/rt-vlm/src/server/rtvi_vlm_server.py` | Included through Compose DNS at `rtvi-vlm:8000`. |
| RT-Embed | `/v1/metrics` in `services/rtvi/rt-embed/src/server/rtvi_embed_server.py` | Included through Compose DNS at `rtvi-embed:8000`. |
| LVS | `f"{API_PREFIX}/metrics"` in `services/video-summarization/src/via_server.py`; Thor's static API inventory substitutes an empty `API_PREFIX` | Included as `/metrics` at `host.docker.internal:38111`; LVS uses host networking. |
| RT-CV | No HTTP Prometheus route exists in the checked-in service source. Compose exposes OTLP exporter settings only. | Not included. Qualify OTLP separately before claiming metrics export. |
| Alert Bridge | `services/alert/enhance_alert_with_vlm.py` starts a separate `/metrics` server on port `9081` only when `PROMETHEUS_METRICS_ENABLED=true`. The main API's port-9080 `/metrics` route is only a text pointer to that server. | Not included because the Thor Compose service does not enable the metrics server. Enable and qualify port 9081 before adding the target. |
| Phoenix 14.15.0 | The pinned upstream source supports `PHOENIX_ENABLE_PROMETHEUS=true` and then starts a separate Prometheus server on port `9090`. This defaults false. See [Phoenix 14.15.0 config](https://github.com/Arize-ai/phoenix/blob/arize-phoenix-v14.15.0/src/phoenix/config.py) and [server metrics implementation](https://github.com/Arize-ai/phoenix/blob/arize-phoenix-v14.15.0/src/phoenix/server/prometheus.py). | Not included because the current Phoenix Compose service does not enable it. Phoenix OTLP trace ingest remains independent at `/v1/traces`. |

This produces no known guaranteed-down target in the Thor-specific static
configuration. Alert Bridge, Phoenix, and RT-CV are documented gaps rather
than optimistic scrape entries.

## Reproduction

```bash
bash deploy/docker/test-scripts/test-thor-observability.sh
```

Initial observation on AGX Thor before image staging:

```text
All Thor observability static contracts passed.
Ran 9 tests ... OK
SKIP: runtime images are not staged (test never pulls):
  ghcr.io/google/cadvisor:0.56.2
  grafana/grafana:13.0.1-ubuntu
  quay.io/prometheus/node-exporter:v1.11.1
  quay.io/prometheus/prometheus:v3.11.3
```

The four exact upstream-pinned images were then staged explicitly for
`linux/arm64` without starting containers. A second run produced no skip and
reported the static contract as passing. Read-only image inspection recorded:

| Image | Local image ID | Architecture |
|---|---|---|
| `quay.io/prometheus/prometheus:v3.11.3` | `sha256:c0b857aead0d5793aa566adb8f49a9983d6f6031652098759d521a330cfa050f` | `arm64` |
| `grafana/grafana:13.0.1-ubuntu` | `sha256:15baab58cbdcf288c36a20ea9e469fe6c60955e725ddc56060377b27e9eaa47c` | `arm64` |
| `quay.io/prometheus/node-exporter:v1.11.1` | `sha256:0f422f62c15f154af8d8572b23d623aebfb10cec73a5c654d18f911f3f9df241` | `arm64` |
| `ghcr.io/google/cadvisor:0.56.2` | `sha256:5534ae91cbf3428998d60428d107cfdd97272d80658534ac6e54d8ce3b0c4d72` | `arm64` |

Image history also proves that the pinned Grafana Ubuntu image installs
`curl`, and that the pinned Prometheus image contains `/bin/promtool`, matching
the configured in-container healthchecks. These are image/static facts, not a
claim that either endpoint is currently live.

The test also resolves the full Compose graph with Thor's explicit loopback and
config-file overrides, asserts that every published monitoring port binds
`127.0.0.1`, verifies that the resolved Prometheus mount uses the Thor-specific
configuration, validates the route decisions above against checked-in source,
checks retention/log bounds and offline Grafana settings, and verifies the
architecture of any already-staged image on ARM64. Missing images are reported
but never downloaded.

## Remaining runtime gates

1. Start the user-approved Thor deployment and prove Prometheus `/-/ready`,
   Grafana `/api/health`, successful provisioning of the dashboard, and `up=1`
   for Prometheus, node-exporter, cAdvisor, tegrastats, RT-VLM, RT-Embed, and
   LVS.
2. Exercise an agent request and prove the trace reaches the existing local
   Phoenix `/v1/traces` endpoint. RT-VLM and RT-Embed OTLP exporters remain
   disabled until their direct local-Phoenix route is runtime-qualified;
   their Prometheus endpoints are nevertheless scraped locally.
3. Capture current listener/firewall evidence for Phoenix and the rest of the
   host-network infrastructure. This source milestone does not weaken or
   bypass the Thor firewall gate.

Until those gates pass, observability is wired but not runtime-qualified.
