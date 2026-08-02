# Thor-local API qualification

This directory owns the machine-readable, static acceptance contracts for the
Thor-local VSS profile. The core API inventory is intentionally incomplete
until every official auxiliary surface has an authoritative server contract;
supplemental packages below preserve those boundaries explicitly. The default
qualification is deliberately safe to run on an offline operator host: it
reads only checked-in files, does not inspect secrets, does not open network
sockets, and never starts, stops, or mutates containers or VSS resources.

The broader parity program also keeps planning and admission boundaries
in this directory:

- `source-contract-integration/` replays the immutable ten-case receipt and
  executes the next sixteen cases against that reconstructed state before
  binding them into live planning acceptance;
- `lvs-mcp-static-adapter-integration/` is the third static successor. It
  preserves the pinned upstream 13-versus-9 discrepancy while recording the
  four Thor-local file-management adapters and two bounded offline MV3DT tool
  observations, with zero runtime evidence or full-oracle promotion;
- `calibration-schema-static-integration/` is the fourth static successor. It
  replays the LVS predecessor and integrates one exact non-advancing binding
  for `calibration.schema.vss-json`, preserving the global-vector owner and six
  explicitly uncovered applicable records with zero runtime evidence;
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
- `advertised-entry-executors-wave6/` checks seven VIOS UI literals plus NAT
  generate/chat against exact source, route, static-operation, dependency, and
  predecessor locks. Its wave-local sequence reaches 71 of 87 and leaves 16;
  empty UI route placeholders and all browser/API runtime work remain open;
- `detection-map-static-executor/` adds a separate candidate for the detection
  mAP literal. It executes a tiny deterministic AP semantic oracle while
  preserving the missing local production-evaluator dependency stack, so it
  creates no runtime evidence or official-state promotion. Together with Wave
  6 this brings aggregate candidate coverage to 72 of 87 and leaves 15;
- `advertised-entry-executors-wave7/` partitions those final 15 entries into
  11 digest-locked source/provenance candidates for search scale, Sparse4D,
  MV3DT, and audio, plus four explicit external-attestation blockers for
  Slack, AWS/GCS, RAG report generation, and FRAG retrieval. Aggregate
  candidate coverage is 83 of 87; all runtime, model, scale, custom-data, and
  external delivery/retrieval oracles remain open;
- `advertised-entry-executors-wave8/` upgrades the SSE-MCP-server and LVS-MCP
  entries with a non-advancing in-process execution of the production LVS MCP
  server: all 13 tools register and bounded health/file operations run through
  deterministic fakes. Live SSE/MCP transport, a deployed service, VLM
  inference, Thor runtime evidence, and official promotion remain open;
- `cpu-multimedia-ledger-successor/` preserves the published `0c9a0a3`
  predecessor instead of relabelling its 87-gap-era evidence. Read-only local
  Git object checks lock all eight advertised-entry wave trees, four Wave 3
  candidate/bundle trees, two static-integration receipt trees, the immutable
  offline-MV3DT candidate observation, and Planning Waves 5-12, then prove that
  only the CPU multimedia gap left the current plan, becoming
  capability/oracle 277 while staying runtime-unqualified and evidence-empty;
- `spatial-ai-entry-static-contract/` and
  `synthetic-data-entry-static-contract/` bind the exact checked-in source and
  CLI surfaces for the twelve newly canonical tooling entries. They are
  deterministic static contracts only and create no Thor runtime evidence;
- `tooling-entry-ledger-successor/` freezes the CPU-multimedia predecessor and
  proves that only those twelve tooling entries leave the advertised-entry gap
  plan, becoming capabilities/oracles 278 through 289 without promotion;
- `exact-title-entry-mapping-successor/` freezes that tooling successor at the
  published `76596c` predecessor, then proves that all 289 existing capability
  titles have one exact same-family advertised entry and bound oracle. It
  changes only the mapping denominator from 13/487/413 to 289/211/137;
- `external-entry-attestations/` turns those exact four blockers into an inert,
  credential-free collection plan and strict validator for a future sanitized
  operator receipt. Source or mocks never count as delivery; Slack and
  Enterprise RAG remain external-optional, while AWS/GCS requires actual
  provider identity rather than local-emulator equivalence. Validation alone
  cannot promote any official state;
