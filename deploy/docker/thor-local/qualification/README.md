# Thor-local API qualification

This directory owns the machine-readable, static acceptance contracts for the
Thor-local VSS profile. The core API inventory is intentionally incomplete
until every official auxiliary surface has an authoritative server contract;
supplemental packages below preserve those boundaries explicitly. The default
qualification is deliberately safe to run on an offline operator host: it
reads only checked-in files, does not inspect secrets, does not open sockets,
and never starts, stops, or mutates containers or VSS resources.

The broader parity program also keeps planning and admission boundaries
in this directory:

- `source-contract-integration/` replays the immutable ten-case receipt and
  executes the next sixteen cases against that reconstructed state before
  binding them into live planning acceptance;
- `lvs-mcp-static-adapter-integration/` is the third static successor. It
  preserves the pinned upstream 13-versus-9 discrepancy while recording the
  four Thor-local file-management adapters, with zero runtime evidence;
- `extended-api-surface-contracts/` splits the five excluded official API
  groups into seven addressable REST surfaces. It locks six exact descriptors
  totaling 80 operations and keeps legacy calibration authoritative-unknown
  with only a 14-operation client lower bound, so complete-product API totals
  remain deliberately unresolved;
- `advertised-entry-executors/` gives 8 of the 87 literal advertised-entry
  gaps bounded, source-locked candidate observations while leaving live state
  and the other 79 entries untouched;
- `advertised-entry-executors-wave2/` adds 21 disjoint helper/source-contract
  candidates, bringing isolated advertised-entry coverage to 29 of 87 while
  leaving 58 entries explicitly open;
- `advertised-entry-executors-wave3/` adds 23 code-locked source/API-shape
  candidates, bringing isolated advertised-entry coverage to 52 of 87 while
  leaving 35 without a candidate executor; all 87 remain unpromoted in live
  official status;
- `advertised-entry-executors-wave4/` adds five cross-layer AST/configuration
  candidates for the remaining LVS live-caption, stream-summary, report, Q&A,
  and Elasticsearch-storage literals, bringing isolated candidate coverage to
  57 of 87 while leaving 30 without a candidate executor. It performs no live
  request, storage operation, or official-state promotion;
- `advertised-entry-executors-wave5/` adds six digest-locked VIOS codec/audio
  source and offline-package candidates for B-frames, HEVC multislice/RFC7798,
  H.264/H.265, audio record/republish, and CPU multimedia support. Isolated
  candidate coverage reaches 63 of 87 while 24 lack a candidate; no codec
  fixture, RTSP session, recording, CPU pipeline, or official-state promotion
  occurs;
- `planning-requirement-executors-wave3/` checks six of the 84 still-open
  planning requirements without promoting them, preserving five source
  matches and the search-upload HTTP 400/415 mismatch;
- `planning-requirement-executors-wave4/` checks six of the 78 previously
  unselected open requirements, preserving five matches and the missing Alerts
  Qwen example as a source-contract mismatch;
- `planning-requirement-executors-wave5/` checks six Smart City contracts from
  the exact 72-requirement successor denominator. It preserves one source match
  and five explicit source gaps, leaves 66 requirements without a candidate,
  and keeps all 84 live-open planning requirements unpromoted;
- `service-binding-resolution/` proves why four capability contracts do not
  yet select unique runtime participant sets and forbids guessed lane updates;
- `runtime-lanes/` binds every manifest-advertised entry and capability oracle
  to a bounded execution lane without manufacturing runtime evidence;
- `offline-mv3dt-tools/` executes the two custom-data MV3DT configuration
  utilities twice against a tiny synthetic two-camera calibration, locking
  schema, matrix, camera-ID, MQTT-topology, determinism, confinement, and
  cleanup observations. It uses neither the Warehouse sample nor Docker,
  models, cloud inference, network, or service lifecycle, and remains
  candidate-only;
- `advertised-entry-gaps/` gives each advertised entry from the 16 families
  that lack capability rows its own still-open semantic oracle plan;
- `host-preflight/` defaults to an inert plan and offers a separately explicit,
  read-only Thor host inspection;
- `host-prerequisite-evidence/` binds exactly four platform prerequisite
  oracles to an inert-by-default, acknowledgement-gated, sanitized read-only
  collector. Its static wrapper runs only the plan and mocked tests; it neither
  emits a live evidence record nor qualifies an application feature;
- `host-cgroupfs-remediation/` provides an inert-by-default, exact-acknowledgement
  transaction for preserving Docker daemon settings, switching only the native
  cgroup driver, and restoring exactly the previously running container set.
  Static qualification exercises only its mocked plan/rollback/recovery suite;
  no host mutation or Docker restart is performed;
