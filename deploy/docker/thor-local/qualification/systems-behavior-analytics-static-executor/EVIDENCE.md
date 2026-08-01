# Evidence: Behavior Analytics candidate-static tranche

Evidence class: deterministic source-level product execution, not runtime
evidence.

The contract binds six canonical requirements to six official capabilities
and oracles. At the locked baseline, all six capabilities remain
`partial`/`not_qualified`, all six oracles remain `open_unexecuted` with
`planning_index_only` readiness, and every runtime-evidence array is empty.
The pre-existing `systems-behavior-dynamic-config` planning row is already
materialized by a narrower source-contract executor; the other five planning
rows are not materialized. This lane verifies those exact states rather than
rewriting them.

## Deterministic observations

Two independent executions produce canonical-byte-identical observations.
The current observation digest is:

```text
d1327193d66d99a4add3ca5a644a03ce278ed84669537bbccb9beb5fba970a8d
```

Observed product behavior:

- Dynamic config applies two app values and one sensor value; mixed valid and
  invalid input returns `partial-success`; malformed, read-only-only, and
  invalid-value inputs return `failure`.
- Calibration accepts `image`, `cartesian`, and `geo`, accepts
  `upsert`/`upsert-all`/`delete`, merges and deletes sensors, preserves state
  after invalid input, and delegates updates when initialized from a file.
- ROI and tripwire helpers return the expected event boundaries. The real
  behavior state machine creates a two-point tracking state and trip state.
  Frame state creates one proximity, restricted-area, confined-area, and
  FOV-count violation state each.
- Disabled embedding filtering is identity pass-through. Five repeated
  embeddings reduce to one SDT output plus one pending flush, and two
  sliding-window outputs; one invalid record is filtered.
- Kafka, Redis Streams, and MQTT each execute seven production `write`
  routes against deterministic in-memory fakes, with zero connections.
- Ten adjacent cases record their exact outcomes: seven reject, while an
  existing-file calibration reload delegates without a type switch, an empty
  event identifier is ignored without mutation, and an invalid embedding is
  filtered.

## Confinement and claims

The result schema requires all of the following:

- zero filesystem writes, network calls, broker connections, subprocess
  calls, and service-lifecycle calls;
- Warehouse sample bundle `excluded`;
- `runtime_evidence: []`;
- `official_capability_effect: none_candidate_only`;
- `result: candidate_static_pass_non_advancing`;
- `full_pipeline_claimed: false`.

The executor itself contains no network, Docker, subprocess, URL-client, or
file-write imports/calls; an AST adversarial test enforces that boundary.
External dependency constructors are import-only sentinels that raise if the
product tries to open a real watcher, Kafka producer, Redis client, or CRS
provider. Broker write behavior is exercised only after injecting bounded
in-memory fakes.

The complete imported product closure includes the locked but uncalled
`calibration_e.py` requests client. This tranche does not execute that network-
capable calibration path and makes no provider/network claim from importing it.

Each observation uses a fresh product-module import, verifies that all 54
repo-backed loaded product files are among the 75 exact source locks, and
restores the caller's exact product/stub `sys.modules` and `sys.path` state. The zero-call counters are
assertions from exact source locks and forbidden-constructor boundaries, not
general-purpose instrumentation of all transitive dependencies.

## Residual blockers

- Full bbox/tracking/media pipeline execution.
- CRS coordinate-transform provider execution.
- Dynamic-config broker listener, atomic persistence, acknowledgements, and
  timeout fallback.
- Calibration filesystem watcher and live multi-worker reload.
- Full tripwire trajectory and incident-completion media fixtures.
- Real Kafka, Redis Streams, and MQTT delivery.
- Thor deployment, load, persistence, restart, and performance evidence.

No residual blocker is converted into runtime evidence or a canonical pass by
this package.
