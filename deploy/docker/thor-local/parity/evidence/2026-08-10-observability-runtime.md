# Thor-local VSS observability runtime qualification — 2026-08-10

## Result

PASS. The complete Thor-local monitoring graph is live and locally isolated:
Prometheus, Grafana, node-exporter, cAdvisor, the Thor tegrastats exporter, and
Phoenix are running; all eight configured Prometheus targets are healthy; the
provisioned Grafana datasource and dashboard are live; and a fresh read-only
VSS Agent search produced a persisted Phoenix trace.

This supersedes the runtime gates in
`2026-07-31-observability-wiring.md`. It does not claim the unsupported
datacenter DCGM exporter on Jetson/Thor, and it does not enable Phoenix's
separate Prometheus listener.

## Runtime identity

| Service | Image | Runtime image ID | Health proof |
| --- | --- | --- | --- |
| Prometheus | `quay.io/prometheus/prometheus:v3.11.3` | `sha256:c0b857aead0d5793aa566adb8f49a9983d6f6031652098759d521a330cfa050f` | Docker healthy and `/-/ready` HTTP 200 |
| Grafana | `grafana/grafana:13.0.1-ubuntu` | `sha256:15baab58cbdcf288c36a20ea9e469fe6c60955e725ddc56060377b27e9eaa47c` | Docker healthy and `/api/health` HTTP 200 (`database: ok`, version 13.0.1) |
| node-exporter | `quay.io/prometheus/node-exporter:v1.11.1` | `sha256:0f422f62c15f154af8d8572b23d623aebfb10cec73a5c654d18f911f3f9df241` | `/metrics` HTTP 200 and Prometheus target up |
| cAdvisor | `ghcr.io/google/cadvisor:0.56.2` | `sha256:5534ae91cbf3428998d60428d107cfdd97272d80658534ac6e54d8ce3b0c4d72` | Docker healthy, `/healthz` HTTP 200, target up |
| tegrastats exporter | `nvcr.io/nvidia/vss-core/vss-agent:3.2.1` | `sha256:b7f3246aaf355ebf96e91a40b2f0abc5dea7e330e7bf9a7cf726107b560c3ac1` | Docker healthy, `/readyz` HTTP 200, target up |
| Phoenix | `arizephoenix/phoenix:14.15.0` | `sha256:4902edc412785dcd90ad20172c3b15def87d076a18cfc3c3df44df211993f0f0` | Docker healthy, OpenAPI and project/trace APIs HTTP 200 |

The already-staged containers had been terminated cleanly during earlier
memory work. They were restarted in exporter → Prometheus → Grafana dependency
order. Only node-exporter was recreated, to apply the Thor-specific collector
fix described below.

## Prometheus

`GET /api/v1/targets?state=active` returned eight active targets, eight with
health `up`, and zero non-empty `lastError` values:

| Job | Scrape URL |
| --- | --- |
| `prometheus` | `http://localhost:9090/metrics` |
| `node-exporter` | `http://node-exporter:9100/metrics` |
| `cadvisor` | `http://cadvisor:8080/metrics` |
| `tegrastats-exporter` | `http://host.docker.internal:19101/metrics` |
| `rtvi-vlm` | `http://rtvi-vlm:8000/v1/metrics` |
| `rtvi-embed` | `http://rtvi-embed:8000/v1/metrics` |
| `lvs` | `http://host.docker.internal:38111/metrics` |
| `alert-bridge` | `http://host.docker.internal:9081/metrics` |

The dashboard's exact `count(up{job=~"..."} == 1)` expression returned `8`.
Prometheus runs with seven-day and 10 GB TSDB retention. At qualification time
its persistent volume used 93.74 MB.

## Thor telemetry and node metrics

The private-gateway tegrastats endpoint reported:

