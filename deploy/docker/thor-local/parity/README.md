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

The live 289-capability ledger is the complete reviewed VSS 3.2.1 static
denominator. Every page in the exact 172-page documentation graph is classified,
and every reviewed claim-bearing source is merged. This is inventory closure,
not evidence that every capability runs on this Thor. A historical audit of the
152 distinct HTML targets linked directly by the versioned documentation index
found 59 substantive semantic/workflow/configuration/benchmark pages that needed
claim extraction, alongside 34 navigation/duplicate/reference pages and 8
external/license/sample-dependency pages. The machine-readable Wave 3 coverage
package under `candidates/wave3/coverage/` preserves that pre-merge denominator;
the reviewed Agent/Smart City, Systems, and Calibration/Warehouse claims are now
merged into the live ledger.

Two isolated successor packages under `qualification/` now prove the next
inventory transition without changing that live denominator. The oracle
successor preserves the 289 live rows exactly and appends 211 planning-only
candidate contracts in manifest-pointer order. The ledger successor projects
the same ordered 500 capability IDs and exact same-family advertised-title
mappings. Both retain zero candidate evidence or promotions and exclude the
Warehouse sample bundle. The ledger projection records nine raw reducer
differences and eight acceptance-coverage gaps. Separate metadata successors
resolve those into six policy-valid family updates, three preserved external
family boundaries, and eight exact acceptance links. These are still isolated
projections rather than a live merge. Their exact composition passes the
authoritative validator at 126 sources, 500 capabilities, 55 families, and 47
discrepancies with zero aggregate or acceptance gaps. The live 289-row files,
live oracle migration, and candidate runtime qualification remain separate.

`metadata_sets/` now resolves the complete metadata plane as one immutable,
hash-bound snapshot. The selector defaults to the registered 500 set under
`qualification/live-metadata-500-migration/`, including a compact strict v2
oracle schema and exact 289+211 registry. The activation receipt under
`qualification/live-metadata-500-activation/` binds the descriptor's
`live_ready` promotion, selector switch, fixed 289 prerequisites, and rollback.
The historical 289 set remains explicitly resolvable. Neither metadata
selection nor `live_ready` promotes any capability runtime state.

Validate either atomic set through the authoritative dispatcher:

```bash
python3 deploy/docker/thor-local/parity/verify_metadata_set.py --json
python3 deploy/docker/thor-local/parity/verify_metadata_set.py \
  --set thor-vss-3.2.1-live-289 --json
```

That direct-index denominator is also not the final documentation graph. A
recursive same-version follow-up reached a 172-page fixed point (including
`index.html`) and found 19 additional Warehouse descendant pages outside the 152
direct-link set. All 19 are now classified: eight claim-bearing semantic pages
are represented in the merged ledger, nine external workflows remain explicit
boundaries, and two navigation/reference pages remain non-claim receipt entries.
The exact URL set, 26,449-edge crawl graph, depth/frontier proof, and 8 semantic /
9 external-workflow / 2 navigation classification are pinned under
`candidates/wave3/recursive-coverage/`. The 152-page direct-index package must
not be described as whole-site coverage.

`official-capabilities.schema.json` documents the on-disk format. The validator
requires every reviewed claim to be cross-linked from exactly one manifest
family and from an acceptance scenario. Its per-source hashes protect the
locally reviewed claim sets; they do not content-pin or re-fetch NVIDIA's remote
HTML. Adding a claim without an explicit status, gap, scenario, and blocker
therefore fails the normal parity verifier. A generic plan-only scenario records
an open gap, not capability-specific runtime acceptance.

`source-lock/` separately records raw response-body SHA-256 metadata for the exact
172-page recursive VSS 3.2.1 HTML fixed point, including the index. The live ledger
and Wave 2 attach provenance but do not define or expand that allowlist. Its offline
validator is part of the unified static wrapper. A byte match detects page drift
only; it is not proof that extraction is semantically correct or that Thor
implements the claim. See
[`source-lock/README.md`](source-lock/README.md) for validation and deliberate
network-refresh commands.

`candidates/wave3/bundle/` is the planning-only merge contract for those three
reviewed candidate families. It binds their exact bytes, resolves duplicate and
conflicting source IDs, preserves both approved multi-package enrichments, and
rejects unplanned capability or fixture collisions. Its deterministic merge
expanded the published 161-capability baseline to 276 live capabilities and 45
explicit discrepancies. The candidate registry has
140 unique source URIs; 126 claim-bearing sources are live and exactly 14
navigation/summary/legal/no-independent-claim pages remain receipt-recorded
exclusions. The receipt accepts only the pinned baseline or the exact wholly
merged outputs; partial or co-tampered states fail. The manifest now contains 55
families and 500 advertised entries. These are static review counts, not
runtime-qualified counts. The optional Warehouse sample bundle remains excluded,
while operator custom media, calibration, model, and configuration inputs remain
in scope.

