# Fixed-topology scaling configuration qualification

This isolated package statically qualifies the opt-in configuration source in
`deploy/docker/thor-local/scaling`. It covers exactly:

- `systems-alert-worker-scaling` → `performance.alerts.worker-scaling`;
- `systems-vios-scaling` → `deployment.vios.horizontal-scaling`.

The validator pins fourteen source files, rechecks the canonical planning and
capability identities, and proves the new profiles remain outside the default
Compose graph. It requires one-instance defaults, bridge networking, no fixed
container names, no replica host ports, explicit singleton services, generated
VIOS replica identity, per-replica anonymous writable state, Docker-DNS ingress,
the Thor-local Alert derivative, generated-environment VLM endpoint/model
substitution, the standalone project-directory bind contract, the Alert shared
Kafka group, blocking worker queue, chunk size one, and private per-replica
metrics.

Run the static validator:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 deploy/docker/thor-local/qualification/fixed-topology-scaling-config/validator.py --pretty
```

Run its tests:

```bash
PYTHONDONTWRITEBYTECODE=1 pytest -q -p no:cacheprovider deploy/docker/thor-local/qualification/fixed-topology-scaling-config/tests/test_scaling_config.py
```

The validator has no Docker, network, subprocess, or lifecycle mode. Static
configuration is not runtime qualification and does not advance either ledger
row. A future authorized run still must prove exact image compatibility, Thor
capacity, Kafka partition assignment, load/backpressure accounting, VIOS RTSP
routing and playback ownership, failure recovery, and exact cleanup.