- `search-scale-qualification-plan/` compiles the two still-open Search scale
  literals into an inert progressive 2/4/8/16 plan and a separate,
  operator-approved 100-stream plan. It requires one future digest-locked
  operator H.264 source, exact per-stream identities and evidence, a strict
  1920x1080 gate for the 16-stream claim, resource aborts, and exact-owned
  cleanup, but executes no publisher, API, container, or runtime workload;
- `planning-requirement-executors-wave3/` checks six of the 83 still-open
  planning requirements without promoting them, preserving five source
  matches and the search-upload HTTP 400/415 mismatch;
- `planning-requirement-executors-wave4/` checks six of the 77 previously
  unselected open requirements, preserving five matches and the missing Alerts
  Qwen example as a source-contract mismatch;
- `planning-requirement-executors-wave5/` checks six Smart City contracts from
  the exact 71-requirement successor denominator. It preserves one source match
  and five explicit source gaps, leaves 65 requirements without a candidate,
  and keeps all 83 live-open planning requirements unpromoted;
- `planning-requirement-executors-wave6/` checks six more Smart City source
  contracts from that exact 65-requirement remainder. It preserves five
  documented mismatches and one external-optional boundary, leaves 59
  requirements without a planning candidate, and keeps all 83 live-open;
- `planning-requirement-executors-wave7/` audits that exact 59-requirement
  remainder and adds six disjoint source subsets: three preserved negative
  contracts, two configuration implementations, and one illustrative NvSchema
  consumer/protocol subset. It leaves 53 without a planning candidate and all
  83 live-open requirements unpromoted;
- `planning-requirement-executors-wave8/` audits that exact 53-requirement
  remainder and adds six disjoint preserved negative contracts for LVS, CR2
  recovery, Search, and ended-stream deletion. It leaves 47 without a planning
  candidate and all 83 live-open requirements unpromoted;
- `planning-requirement-executors-wave9/` audits that exact 47-requirement
  remainder and adds six disjoint bounded subsets: one preserved negative
  contract, two configuration-only observations, and three protocol/source
  surfaces. It leaves 41 without a planning candidate and all runtime semantics
  and all 83 live-open requirements unpromoted;
- `planning-requirement-executors-wave10/` audits that exact 41-requirement
  remainder and adds six disjoint bounded subsets for agent routing, UI chat
  state, Smart City model/configuration boundaries, NvStreamer file protocol,
  and the VA query library. It leaves 35 without a planning candidate, excludes
  every Warehouse row, and keeps all 83 live-open requirements unpromoted;
- `planning-requirement-executors-wave11/` audits that exact 35-requirement
  remainder and adds six disjoint bounded subsets for Kibana, alert workflow
  and persistence, Behavior Analytics, and LVS queue/format surfaces. It leaves
  29 without a planning candidate, selects no Warehouse row, and keeps all 83
  live-open requirements unpromoted and runtime-evidence-empty;
- `planning-requirement-executors-wave12/` audits that exact 29-requirement
  remainder and adds six disjoint bounded subsets for Search documents and
  bounding boxes, real-time alerts, the three UI surfaces, and alert-worker
  scaling. It leaves 23 without a planning candidate, selects no Warehouse row,
  and keeps all 83 live-open requirements unpromoted and evidence-empty;
- `ui-runtime-contracts/` binds the three still-open Alerts, Search, and video-
  management UI rows to a strict future browser/API evidence shape. Its inert
  compiler and offline validator require a separate UI origin plus three mock
  APIs on distinct numeric-loopback ports, locally generated tiny fixtures,
  rendered DOM/actions and sanitized browser artifacts, bounded exchanges, and
  exact-owned cleanup. There is no executor; API mocks alone are non-admissible
  and no live state can advance;
- `runtime-execution-bounds-audit/` derives exact minimum envelopes for the 20
  non-Warehouse rows still needing local runtime evidence. It proves every
  generic two-request budget is inadequate, locks 202 minimum requests and 207
  atomic actions, and verifies those bounds are now integrated into the
  canonical oracle plan without changing any official state or evidence;