- `official-edge-readiness/` fixes the exact Nemotron/Cosmos identities,
  source-locks all staging gates, and offers a separately acknowledged,
  allowlisted read-only inspection that cannot claim runtime qualification;
- `prerelease-watchlist/` isolates a curated watchlist from the divergent VSS
  3.3.0 development line as fourteen selected candidate-static families backed
  by forty exact remote source pointers. It has no authoritative full-diff
  denominator and makes no exhaustive-coverage claim. It requires no network
  or local development checkout, preserves the stale Thor Edge 4B recipe as a
  conflict, keeps the Warehouse sample excluded, and cannot promote stable/live
  qualification state;
- `prerelease-denominator/` complements that curated watchlist with exhaustive
  Git-metadata accounting for the exact locked divergence: all 498 develop-side
  commits, 109,052 develop path/status records, and two main-only exceptions.
  This is commit/path exhaustiveness, not feature-semantic completeness, local
  implementation, or runtime parity; and
- `local-alternate-models/` defines an exact-acknowledgement, four-request
  qualifier for the non-official local Qwen endpoint pair.

The optional NVIDIA Warehouse sample bundle is excluded throughout. Small
operator-owned custom media and calibration remain valid inputs for the
Warehouse capability lanes.

The core API inventory remains at 17 surfaces, 327 declared REST operations,
326 normalized REST operations, 42 MCP tools, and five MCP prompts. The
separate extended contract proves 80 more operations across six surfaces and
keeps the seventh, legacy calibration, at `L >= 14` rather than inventing an
exact server count. Complete REST totals therefore remain `407 + L` declared
and `406 + L` normalized; the defensible lower bounds are 421 and 420, not
complete totals.

The first two deterministic static successors currently materialize 26 of 110
planning requirements. All 276 full capability oracles remain
`planning_index_only`; the 26 bindings are static subsets only, with zero
runtime evidence and zero `passed_current` promotions. The third successor
updates only the LVS adapter's static API contract and does not materialize an
additional planning requirement. The separate 8 + 21 + 23 + 5 + 6
advertised-entry candidates and 6 + 6 + 6 additional planning checks are
non-advancing and do not change those live counts. They leave 24
advertised entries without a candidate source executor and 66 planning
requirements not yet selected by a planning executor package, respectively.
The prerelease packages are separate from these stable 3.2.1 denominators. The
fourteen-family watchlist remains pointer-only; the adjacent exact diff package
proves that every commit and path/status in the locked prerelease range was
considered, but does not prove that a classifier captured every feature meaning.
Neither adds official capabilities, runtime evidence, or `passed_current`
results. The two offline MV3DT observations likewise leave their official
capability/oracle states unchanged while proving that the checked-in
repository tools execute deterministically on Thor with custom data.

Run the contract tier from the repository root:

```bash
deploy/docker/scripts/thor-local.sh qualify --tier contract
```

For machine-readable output:

```bash
python3 deploy/docker/thor-local/qualification/qualify.py \
  --tier contract --json
```

`api_inventory.json` records the 17 enumerated core REST/MCP surfaces, direct
and public route exposure, source provenance, release conditions, expected
counts, and reviewed contract differences. The seven auxiliary surfaces are
accounted for separately in `extended-api-surface-contracts/` until the legacy
server denominator is authoritative. `expected/*.json` is the reviewed core
acceptance baseline. The qualifier independently re-derives manifests from:

- OpenAPI JSON for Alerts and Video Analytics;
- all seven VIOS Swagger documents;
- Python route decorators for RT-VLM, RT-Embed, and LVS;
- the RT-CV API reference;
- the pinned NAT 1.6.0 route model plus VSS Agent config/source routes; and
- VA/LVS MCP declarations; and
- the VST/VIOS FastMCP gateway's 22 tools and five prompts.

OpenAPI prose such as descriptions and examples is ignored. Its validation
shape, method, path, operation ID, and component definitions are retained.
The VIOS Swagger extractor retains route metadata and a whole-file digest, so
schema changes still fail qualification without requiring PyYAML on an offline
host. VIOS paths are normalized to their deployed `/vst/api/v1/...` form.
Parameter names are normalized separately when finding runtime route
collisions.

MCP manifest schema version 2 records tools and prompts independently. For
FastMCP source, the qualifier parses top-level `@mcp.tool` and `@mcp.prompt`
decorators with Python's AST and hashes the function signature that derives
each input schema. It never imports the server module, so settings and backend
clients cannot create side effects during offline qualification. The complete
source-file hashes continue to protect decorator metadata and handler bodies.

