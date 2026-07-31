# Thor tegrastats Prometheus exporter — 2026-07-31

## Outcome

Thor now has a local Jetson telemetry path without falsely claiming the
datacenter DCGM contract. The Thor-only Compose overlay adds
`tegrastats-exporter`, reusing the already selected and content-locked ARM64
VSS Agent image plus the host's L4T `/usr/bin/tegrastats`. No dependency,
image, package, model, or sample-data download is introduced.

The stdlib-only exporter:

- invokes tegrastats without a shell through read-only mounts of its exact
  host AArch64 loader, libc, and libm, then restarts it with a fixed
  five-second backoff;
- hardcodes its listener to `127.0.0.1:19101` and publishes no Docker port;
- rejects lines over 16 KiB and caps CPU cores at 128, temperature zones at
  32, power rails at 32, and label text at 48 safe characters;
- emits only parsed numeric memory, CPU, EMC, GPU, temperature, and power
  metrics—never the raw tegrastats line or arbitrary host text;
- exposes `/healthz`, `/readyz`, and `/metrics`, with readiness and metrics
  failing closed until a recognized sample is fresh; and
- runs read-only as the image's non-root user with all capabilities dropped,
  no-new-privileges, a 4 MiB temporary filesystem, bounded Docker logs, the
  NVIDIA runtime, and read-only host binary/sysfs mounts.

Prometheus adds `tegrastats-exporter` as its seventh exact Thor job through
Docker's private host gateway. The runtime qualifier adds a thirtieth GET-only
probe for `/readyz`, and the exact-target gate requires all seven jobs once
each with `health: up`.

## Static reproduction

```bash
bash deploy/docker/test-scripts/test-thor-observability.sh
python3 -m unittest discover \
  -s deploy/docker/thor-local/qualification/tests -v
```

Result:

```text
All Thor observability static contracts passed.
Ran 9 tests ... OK
Ran 23 tests ... OK
```

`docker compose config --services` resolves 32 Thor services, including the
exporter. These are source/config/parser facts only. No container was started
or stopped, so the exporter, its scrape, the seven-job target gate, and the
30-probe inventory remain runtime-unqualified until the operator-approved
unified qualification run.