- `local20-fixture-pack/` supplies strict candidate-input contracts for nine of
  those rows: four tiny MP4/MKV/B-frame media recipes plus four embedded JSON
  fixtures for HITL, Search/bboxes, Alerts/Smart City tracks, and VIOS
  remediation. Static validation is read-only; optional media generation is
  separately acknowledged, outside-repository, local-FFmpeg-only, bounded to
  8 MB total, and still non-promoting;
- `architecture-gap-contracts/` freezes the four implementation boundaries
  that cannot be qualified from current configuration: native legacy manual
  and provider-free GIS calibration, replica-safe Alert workers, and scalable
  VIOS stream processing with a singleton Sensor. It source-locks the current
  blockers, rejects false equivalences such as AMC=legacy or `num_workers`=
  horizontal scaling, and defines future decision/acceptance receipt shapes;
- `../legacy-calibration/` is the first functional clean-room calibration
  slice: bounded provider-free Cartesian/image/GIS/multi-camera project
  validation, pure-Python 3x3 homography solving, eight-point
  ROI/tripwire/road-link validation, strict consumer-schema-compatible export,
  and a strict path/method-named loopback adapter. A separate inert VIOS-client
  compatibility server on private port 8013 implements bare numeric project
  CRUD, partial sensor updates, persisted homography, bounded multipart image
  storage/serving, staged local sensor import, and optional loopback CORS.
  Route/nav and same-origin proxy wiring, four transform/ZIP/upload endpoints,
  the UI-state-to-strict-export bridge, official Google Maps identity, and
  Thor runtime proof remain open;
- `calibration-schema-static-executor/` materializes the exact
  `calibration-schema-static` planning subset without advancing its capability:
  four
  generated geo/cartesian/image/MTMC projects are exported twice, checked
  against all exact VSS calibration/Behavior/Road schemas, subjected to seven
  adjacent invalid cases, read back, confined, and cleaned deterministically;
- `fixed-topology-scaling-config/` statically qualifies an opt-in, default-one
  Alert worker and VIOS stream-processor scaling topology while keeping VIOS
  DB/Redis/Sensor/ingress singletons. It does not run Compose or claim Kafka
  partitioning, image/network compatibility, Thor capacity, failure recovery,
  RTSP ownership, or live cleanup;
- `services/alert/utils/schema_util.py` now preserves the documented NvSchema
  Incident field-7 name `analytics` by conflict-safely mapping it to the
  released wire binding `analyticsModule`; the Thor Alert derivative installs
  that converter and focused tests prove deterministic protobuf roundtrip;
- `systems-alert-completion-static-executor/` binds three remaining Alert
  systems planning rows to actual DirectMedia, NvSchema/protobuf, sink receipt,
  and terminal job-store behavior with deterministic external-client fakes and
  adjacent negatives. It creates no runtime evidence and advances no canonical
  planning, capability, or oracle state;
- `systems-behavior-analytics-static-executor/` binds all six Behavior
  Analytics systems rows to real config, calibration, event/state, embedding,
  and broker-sink product subsets. External constructors and transports are
  replaced by fail-closed or in-memory fakes; full media, listener/watcher,
  broker, deployment, and Thor runtime evidence remain explicit blockers;
- `systems-nvschema-json-static-executor/` executes the real Behavior legacy
  2D JSON-to-Protobuf converter, Spatial AI modern 3D JSONL loader, and agent
  incident aliases for the open NvSchema systems row. It preserves two
  observed consumer limitations, creates no runtime evidence, and advances no
  canonical state;
- `systems-search-lvs-boundary-static-executor/` executes three remaining
  Search/LVS systems subsets and deliberately reports a candidate mismatch:
  unsupported Search media returns 415 rather than the canonical 400, the
  isolated LVS handler does not demonstrate one-active/one-queued behavior,
  and AVI/MOV/WebM remain outside the default UI admission path and unproven at
  runtime. No mismatch is normalized into a pass;
- `headline-cosmos-smartcity-static-executor/` binds the two Cosmos3 Nano
  headline model records and the Smart City version-skew record to their exact
  canonical oracles. It executes only byte-locked file/config checks, preserves
  all three `not_qualified` runtime states, and leaves model staging/inference
  plus Smart City component-digest/runtime evidence open;
