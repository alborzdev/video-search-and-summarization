# Thor-local Qwen alternate qualifier

This package provides one bounded runtime check for the already-provisioned
`datasheet-chat` and `datasheet-vision` endpoints. It is deliberately a
**non-official local alternate** lane. A pass does not establish official NVIDIA
model equivalence, does not advance an official VSS capability, and must not be
copied into the acceptance inventory or capability oracles as official runtime
evidence.

The contract binds:

- VSS 3.2.1 at peeled tag commit
  `7640d917047cf7b0fd3085eefb8282754b56bc94`;
- reviewed upstream `main`
  `7732edf8fb38ef896b20f2a0a6a701a4db10dc57`;
- the local source baseline
  `ee82896c01e66e03502d24bdafe6b46e20679785`;
- the actual commit current when evidence is emitted, resolved read-only from
  `.git/HEAD` without Git or another subprocess;
- the complete artifact lock SHA-256 and the canonical lock entries for
  `Qwen/Qwen3.6-35B-A3B-FP8` at revision `95a723d...` and
  `Qwen/Qwen3-VL-8B-Instruct-FP8` at revision `9cdc631...`;
- vLLM image digest `sha256:6402d5ac...`;
- exact local endpoint/model pairs: `172.17.0.1:8000` / `datasheet-chat` and
  `172.17.0.1:8003` / `datasheet-vision`.

## Inert plan mode

The default mode validates the checked contract and artifact ledger, prints a
JSON plan to stdout, and sends no HTTP requests:

```bash
python3 deploy/docker/thor-local/qualification/local-alternate-models/qualify.py
```

It never calls Docker or a subprocess, reads credentials, downloads anything,
changes lifecycle state, or writes a file.

## Explicit bounded execution

Execution requires the exact acknowledgement below. Do not run it until the
operator has separately started both endpoints and authorized runtime probing.

```bash
python3 deploy/docker/thor-local/qualification/local-alternate-models/qualify.py \
  --execute \
  --ack I_ACKNOWLEDGE_THIS_IS_A_NON_OFFICIAL_ALTERNATE_MODEL_TEST_WITH_NO_OFFICIAL_VSS_CAPABILITY_PROMOTION
```

The execute path makes at most four direct, no-proxy HTTP requests, in order:

1. exact `/v1/models` identity at the LLM endpoint;
2. exact `/v1/models` identity at the VLM endpoint;
3. one forced `ping` tool-call request with
   `chat_template_kwargs.enable_thinking=false`;
4. one four-image vision request using deterministic 56×56 red, green, blue, and
   yellow PNGs generated only in memory.

Every request has a ten-second transport timeout, a 256 KiB request limit, and
a 1 MiB response limit. Redirects are rejected and never followed. The client
uses fixed IPv4 hosts directly and does not consult proxy variables. Requests
carry no credentials. Output is controlled JSON evidence on stdout; raw model
responses are never printed or retained.

The evidence document validates against `evidence.schema.json`. A `passed`
document proves only that this exact alternate pair satisfied these four probes
at that moment. It does not prove container-image identity by introspection—the
digest is the required deployment binding—and it performs no deployment or
cleanup itself.

## Failure-safe temporary lifecycle runner

`lifecycle.py` wraps the qualifier for the narrow case where Thor does not have
enough available unified memory to start the already-provisioned Qwen VLM next
to every currently running workload. It is also inert by default:

```bash
python3 deploy/docker/thor-local/qualification/local-alternate-models/lifecycle.py
```

Plan mode validates the existing qualifier contract and artifact lock, emits a
machine-readable plan, and constructs no Docker runtime. It performs no HTTP
request or lifecycle action.

Execute mode is permitted only after the operator authorizes this exact scope:

> Temporarily stop `ctai-vision-playground-api`, remeasure available memory,
> and stop `datasheet-embedding` only if memory remains below 50 GiB. Then
> start and qualify only `cti-vss-qwen3-vl`. Preserve all containers, images,
> volumes, files, and data; keep `datasheet-vllm-30` running; stop Qwen before
> restoring only workloads actually stopped by this run. Abort and restore if
> memory remains below 50 GiB.

After receiving that authorization, use the exact acknowledgement gate:

```bash
python3 deploy/docker/thor-local/qualification/local-alternate-models/lifecycle.py \
  --execute \
  --ack I_AUTHORIZE_TEMPORARY_QWEN_VLM_LIFECYCLE_WITH_FAILURE_SAFE_RESTORATION
```

The runner fails closed before the first mutation unless the reviewed snapshot,
image and container-command identity gate passes; the vision API, embedding,
and `datasheet-vllm-30` are running; Qwen is stopped; and the exact local LLM
identity is ready. Environment variables cannot redirect the identity gate to
different Thor model containers, endpoints, revisions, or cache paths.

The identity gate SHA-256-locks the reviewed provisioner and every repository
helper it executes or imports, then independently verifies both model
containers. The stopped Qwen container's full launch contract includes the
exact image ID and digest-qualified image reference, entrypoint, complete argv
and immutable model/tokenizer revisions, user and working directory, host
networking, NVIDIA runtime, `restart=no`, role label, exact host Hugging Face
cache bind and container target, a canonical digest over the complete
environment, and fail-closed privileged/namespace/capability/security fields.
Canonical digests over the complete Docker `Config` (normalizing only Docker's
generated hostname) and complete `HostConfig` make unlisted launch surfaces
fail too, including healthchecks, tmpfs mounts, log-driver changes, or future
fields not covered by the readable assertions.
The already-running LLM predates the role label and three offline flags, so its
preserved-running contract accepts exactly either that legacy label/environment
pair or the current provisioner's exact pair; no mix-and-match or extra
environment field is accepted, and all other identity, mount, lifecycle, and
live local-model checks remain mandatory. The runner never starts or stops that
LLM. A substring match, altered entrypoint, mutable image reference, different
mount, injected environment, privileged mode, or namespace/capability change
therefore fails before the first stop.

The lifecycle is bounded as follows:

1. Stop only `ctai-vision-playground-api`, then sample `MemAvailable` for up to
   30 seconds.
2. Stop `datasheet-embedding` only if 50 GiB has not become available, then
   sample for up to 60 more seconds. If admission still fails, restore and exit.
3. Recheck the 50 GiB floor and `datasheet-vllm-30` immediately before starting
   only `cti-vss-qwen3-vl`.
4. Poll the fixed no-proxy VLM `/v1/models` endpoint at most 90 times and for no
   more than 900 monotonic seconds. Each request is capped at the smaller of the
   qualifier's ten-second transport timeout and the time remaining. A
   nonblocking socket loop applies the same absolute deadline across connect,
   send, and every response chunk, so a slow-drip response cannot reset the
   timeout or leak a worker. The wall-clock deadline and request-count bound both
   hold, and polling stops early if Qwen exits.
5. Call the existing qualifier. Only its exact non-official, four-request pass
   is accepted.
6. In `finally`, stop Qwen first and verify it is no longer running. Restore in
   reverse order only containers this invocation actually stopped. Any Qwen
   stop or workload restoration failure makes the entire run fail.

If Qwen cannot be confirmed stopped, the runner deliberately does not restart
the memory-heavy workloads underneath it. It reports a cleanup failure for
operator intervention instead of risking unified-memory overcommit. The runner
never starts or stops `datasheet-vllm-30`, never invokes Docker Compose, and
never creates, removes, restarts, pulls, or downloads anything. Its JSON output
remains alternate-lane evidence and cannot promote an official VSS capability.

Cleanup treats any raw Docker `State.Running=true` value—and the `running`,
`paused`, or `restarting` states—as active Qwen residency. SIGINT and SIGTERM
are blocked before preflight, consumed at safe checkpoints to enter the normal
failure path, and held through all cleanup and restoration. A signal arriving
during cleanup is consumed only after cleanup finishes, then the caller's
original signal mask is restored. Because POSIX signal masks are per-thread,
execute mode fails closed before mutation unless it is the only live Python
thread and is running on the main thread. Docker CLI helpers run in a separate
session so a terminal process-group interrupt cannot bypass the parent's masked
cleanup. Cleanup is idempotent: Qwen is stopped first, and only workloads
verified stopped after this invocation's stop attempts are restarted.

Plan, gate-failure, pass, and runtime-failure documents validate against the
strict, no-extra-fields `lifecycle-evidence.schema.json`. The nested qualifier
evidence remains governed by its existing `evidence.schema.json`.
