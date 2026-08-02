# Search exact fixture provisioner successor

This package replaces the operator-preprovisioned Search fixture assumption
with a bounded lifecycle for one small, run-owned MP4. It is inert by default
and excludes the Warehouse sample.

The lifecycle deliberately uses production paths: the agent upload handshake,
VST's one-chunk nvstreamer upload, the agent `/complete` transaction, the three
Search profile Elasticsearch indices, and agent-backed deletion. VST allocates
the UUID; the executor reconciles that UUID with a run-derived VST name instead
of pretending a caller-selected UUID was created. Elasticsearch document IDs
and sources are discovered after model inference, never injected by the
qualification harness.

The upload attempt is recorded before transport. If VST creates the sensor but
its response times out or carries an invalid identity, cleanup re-reads the
complete VST stream list and accepts only one UUID under the exact run-derived
name. It then deletes that reconciled UUID through the Agent and performs the
same two cross-system absence checks. Zero matches re-proves both deterministic
Elasticsearch name scopes; multiple matches fail closed instead of guessing.

`executor.py plan` performs only source-lock and contract checks. The gated
`exercise-http` command is numeric-loopback-only and requires the exact
acknowledgement in `contract.json`. It has not been run on Thor and therefore
does not advance canonical evidence.
All executor-managed HTTP requests share one 900-second wall-clock deadline;
180 seconds are reserved for cleanup and each request timeout is clamped to the
remaining phase budget.

The former in-process `fixture_consumer` hook is fail-closed disabled. An
unbounded callback could prevent `finally` cleanup from running, so a future
combined semantic runner must first provide an isolated consumer that shares
this executor's wall-clock deadline and cleanup reserve.

The supplied MP4 must be a reviewed custom clip no larger than 16 MiB and must
contain at least one consistently tracked object. Readiness requires:

- a positive synchronous RT-Embed chunk count;
- at least one exact owned document in embed, behavior, and raw indices;
- a behavior object with an embedding that is also present with a finite,
  non-negative, non-inverted bbox in an owned raw frame timestamped inside the
  behavior interval;
- the Elasticsearch response to prove its complete bounded hit set (`relation`
  `eq` and total equal to the returned rows), with every discovered document
  remaining within the run's allocated UUID/name identity scopes; and
- complete nonnegative Elasticsearch shard accounting with zero failed shards.

Cleanup succeeds only when agent deletion reports `success`, the VST UUID/name
is absent, every discovered document is absent by exact `_mget`, all three
identity-scoped searches return zero, and a delayed second check shows no
reappearance.

The production failed-ingest rollback removes state visible at rollback time,
but it has no proven pipeline-drain/remediation loop for writes that arrive
later. This executor detects such reappearance and fails closed; it does not
claim to repair it automatically, so live validation and remediation of that
failure path remain open.
