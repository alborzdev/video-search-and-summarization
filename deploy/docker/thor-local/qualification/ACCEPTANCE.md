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
locator in the validated plan. Failed cleanup attempts are recorded and later
cleanup continues in LIFO order.

## Tests

Run the isolated suite:

```bash
deploy/docker/test-scripts/test-thor-stateful-acceptance.sh
```

The tests use only checked-in JSON and temporary local ledger files. They do
not open sockets, spawn processes, call Docker, change service lifecycle, or
mutate VSS. Adversarial cases cover remote/userinfo origins, redirects and
proxy policy, response and SSE limits, fixture tampering, namespace escape,
foreign resources, non-LIFO or inexact cleanup, missing coverage and blockers,
ledger mode/link/chain corruption, and redacted configuration failure.

Phase 1 integration must add an explicit execution subcommand and operator
opt-in; it must not make planning executable by default. Before enabling any
REST operation, MCP tool, or MCP prompt, replace its
`operation-classification-required` blocker with an exact semantic safety
class, owned-resource mapping where applicable, response oracle, and cleanup
locator.