The claim-level ledger is not yet a literal one-row-per-advertised-string
denominator. Of the 500 advertised strings, 289 have exact capability-title and
oracle mappings: 13 canonical `manifest-entry.*` rows plus 276 pre-existing
capability rows. Another 74 are enumerated in the empty/partial-family gap plan,
while 137 still have family-only planning bindings. Those 211 entries without
exact mappings block literal feature-completeness.

`remaining-advertised-entry-candidates/` now provides a reviewed candidate row
for every one of those 211 blockers. Its deterministic in-memory projection is
a schema-valid 500-capability ledger with one exact same-family title mapping
per advertised string. This is a merge candidate, not the live ledger and not
runtime evidence; official counts remain 289 until a separate successor merge.

Three candidate-only inputs now make that successor mechanically representable:
`candidate-oracle-adapter/` translates all 211 exact semantic plans while
locking the current 289 oracle states and evidence; `protocol-cases-v2-candidates/`
preserves the seven live protocol cases and adds 23 non-activating planning
cases; and `remaining-entry-workloads/` defines exact bounded workloads for the
41 API and 19 deployment candidates. None changes the live denominator or
claims Thor runtime qualification.

A first current-ledger successor added the exact CPU multimedia advertised entry
as capability 277. The tooling-entry successor then added eight exact Spatial
AI utility entries and four exact Synthetic Data tool entries as capabilities
278 through 289. The four Synthetic Data entries have exact current target-bound
offline receipts. Two MV3DT configuration utilities and three core SpatialAI
utilities now have exact executor-ready bindings; the remaining SpatialAI
utilities stay unqualified or external-optional. The Warehouse sample bundle
remains excluded.

Every source must back at least one precise claim. Core API/MCP claims also bind
the checked-in operation manifests by repository path, exact SHA-256, and
operation/tool count. This prevents a documentation URL or a stale aggregate
count from being treated as operation-level coverage.

`capability-oracles.json` expands every reviewed capability into a unique
record with exact ledger semantics, scenario identity, fixture identity,
observations, assertions, work bounds, admission gates, and mutation ownership.
Nine oracles are `executor_ready`: four Synthetic Data, two MV3DT configuration
utilities, and SpatialAI core entries 01, 04, and 05. The other 280 entries
remain `planning_index_only`. The three SpatialAI rows bind their locked tiny
fixtures and offline executor/collector/cleanup path, but remain
`open_unexecuted` with empty evidence; the SpatialAI ledger and family runtime
state are unchanged. Twenty-seven live planning bindings cover bounded
file-only subsets, and the two MV3DT generator oracles additionally bind their
deterministic custom-data tool observations from
`../qualification/offline-mv3dt-tools/`. All 29 subset bindings are explicitly
non-advancing. The seven planned modes are static, config, runtime, API,
protocol, model, and deploy.

`../qualification/static-cases/` is an isolated first tranche of 24 bounded
static observations. Its inventory, generated calibration fixtures, and tests
are part of the unified static wrapper, but every case remains `candidate_only`,
`executor_ready: false`, and unable to advance a capability. Current outcomes
are diagnostic observations rather than runtime evidence.

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

Runtime-evidence references support two fail-closed forms. Existing direct
receipts retain the exact `{path, sha256}` reference. An aggregate receipt uses
exactly `{path, sha256, capability_id, json_pointer}`, where the pointer is
restricted to `/capability_results/<index>` and must select the named enclosing
ledger capability. Aggregate validation checks the full raw-file digest and
deep aggregate/result shape, clean non-development promotability, exact
confinement and cleanup accounting, recomputes the outer runtime-evidence
binding, and then validates the selected nested official receipt through the
same canonical oracle verifier. It also resolves the recorded checkout commit
and tree and hashes the executor, contract, oracle document, fixtures, and every
contract source-control blob from that historical commit. Promotion therefore
does not require current `HEAD` to remain at the capture commit, but trusted
booleans or a shallow nested receipt cannot substitute for captured provenance.

The seven non-REST protocol planning records additionally bind the exact
[`protocol-cases.json`](../qualification/protocol-cases/protocol-cases.json)
whole-file and internal-set hashes, matching case and vector IDs, target commit,
and every source content/blob hash. The standalone protocol validator remains
static-only; all seven cases are unexecuted. Future executor evidence must
repeat those bindings and a passing cleanup result.

`candidates/wave2/` preserves the reviewed extraction provenance for the 30
capabilities, 9 enrichments, and 14 discrepancy/boundary records now merged
into the published 161-capability Wave 3 baseline. Its validator accepts only a wholly
unmerged or wholly merged lifecycle and rejects partial application. The live
ledger deduplicates four same-URI sources and requires at least two structured
source/locator/claim observations for every discrepancy, including two claims
within a single NVIDIA page.

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