Upstream includes the VST/VIOS MCP Python service and both stdio and
streamable-HTTP entry points but omits it from the released Compose graph.
Thor closes that packaging gap with a checksum-locked Linux/AArch64 wheel
closure, an exact Python base-image digest, a networkless derivative build,
and a read-only, loopback-only Compose service on `VST_MCP_PORT` (8001 by
default). Its direct `/mcp` endpoint is listed in `runtime_inventory.json`;
the static contract still derives all 22 tools and five prompts from source
without importing the service.

## Locally captured live documents

The helper can compare a previously captured local OpenAPI JSON document
without making a network request:

```bash
python3 deploy/docker/thor-local/qualification/qualify.py \
  --live-openapi alerts=/tmp/alerts-openapi.json
```

URLs are intentionally unsupported here. The separate runtime tier below owns
loopback HTTP/MCP collection without weakening this contract tier's offline
guarantee.

## Read-only runtime qualification

`runtime.py` is isolated from the offline qualifier above. Run it only after
the operator has started the Thor-local stack:

```bash
deploy/docker/scripts/thor-local.sh qualify --tier runtime
```

The wrapper supplies the same Thor-local port defaults and environment
overrides as the deployment. Running `runtime.py` directly remains supported
for isolated tests.

It always emits JSON. A readiness response or live OpenAPI contract failure
produces `result: "fail"` and exit 1. A connection refusal, timeout, or other
transport outage produces `result: "unavailable"` and exit 2, making a stopped
stack distinguishable from a broken contract without treating it as a pass.
An OpenAPI endpoint marked optional is skipped only when it returns 404 or 405.
`runtime_inventory.json` defines the health, OpenAPI, MCP, UI, ingress,
VIOS, VIOS MCP, Elasticsearch, Kibana, Phoenix, Logstash, Prometheus, Grafana,
node-exporter, cAdvisor, and the Thor `tegrastats` exporter GET probes and their
default Thor-local ports. A valid port environment variable listed there
overrides its default. The deployment contract requires `TEGRASTATS_PORT=19101`
so the loopback-only exporter and checked-in Prometheus target cannot drift.

The Prometheus target probe is stronger than endpoint reachability: it reads
the bounded `/api/v1/targets` JSON document and requires the exact versioned
Thor job set (`prometheus`, `node-exporter`, `cadvisor`, `rtvi-vlm`,
`rtvi-embed`, `lvs`, and `tegrastats-exporter`) to be present once each with
`health: up`. Its report contains counts and a drift fingerprint, never live
scrape URLs or response bodies. The Grafana tier also requests the provisioned
`thor-vss-observability` dashboard by its checked-in UID.

The host-managed LLM and VLM intentionally bind to Docker's private bridge,
not loopback, so this loopback-only tier does not contact them directly. Use
the separate read-only `deploy/docker/scripts/thor-local.sh model-check`
contract once both local model containers are running.

## Explicit stateful canary

The default stateful acceptance command is an inert compiler:

```bash
deploy/docker/scripts/thor-local.sh acceptance plan
```

An explicitly opted-in Phase-1 canary exercises only client-addressed file
create/read/content/delete lifecycle on the loopback RT-VLM and RT-Embed APIs.
It never starts or stops containers and all other planned REST, MCP, profile,
UI, stream, inference, and external actions remain blocked. See
[`ACCEPTANCE.md`](ACCEPTANCE.md) for the approval token, private evidence
directory, exact source-fingerprint acknowledgement, crash recovery, and
fake-loopback test contract.

For tests or a deliberately remapped local port, override an origin explicitly:

```bash
python3 deploy/docker/thor-local/qualification/runtime.py \
  --endpoint agent=http://127.0.0.1:18100
```

Only numeric IPv4/IPv6 loopback HTTP origins are accepted. The qualifier
disables ambient proxies and redirects, issues only GET requests, never calls
Docker or another process, never invokes an MCP tool, and never creates,
updates, or deletes a VSS resource. Error output contains stable categories,
HTTP status codes, counts, and drift fingerprints; response bodies, redirect
locations, raw exceptions, and live route names are not included.

## Updating a reviewed contract

After reviewing a deliberate upstream API change, regenerate expected files:

```bash
python3 deploy/docker/thor-local/qualification/qualify.py --regenerate
git diff -- deploy/docker/thor-local/qualification
python3 deploy/docker/thor-local/qualification/qualify.py
```

Never regenerate merely to make a failure disappear. Review every added,
removed, or changed operation/tool and update `api_inventory.json` counts and
known differences explicitly.
