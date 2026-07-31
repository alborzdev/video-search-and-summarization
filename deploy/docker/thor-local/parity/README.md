# Thor VSS parity ledger

This directory is the acceptance ledger for the Thor-local VSS integration. It
separates four facts that are easy to conflate:

1. NVIDIA advertises a capability.
2. Its source or deployment asset is present in this checkout.
3. The Thor profile selects and configures it.
4. It has passed a current end-to-end run on this Thor.

The authoritative target is NVIDIA's protected `main` at
`7732edf8fb38ef896b20f2a0a6a701a4db10dc57`: VSS 3.2.1 plus the current LVS
invalid-purpose API fix. Unreleased nightly/develop snapshots are recorded but
do not silently redefine the GA acceptance target.

Run the static contract check from the repository root:

```bash
python3 deploy/docker/thor-local/parity/verify_manifest.py
```

Print the current gap report:

```bash
python3 deploy/docker/thor-local/parity/verify_manifest.py --report
```

`official-capabilities.json` is the reviewed claim-level gap ledger behind the
newly enumerated families. It records a dated review of the versioned VSS 3.2.1
documentation and current `main`, including model IDs, components, APIs, protocols,
evaluation/calibration/tooling contracts, release-note behaviors, external
boundaries, official platform prerequisites, the narrower NVIDIA Thor support
statement versus the custom all-local lane, digest-bound core API/MCP operation
surfaces, Agent Skills and harnesses, Orchestrator MCP operations, and
documentation/repository discrepancies. Validate it directly:

```bash
python3 deploy/docker/thor-local/parity/verify_official_capabilities.py --report
```

`official-capabilities.schema.json` documents the on-disk format. The validator
requires every reviewed claim to be cross-linked from exactly one manifest
family and from an acceptance scenario. Its per-source hashes protect the
locally reviewed claim sets; they do not content-pin or re-fetch NVIDIA's remote
HTML. Adding a claim without an explicit status, gap, scenario, and blocker
therefore fails the normal parity verifier. A generic plan-only scenario records
an open gap, not capability-specific runtime acceptance.

Every source must back at least one precise claim. Core API/MCP claims also bind
the checked-in operation manifests by repository path, exact SHA-256, and
operation/tool count. This prevents a documentation URL or a stale aggregate
count from being treated as operation-level coverage.

`capability-oracles.json` is a capability-specific planning index, not an
executable acceptance suite. It expands every reviewed capability into a unique
record with the exact ledger semantics, scenario and prospective fixture
identity, required observations/assertions, arithmetic work bounds, admission
gates, and intended mutation ownership. These prose-derived requirements are
useful for implementation review but do not provide fixture files/generators,
commands/requests, collectors, or executable cleanup. All 131 entries are
therefore explicitly `planning_index_only`; the executor-ready count is zero.
The seven planned modes are static, config, runtime, API, protocol, model, and
deploy.

Validate or review the oracle counts without executing any oracle:

```bash
python3 deploy/docker/thor-local/parity/capability_oracles.py --report
```

The validator rejects missing capabilities, source/locator/gap/status/contract
drift, generic record reuse, arithmetic bound drift, fabricated evidence,
unbounded prerequisites, and inclusion of the excluded warehouse sample. Its
cleanup fields are reviewed intent and allowlists, not proof that cleanup ran.
An entry may become `executor_ready` only after its exact fixture path,
generator and SHA-256, executor, collectors, mutation pre-state capture, cleanup
executor, and postcondition collectors are implemented and reviewed.

`passed_current` evidence is rejected for every current planning-only entry.
Future executor-ready evidence must bind the canonical oracle SHA-256, fixture
identity/digest, product and GA/main commits/date, exact oracle scenario, every
observation and assertion (including expected values), and all cleanup
postconditions. A generic `pass` check cannot advance the ledger.

The seven non-REST protocol planning records additionally bind the exact
[`protocol-cases.json`](../qualification/protocol-cases/protocol-cases.json)
whole-file and internal-set hashes, matching case and vector IDs, target commit,
and every source content/blob hash. The standalone protocol validator remains
static-only; all seven cases are unexecuted. Future executor evidence must
repeat those bindings and a passing cleanup result.

`candidates/wave2/` is validated by the unified static wrapper as an inert
proposal package. Its 30 proposed capabilities and 9 enrichments do not change
the live 131-capability denominator unless its separate merge plan is reviewed
and applied later.

Compile the complete stateful acceptance plan without executing it:

```bash
python3 deploy/docker/thor-local/qualification/acceptance.py
```

The default Phase 0 planner fail-closes unless every inventoried feature
capability, skill, REST operation, MCP tool, and MCP prompt has a scenario and
explicit blockers. Planning reports zero network requests, processes, or
mutations. A separately declared, explicitly acknowledged Phase 1 canary can
exercise only the RT-VLM/RT-Embed file lifecycle; all other planned actions
remain non-executable. See `qualification/ACCEPTANCE.md` for its owned
namespace, exact-target cleanup, fixture, and append-only ledger contracts.

`manifest.json` is intentionally conservative. `source_only`, `partial`,
`static_only`, `not_qualified`, and `blocked` are open work, not parity. A
feature may become `wired` only when the Thor Compose/config path selects it;
it may become `passed_current` only when a reproducible runtime check and its
evidence are recorded.

Some NVIDIA features are external surfaces rather than local runtime features:
Helm and VLM autoscaling require Kubernetes, Slack is a third-party destination,
Brev is a hosted platform, named managed model endpoints need their providers,
and secure deployment assumes operator-managed authentication/TLS/rate limits.
The complete local goal requires either a documented local replacement or an
explicit `external_optional` boundary; external services must never be
represented as offline functionality.

NVIDIA's versioned warehouse app-data resource is an optional reference
fixture, not a VSS capability and not a parity gate. The roughly 100 GB sample
bundle is excluded from this Thor acceptance target. Warehouse acceptance is
based on the local custom-data contract (operator-provided compatible models,
videos/streams, and calibration) plus reproducible static and runtime evidence;
an unavailable NVIDIA sample must not turn that capability into a blocker.

Register the 16 versioned NVIDIA VSS skills with Codex, or verify the current
host registration, with:

```bash
deploy/docker/thor-local/install-vss-skills.sh install
deploy/docker/thor-local/install-vss-skills.sh status
```
