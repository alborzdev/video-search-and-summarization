# Evidence status

Status: **static candidate only; non-promoting**.

Materialized here:

- strict source locks for the canonical capability/oracle, execution-bound
  integration, planning requirement, and local20 fixture;
- an exact 8-request / 9-action future workflow;
- explicit prestate, ownership admission, adjacent-negative, LIFO cleanup,
  readback, restoration, and late-effect contracts;
- closed schemas for the contract, inert plan, and fake simulation; and
- plain-data fake-transcript tests that reject callbacks, live-looking
  transports, and semantic drift.

Not observed:

- VIOS service or configuration state;
- actual fixture generation, media identity, upload, transcode, or replay;
- the playback failure or remediated synchronized playback at runtime;
- asynchronous playback-ready convergence; or
- cleanup races and delayed resource reappearance.

Consequently this package supplies a materialized qualification candidate, not
runtime evidence. It must not set `materialized`, `executor_ready`,
`runtime_state`, `current_state`, or `promotion_eligible` in canonical ledgers.
