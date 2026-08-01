# Behavior Analytics candidate-static executor

This isolated lane executes a bounded, deterministic subset of the six open
Behavior Analytics systems requirements against the checked-in production
Python modules. It uses import-only dependency stubs and in-memory broker
fakes, opens no network connections, writes no files, starts no services, and
does not use the Warehouse sample bundle.

The lane is deliberately non-advancing. A green result is
`candidate_static_pass_non_advancing`; `runtime_evidence` remains empty and
the canonical acceptance/oracle ledgers remain unchanged.

## Canonical bindings

| Planning requirement | Capability | Oracle | Product subset executed |
| --- | --- | --- | --- |
| `systems-behavior-pipeline` | `runtime.behavior.pipeline` | `oracle.runtime.behavior.pipeline` | Constituent config, calibration, ROI, violation-state/metrics, and embedding stages; not the full process graph |
| `systems-behavior-dynamic-config` | `configuration.behavior.dynamic-update` | `oracle.configuration.behavior.dynamic-update` | Real validator and `ConfigApplier`, including success, partial-success, and failure boundaries |
| `systems-behavior-calibration` | `calibration.behavior.dynamic` | `oracle.calibration.behavior.dynamic` | Real schema validator, merge/delete state logic, and existing-file reload delegation |
| `systems-behavior-events` | `runtime.behavior.events-incidents` | `oracle.runtime.behavior.events-incidents` | Real ROI/tripwire helpers and all four violation-state paths |
| `systems-behavior-embedding-downsampling` | `runtime.behavior.embedding-downsampling` | `oracle.runtime.behavior.embedding-downsampling` | Real pass-through, SDT, sliding-window, invalid-record filter, and pending flush logic |
| `systems-behavior-sinks` | `protocol.behavior.broker-sinks` | `oracle.protocol.behavior.broker-sinks` | Real factory and Kafka/Redis Streams/MQTT write methods over all seven advertised output routes using deterministic fakes |

The contract pins canonical planning/capability/oracle objects plus 75 exact
product and product-test file hashes, including every repo-backed product
module loaded by the observed import graph. The executor fails closed on any drift,
duplicate JSON key, non-finite JSON number, path escape, symlinked source, or
schema mismatch.

## Exact commands

Run the executable candidate:

```bash
python deploy/docker/thor-local/qualification/systems-behavior-analytics-static-executor/executor.py
```

Run its built-in invariant check:

```bash
python deploy/docker/thor-local/qualification/systems-behavior-analytics-static-executor/executor.py --self-test
```

Run the adversarial suite:

```bash
pytest -q -W ignore::pydantic.warnings.PydanticDeprecatedSince20 deploy/docker/thor-local/qualification/systems-behavior-analytics-static-executor/test_executor.py
```

Run formatting/static checks:

```bash
ruff check deploy/docker/thor-local/qualification/systems-behavior-analytics-static-executor/executor.py deploy/docker/thor-local/qualification/systems-behavior-analytics-static-executor/test_executor.py
git diff --check -- deploy/docker/thor-local/qualification/systems-behavior-analytics-static-executor
```

## What this does not prove

This lane does not execute bbox/tracking media, the CRS coordinate-transform
provider, broker listeners, acknowledgement/timeout flows, filesystem
watchers, multi-worker fan-out, live broker delivery, service deployment,
restart behavior, performance, or Jetson Thor runtime readiness. Those remain
explicit blockers in every result.
