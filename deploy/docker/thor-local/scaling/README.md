# Optional fixed-topology scaling profiles

This directory contains opt-in Compose source for the two fixed-topology gaps.
It is not included by any existing profile, so the default remains one Alert
Bridge and one VIOS stream processor.

`thor-alert-scale` defines a bridge-networked `alert-worker` service without a
fixed container name or host listener. Compose can assign unique replica
identities, while every replica retains one in-process worker, `chunk_size: 1`,
the shared `alert-bridge-vlm-group`, blocking queue semantics, and private
9080/9081 endpoints. It defaults to the Thor-local Alert derivative and renders
the mounted config through NVIDIA's `env-substitute.py`, using `VLM_BASE_URL`
and `VLM_NAME` from `thor-local/generated.env` (currently the local port 8003
and `datasheet-vision`). Existing host services are reached through the
explicit Linux `host-gateway` alias.

`thor-vios-scale` defines singleton database, Redis, Sensor, and ingress
services plus a scalable `vios-streamprocessor`. Every stream-processor replica
gets its own Compose identity, `$HOSTNAME` application identity, copied config,
and anonymous writable config/data/video/clip/temp volumes. Only the singleton
ingress publishes a host port, bound to `127.0.0.1`; its Docker-DNS resolver
routes sensor requests to the singleton and other HTTP requests to the replica
service name.

These files are configuration improvements, not runtime evidence. Before any
future run, an operator must review exact images, free memory/disk/GPU capacity,
Kafka partition count, ports, lifecycle, and cleanup. VIOS RTSP address routing,
stream ownership across replica changes, and failure recovery still need live
proof. Do not scale `vios-sensor-singleton`, `vios-scale-db`,
`vios-scale-redis`, or `vios-scale-ingress`.

## Deterministic Compose path contract

This file is a standalone Compose source, not a later `-f` overlay on
`deploy/docker/compose.yml`. Its three relative bind paths are intentionally
resolved from this directory. From the repository root, the only documented
non-lifecycle render command is:

```bash
docker compose \
  --env-file deploy/docker/thor-local/generated.env \
  --project-directory deploy/docker/thor-local/scaling \
  -f deploy/docker/thor-local/scaling/compose.yml \
  --profile thor-alert-scale \
  config
```

Use `--profile thor-vios-scale` to render the VIOS topology instead. Do not
append this file after another Compose file without preserving the same project
directory: Compose would otherwise resolve `./alert-scale-config.yml` and
`./vios-scale-nginx.conf` from a different base directory.

The command above only renders configuration. Starting, stopping, scaling, or
pulling images requires a separate authorization bundle. Static validation
lives in `qualification/fixed-topology-scaling-config` and never invokes
Docker.