- `jetson_tegrastats_up 1`
- `jetson_tegrastats_process_running 1`
- `jetson_tegrastats_parse_errors_total 0`
- a sub-second sample age;
- RAM usage/total, per-core CPU utilization and frequency, CPU/GPU/SoC
  temperatures, and current/average CPU/GPU/system power rails.

The shared node-exporter default attempted to read Jetson
`cpufreq/stats/trans_table`, whose pseudo-file exceeds node-exporter's bounded
sysfs reader. The target stayed up but emitted a failed collector and an error
on every scrape. The Thor Compose override now retains the host
proc/sys/rootfs paths and adds only `--no-collector.cpufreq`; tegrastats remains
the authoritative Thor clocks and power source. After recreation:

- the command contained `--no-collector.cpufreq`;
- no `node_scrape_collector_*{collector="cpufreq"}` series existed;
- no `cpufreq` or `trans_table` error appeared in the new container log;
- node-exporter remained HTTP 200 and Prometheus `up=1`.

Thermal collector labels such as `type="cpufreq-cpu0"` remain valid cooling
device data and are not the disabled cpufreq collector.

## Grafana

The unauthenticated Viewer APIs are intentionally usable only on Thor
loopback. Live API results proved:

- datasource UID `prometheus`, URL `http://prometheus:9090`, default,
  read-only;
- dashboard UID `thor-vss-observability`, title
  `Thor-local VSS Observability`;
- three provisioned panels using datasource UID `prometheus`;
- every live panel expression includes the exact eight-job set, including the
  newly qualified `alert-bridge` target.

The checked-in dashboard initially omitted Alert Bridge even though Prometheus
was scraping it successfully. All three expressions were corrected, the file
provider reloaded them without a container restart, and the live API returned
the updated expressions. Grafana's persistent volume used 50.48 MB.

## Phoenix trace path

The Agent runtime uses the local Phoenix endpoint and project
`DEV-THOR-FULL-vss-agent-3.2.1`. To prove the current post-restart path without
crossing the `/generate` safety gate or mutating the archive, the qualification
issued one direct read-only `POST /api/v1/search` request to numeric loopback:

- query: `race car in a pit stop`
- source type: `video_file`
- source: existing retained `pit-POV`
- agent mode and critic: disabled
- HTTP 200 with one `pit-POV` result at similarity 0.27
- response SHA-256:
  `feec75cf4b9720a5c84e8e1bb234275eee212d6cd8967643c90b5cd9a8b843d8`

Phoenix immediately returned one new trace after the captured request start
time. It contained three spans, all status `OK`:

1. `search` (`CHAIN`)
2. child `search` (`CHAIN`)
3. child `embed_search` (`CHAIN`)

This proves the Agent → local Phoenix distributed-trace path. It is not a
claim that Agent `/generate`, visual Q&A, or report generation has been
qualified; those remain under their separate endpoint gate.

## Local isolation

Listener state after qualification:

- `127.0.0.1:9090` — Prometheus
- `127.0.0.1:35000` — Grafana
- `127.0.0.1:19100` — node-exporter
- `127.0.0.1:18080` — cAdvisor
- `172.17.0.1:19101` — tegrastats exporter on Docker's private gateway
- `127.0.0.1:6006` — Phoenix

For every one of those six ports, a `--noproxy '*'` request to Thor's physical
`wlP1p1s0` address failed with curl exit 7 and HTTP `000`. The pending host
firewall remains defense in depth; these observability endpoints do not depend
on it for physical-interface isolation.

## Tests and resource boundary

- `bash deploy/docker/test-scripts/test-thor-observability.sh`:
  static contracts passed and **11 tests passed**.
- The live dashboard JSON, Prometheus target API, panel query, telemetry
  metrics, and Phoenix trace APIs were independently parsed and asserted.
- The six observability/trace containers used approximately 1.05 GiB RAM in
  total during the sample. Thor retained about 25 GiB available unified memory.
- Data disk headroom remained about 22 GiB; no image pull or model download
  occurred.
- The system cache cleaner remained active.