- `official-vss-doc-drift-observation/` preserves the immutable July 31
  172-page, 26,449-edge source lock while recording the reviewed August 1
  aggregate drift: all raw hashes changed, but every page size, the URL set,
  and graph topology matched. August bodies/hashes are unavailable, so semantic
  equality remains explicitly unproven and no source lock is relabelled;
- `runtime-evidence-common/` provides reusable fail-closed primitives for
  future authorized collectors: numeric-loopback/exact-path transport through
  an injected proxy/redirect-disabled opener, independent request/action
  budgets, exact run/authorization binding, exact-owned LIFO cleanup, pre/post
  digests, and sanitized evidence. Its CLI is limited to a static check and an
  in-memory fake self-test; it constructs no opener and performs no live I/O;
- `candidate-alerts-runtime-evidence/` is the first bounded consumer of those
  primitives: an inert plan and fake-only tests bind one alert workflow to an
  exact eight-request/eight-action future collector. Even an authorized run is
  non-promoting because final background VLM verdict, sink delivery, fixture
  identity, and media digest remain outside this collector;
- `candidate-alerts/` is the offline completion scaffold for those missing
  observations: two digest-bound confirmed/rejected descriptors, exact future
  media/server/run identity, a 53-request/56-action ES lane, terminal ES/Kafka
  delivery receipts, strict query construction, proof-gated LIFO ownership,
  and an explicit late-publication blocker. It has no execute path and remains
  non-promoting until media, terminal/cancel APIs, durable sink receipts,
  bounded transport integration, and live runtime identity exist;
- `search-documents-bboxes-runtime-evidence/` binds the Search agent requirement
  to an exact 14-step/14-request/14-action future workflow and validates a
  strict plain-JSON fake transcript. The CLI exposes no execute mode or live
  adapter; exact official `/api/v1/search/{attribute,fusion,image}` route gaps
  and the missing selected-bbox image payload remain explicit blockers;
- `service-binding-resolution/` proves why four capability contracts do not
  yet select unique runtime participant sets and forbids guessed lane updates;
- `runtime-lanes/` binds every manifest-advertised entry and capability oracle
  to a bounded execution lane without manufacturing runtime evidence;
- `offline-mv3dt-tools/` executes the two custom-data MV3DT configuration
  utilities twice against a tiny synthetic two-camera calibration, locking
  schema, matrix, camera-ID, MQTT-topology, determinism, confinement, and
  cleanup observations. It uses neither the Warehouse sample nor Docker,
  models, cloud inference, network, or service lifecycle. Its two observations
  are bound only to exact non-advancing oracle subsets; both full oracles remain
  open;
- `mv3dt-entry-oracles/` converts the four remaining MV3DT advertised-entry
  semantics into an exact-four, operator-data-only admission plan and a strict
  read-only candidate-receipt validator. It requires per-camera `mdx-raw`
  detections, linked `mdx-bev` fusion, distinct BodyPose load/use observations,
  calibrated cross-camera continuity, and exact-owned cleanup while retaining
  all four official oracles as `open_unexecuted`;
- `sparse4d-entry-oracles/` binds the two remaining Sparse4D literals to the
  existing custom-data validator and prepare/preflight/qualify lane without
  invoking it. Its future candidate-receipt contract requires exact four-camera
  input, RT-DETR and Sparse4D/anchor identities, model load/use observations,
  fused 3D/BEV semantics, health/latency/resources, and exact-owned cleanup;
  missing assets, custom data, admission gates, and runtime evidence remain
  explicit blockers;
- `tiny-audio-fixture/` provides an inert-by-default, acknowledgement-gated
  generator and read-only verifier for a six-second known-speech H.264/AAC
  candidate. It uses only local FFmpeg/FFprobe and publishes only the explicit
  new media path and its adjacent receipt outside the repository. A private
  transient work directory is removed non-recursively; the package claims no
  VSS, model, ASR, summary, or alert runtime evidence;
- `audio-entry-oracles/` binds that fixture to strict future candidate evidence
  for the three audio literals. It keeps native Omni Base/summary/alert
  semantics separate from a real local-ASR run for per-chunk transcript,
  enforces model, loopback, phrase/control, timing, memory-reserve, resource,
  artifact, and cleanup gates, and explicitly rejects native-audio ASR-skip as
  transcript proof. Its validator still returns only `not_admitted`;
