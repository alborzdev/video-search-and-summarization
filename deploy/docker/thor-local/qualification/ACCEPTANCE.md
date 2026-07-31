# Thor stateful acceptance: Phase 0

`acceptance.py` is the fail-closed planning layer for stateful Thor VSS
acceptance. Phase 0 validates the complete plan and prints it; it cannot run an
HTTP request, invoke a tool, start a process, change a container, or mutate a
VSS resource.

From the repository root:

```bash
python3 deploy/docker/thor-local/qualification/acceptance.py
```

The command exits zero only when `acceptance_inventory.json` assigns every
current advertised capability, installed VSS skill, REST operation, MCP tool,
and MCP prompt. Coverage is expanded from the parity manifest and reviewed API
manifests, rather than copied into a second list. An upstream addition therefore
fails planning until it has a scenario and an explicit blocker. A plan is not
runtime evidence and does not change a feature's parity status.

## Safety contract

- HTTP origins must use numeric IPv4 or IPv6 loopback over plain HTTP. Ambient
  proxies are disabled and redirects are refused.
- Response bodies have a hard byte limit. SSE has independent byte, event, and
  elapsed-time limits.
- Phase 0 marks every safety class non-executable. Later phases must retain the
  distinction between observation, owned create/update/delete, service
  lifecycle, external side effects, and actions still awaiting semantic
  classification.
- Created objects use `thor-vss-accept-<run-id>-...` names. The plan never
  adopts, updates, or deletes a pre-existing object.
- Every owned create registers one exact response locator. Cleanup may use only
  that locator and must run in strict reverse creation order. A broad list or
  prefix delete is not representable in the contract.
- Lifecycle and external-side-effect actions remain blocked behind explicit
  operator or external-dependency blockers.

`fixtures.json` embeds three tiny deterministic fixtures: H.264/AAC MP4,
HEVC/AAC MP4, and PNG. Each declaration includes decoded byte length, SHA-256,
media type, use cases, and a structured `ffprobe` oracle. The only permitted
probe command places `--` before the owned fixture path and contains no network
URL. A later runner may materialize a fixture only below its owned temporary
directory and must verify the hash before invoking `ffprobe`.

## Mutation ledger contract

`append_ledger_event()` is qualified now for later execution phases but is not
reachable from the Phase 0 CLI. It creates or opens one operator-selected
regular file with exact mode `0600`, refuses symlinks and hardlinks, locks the
file, validates its complete JSONL SHA-256 chain, appends one bounded record
with `O_APPEND`, and calls `fsync`. Records contain logical scenario/action and
resource IDs plus a hash of the exact runtime locator; they do not store
credentials, payloads, response bodies, or URLs.

The ledger is recovery evidence, not permission to delete. Cleanup still has
to match the namespace, logical resource, creation action, and exact registered
locator in the validated plan. A failed cleanup of the newest resource is
recorded and stops cleanup; an older resource is never deleted through a newer
resource that may still depend on it.

## Phase 1: owned RTVI file-lifecycle canary

Phase 1 is deliberately limited to client-addressed file lifecycle on RT-VLM
and RT-Embed. It does not start or stop containers, follow a returned URL,
invoke inference, operate streams, call MCP tools, or execute another planned
scenario. The default command above remains Phase 0 and makes no request.

First compile the current plan and copy its `source_fingerprint`. Then use a
private operator-owned directory with exact mode `0700`:

```bash
install -d -m 0700 /tmp/vss-acceptance-evidence

python3 deploy/docker/thor-local/qualification/acceptance.py execute \
  --scenario rtvi-file-lifecycle \
  --run-id rtvi-000001 \
  --confirm-stateful rtvi-file-lifecycle \
  --ack-source-fingerprint <CURRENT_SOURCE_FINGERPRINT> \
  --evidence-dir /tmp/vss-acceptance-evidence
```

Execution is sequential and numeric-loopback-only. For each service it:

1. materializes and hashes the embedded H.264/AAC fixture, then runs the fixed
   `/usr/bin/ffprobe` oracle;
2. derives a stable UUID from the run, scenario, and logical resource;
3. proves that exact UUID is absent;
4. writes a durable `create-intent` before the multipart upload;
5. requires the service to echo the exact UUID and namespaced ownership fields;
6. reads the exact object and verifies the downloaded media SHA-256; and
7. deletes only the predetermined UUID, verifies absence, and cleans resources
   in strict LIFO order.

The optional `--endpoint SERVICE=ORIGIN` override accepts only numeric loopback
HTTP origins and exists for isolated testing or deliberate local port remaps.
It cannot target a hostname, LAN address, HTTPS endpoint, or userinfo URL.

Phase 1 writes a mode-`0600` hash-chained ledger with schema version 2 before
the first mutation and fsyncs both new files and their parent directory. A
create intent remains cleanup-eligible even if the HTTP response is lost or
malformed. Because the resource UUID is derived rather than learned from the
response, an interrupted process can recompute the exact cleanup target without
storing a URL, credential, or raw response:

```bash
python3 deploy/docker/thor-local/qualification/acceptance.py recover \
  --scenario rtvi-file-lifecycle \
  --run-id rtvi-000001 \
  --confirm-stateful rtvi-file-lifecycle \
  --evidence-dir /tmp/vss-acceptance-evidence
```

Recovery validates the entire ledger chain and current scenario/source
fingerprints before making a request. It also binds the canonical effective
origin of each service into a separate execution fingerprint. Recovery must
use the same default ports or repeat the exact `--endpoint` mappings from the
original execution; a changed loopback service mapping is rejected before any
request. The operator acknowledgement remains tied to the reviewed plan source
fingerprint rather than the host-specific execution fingerprint. Cleanup stops
on the newest failed resource and can be retried with `recover`; if interruption
occurred after `cleanup-started`, recovery resumes that exact top cleanup
without appending a second start event. It never falls through to an older
resource or performs a list/prefix/broad delete.

The private JSON report records both reviewed source and effective-execution
fingerprints, operation results, status codes, durations, fixture and response
hashes, oracle names, cleanup result, final ledger digest, and
residual-resource count. It omits request/response bodies, raw locators, URLs,
headers, and credentials. A report is runtime evidence for this canary only;
it does not automatically promote a parity-manifest feature.

## Tests

Run the isolated suite:

```bash
deploy/docker/test-scripts/test-thor-stateful-acceptance.sh
```

Phase 0 tests use only checked-in JSON and temporary local ledger files. They
do not open sockets, spawn processes, call Docker, change service lifecycle, or
mutate VSS. Phase 1 tests use two ephemeral numeric-loopback fake HTTP servers
and the embedded fixture; they never contact VSS or Docker. Adversarial cases
cover remote origins, redirects, oversized and lost responses, wrong echoed
IDs, pre-existing resources, exact cleanup after an uncertain create,
stop-on-top cleanup failure, recovery, and ledger tampering.

Every Phase 0 HTTP action is now bound to an exact reviewed REST operation or
runtime probe. All operations outside the four file routes per RTVI service
remain non-executable. Before expanding Phase 1 to another REST operation, MCP
tool, or MCP prompt, replace its `operation-classification-required` blocker
with an exact semantic safety class, owned-resource mapping where applicable,
request builder, response oracle, and crash-recoverable cleanup locator.
