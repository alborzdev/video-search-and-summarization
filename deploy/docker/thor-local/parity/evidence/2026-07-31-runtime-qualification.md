# Thor runtime-qualification baseline — 2026-07-31

The protected Thor runtime contract was refreshed after staging the exact
ARM64 monitoring images and the offline Logstash derivative. The offline gate
then passed without registry credentials or network access:

```text
[OK] Every selected image matches its protected content-addressed lock.
[OK] Pinned host model checksums match.
[OK] Cosmos-Embed model shards and Thor batch-8 engines are staged.
[OK] LLM and VLM snapshots, images, and container contracts are staged.
[OK] Offline stage is complete; restart needs no image pull, build, NGC key,
or model download.
```

No application container was started. The read-only runtime tier was then run:

```bash
deploy/docker/scripts/thor-local.sh qualify --tier runtime
```

It issued only GET requests to loopback, with proxies disabled and no container
or VSS-state mutation. After the tegrastats source lane was added, the stopped
stack produced exactly 30 `unavailable` probes, zero passed, zero failed, zero
skipped, and exit status `2`. This current stopped-stack baseline includes the
exporter's `/readyz` and proves the qualifier does not turn absence into a
false pass. It remains unqualified runtime evidence. The expanded inventory
also adds Kibana
`/kibana/api/status`, Phoenix `/readyz`, the Logstash node API, the provisioned
Grafana dashboard, and a bounded Prometheus `/api/v1/targets` contract. The
last check now requires exactly the seven versioned Thor jobs once each with
`health: up`; it reports only counts and a drift fingerprint.

The ordinary preflight currently stops at the local VLM provider because
`cti-vss-qwen3-vl` is not running. Thor has about 34 GiB available unified
memory while the fail-closed VLM start gate requires 50 GiB. Unrelated GPU
containers must be temporarily stopped with operator approval before the
local VLM and complete stack can be started and the 30 probes promoted to
current runtime passes.