- `runtime-approval-bundles/` is the immutable historical 14-scope approval
  predecessor. Its scopes remain explicit, inert, and non-inheriting;
- `candidate-approval-mapping-successor/` is the immutable historical v1
  classification of all 211 Metadata-500 candidates: 206 mapped, three static
  and non-activating, one contract conflict, and one approval-scope gap;
- `runtime-approval-bundles-successor/` preserves that exact 14-scope prefix
  and appends separate physical-interface firewall inspection and configuration
  scopes. Both are inert and non-inheriting; the current firewall apply/remove
  path remains blocked pending a lossless transaction executor and receipt;
- `sparse4d-candidate-dependency-repair/` is an additive one-field planning
  overlay that replaces the objectively wrong MV3DT dependency with the
  existing Sparse4D pipeline. It does not modify selected Metadata-500 files,
  execute the Sparse4D lane, or use the Warehouse sample bundle;
- `candidate-approval-mapping-successor-v2/` consumes those two successors and
  preserves 209 historical rows while resolving exactly the Sparse4D and
  firewall classifications. Its current split is 208 mapped and three static,
  with zero contract conflicts or scope gaps. All 211 rows remain receipt-free,
  unapproved, not admitted, non-executable, and runtime-evidence-empty;
- `candidate-admission-receipts-successor/` source-locks those 211 ordered rows
  into an exact admission index and validates only the canonical empty receipt
  set. It distinguishes 204 local/alternate binding-blocked candidates, four
  external-only candidates that cannot establish Thor-local admission, and
  three static runtime-not-applicable entries. The compiler has no write,
  receipt-consumption, action, or execution mode; receipts, trusted roots,
  admissions, and executable candidates are all zero;
- `candidate-execution-binding-registry-successor/` binds the 208 mapped rows
  to exact semantic, planning-action, observer, and lane projections plus 261
  direct implementation/profile/Compose file locks. These projections remain
  explicitly non-authoritative: every executable action, service/profile,
  cleanup/rollback, postcondition, and evidence field is null or empty, and
  admission-grade bindings remain zero;
- `advertised-entry-gaps/` gives each still-unmapped advertised entry from the
  13 families with no capability rows plus the partial VIOS family its own
  still-open semantic oracle plan. Its 74-entry scope is not the global missing
  entry-specific denominator: 289 strings already have exact capability-title
  and oracle mappings, while 137 more retain family-only bindings;
- `advertised-entry-coverage/` compiles all 500 advertised strings into exactly
  one fail-closed mapping class: 276 exact pre-existing capabilities, 13 exact
  canonical entry capabilities, 74 explicit gaps, or 137 family-only unreviewed
  entries. It keeps all 211 semantic blockers and all runtime evidence at zero;
- `remaining-advertised-entry-candidates/` gives each of those 211 blockers a
  source-bound exact-title capability and future-oracle candidate. Its in-memory
  500-capability/500-exact-mapping projection satisfies the strict ledger
  schema, but the package is candidate-only and neither merges nor promotes it;
- `candidate-oracle-adapter/` translates all 211 candidate contracts into
  machine-usable planning-oracle seeds and separately locks the states and
  evidence arrays of all 289 live oracles. Every execution/materialization hook
  remains absent and no candidate is executor-ready;
- `protocol-cases-v2-candidates/` preserves the seven live protocol cases and
  adds 23 exact, non-activating planning cases with composite transport and
  locality boundaries. It does not change the live protocol executor;
- `remaining-entry-workloads/` replaces generic workload defaults for the 41
  API and 19 deployment candidates with 134 exact operation units and 58
  ordered actions. Its three external workloads remain zero-activation;
- `oracle-500-successor/` preserves the 289 live capability oracles exactly and
  appends all 211 candidate adapters in manifest-pointer order under a strict
  successor schema. It binds the exact protocol and workload candidates while
  keeping evidence, execution, readiness promotion, cloud inference, and the
  Warehouse sample at zero;
- `ledger-500-successor/` projects the live manifest and capability ledger to
  the same ordered 500 IDs with exact same-family title mappings. It preserves
  the 289 existing capability rows, recomputes only 17 derived source claim
  hashes, and records nine family-aggregate plus eight acceptance-coverage
  blockers; it does not change the live parity files;
- `manifest-500-aggregate-successor/` resolves the nine raw family-reducer
  differences into six policy-valid scalar updates plus three preserved
  `external_optional` family boundaries. Its projected manifest has zero
  policy-correct aggregate drift while leaving the eight acceptance links open;
- `acceptance-500-successor/` appends exactly those eight scenario links and
  proves that removing its eight surgical replacements reconstructs the live
  inventory bytes exactly. Its projected acceptance coverage has zero missing
  links while the separate live family metadata remains unmodified;
- `metadata-500-composition-successor/` binds all four 500-row metadata
  successors and runs the authoritative capability validator over their exact
  composition. It passes at 126 sources, 500 capabilities, 55 families, and 47
  discrepancies with zero aggregate or acceptance gaps, while retaining three
  explicit blockers for live metadata migration, live oracle-registry
  migration, and execution/evidence for the 211 candidate oracles;
- `live-metadata-500-migration/` materializes the exact five-file post-state
  without applying it: the settled ledger, manifest, acceptance inventory, and
  a live-root-shaped strict v2 oracle registry/schema. Its migration journal
  locks every before/after byte and rollback object while keeping all 211
  candidates non-executable, evidence-empty, and non-promoting. The staged set
  is registered with the atomic metadata-set resolver. Its additive v2
  validator and atomic bundle verifier pass;
- `live-metadata-500-activation/` binds and validates the exact metadata-default
  transaction: lifecycle-only promotion to `live_ready`, selector switch to
  the 500 set, unchanged fixed 289 prerequisites, zero candidate promotion,
  and exact rollback. The receipt compiler accepts only the complete pre-state
  or complete applied state and rejects partial activation. This selects the
  complete metadata inventory but does not qualify any runtime capability;
- `advertised-entry-executors-74-successor/` rebases the immutable historical
  Waves 1-7 inventory onto the current gap denominator: exactly 71 retained
  candidate rows, three external-attestation blockers, and a separate exact
  map for all 13 IDs migrated into the fixed live predecessor. All 71 retained
  rows dispatch through guarded, deterministic direct historical adapter
  functions with exact per-wave counts of 1/18/23/5/5/8/11; historical
  `execute()` and `main()` paths are never invoked. The checked receipt remains
  candidate-only, evidence-empty, and non-promoting, so this is bounded adapter
  evidence rather than runtime qualification;
- `successor-500-executable-subsets-wave1/` binds the two Wave 8 LVS/MCP
  production-code executable subsets to their exact selected Metadata-500
  oracle rows. It leaves the v2 oracle document byte-identical and records the
  subset observations in a separate hash-bound annotation index. Both rows
  remain `not_qualified`, executor-not-ready, approval-gated, and free of
  runtime evidence; SSE transport, MCP handshake, deployed LVS, inference, and
  Thor readiness remain explicit blockers;
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
  Git-metadata accounting for the exact locked divergence: all 499 develop-side
  commits, 109,058 develop path/status records, and two main-only exceptions.
  Its exact one-commit head delta records the post-nightly NemoClaw Hermes
  semantics as a develop-only watchlist item. Commit/path exhaustiveness plus
  that bounded semantic record is not complete feature-semantic coverage,
  local implementation, or runtime parity; and
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

The deterministic static successors currently materialize 27 of 110
planning requirements. All 289 full capability oracles remain
`planning_index_only`; those 27 planning bindings plus two offline MV3DT tool
bindings are static subsets only, with zero runtime evidence and zero
`passed_current` promotions. The third successor updates the LVS adapter's
static API contract and binds those two MV3DT subsets without materializing an
additional planning requirement. The fourth successor integrates the exact
calibration-schema subset while preserving six uncovered global-vector
records. The separate 8 + 21 + 23 + 5 + 6 + 8 + 1 +
11 advertised-entry candidates and 6 + 6 + 6 + 6 + 6 + 6 + 6 + 6 + 6 additional planning
checks are non-advancing and do not change those live counts. They leave four
advertised entries as explicit external-attestation blockers and 30 planning
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
