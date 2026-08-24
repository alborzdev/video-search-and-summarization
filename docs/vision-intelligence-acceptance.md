# Vision Intelligence shakedown and acceptance record

Final acceptance was performed on NVIDIA Thor on 2026-08-19 against the
rebuilt production image through the supported trusted-LAN gateway at
`http://10.88.8.175:7777`.

The accepted runtime had five sources: one traffic source actively analyzed as
a general scene and four Isaac Sim sources deliberately paused. Pausing was a
resource-control choice, not a hidden failure. The cache cleaner was running
throughout final acceptance.

## Feature verification ledger

| Area | Accepted behavior | Runtime proof |
| --- | --- | --- |
| Application shell | Operations, Investigate, and Manage have coherent navigation; System readiness and Presentation Mode work from every workspace. | Real browser fullscreen entered and exited. The readiness popover reported all seven local capabilities online. |
| Operations overview | A responsive camera grid shows every VST source, truthful Live/Replay/Paused/Offline state, recent intelligence, attention state, and a focused-camera handoff. | Five sources rendered from the LAN origin. The traffic source reported `Analyzing`; four paused sources remained visible without requesting noisy live snapshots. |
| Focused camera | Live/replay media, source-scoped Vision Analyst, intelligence state, analytics mode, Activity, Insights, and History remain in one camera workspace. | Traffic media decoded at 1920x1080 with no media error. The source reported active semantic indexing and caption history without falsely claiming warehouse detections. |
| Current-camera questions | Cosmos visually inspects retained current footage and Nemotron synthesizes the local answer; continuous captioning resumes after the one shared Cosmos lane is released. | The single-model-lane reservation/recovery workflow was exercised against a live source and returned to continuous captioning. |
| Semantic search | Natural-language search supports all-source/source, live/recorded, time, status, sorting, pagination, and provenance filters. | `pedestrian crossing` returned 18 locally indexed matches after the final deployment. The first exact clip loaded at `readyState=4`, 1920x1080, with no media error. |
| Evidence playback | Search, incidents, history, reports, and visual matches resolve to bounded, same-origin VST MP4 evidence rather than an RTSP URL or stale temporary link. | A search result played a 4.366-second MP4. A GraphRAG citation resolved to a 15-second, 9.6 MB MP4 and decoded with both Chromium and `ffprobe`. |
| Visual similarity | Find Similar is exposed only for a real indexed detector/tracker object at the selected frame; object ID, sensor identity, and timestamp are preserved. | Detector-backed object selection, visual ranking, explicit unavailable state, and expired/missing-object handling have component/API regression coverage. No synthetic boxes are generated. |
| Evidence analysis | Selected clips persist in an evidence tray; Cosmos inspects the exact clips and Nemotron returns observed facts, interpretation, timeline, and citations. Follow-ups stay scoped to the selected evidence. | Multi-clip analysis, follow-up, investigation persistence, report export, and citation reopen/playback passed the browser/API workflow. |
| GraphRAG history | Source-scoped captions build asynchronous LVS/Neo4j history. Questions return graph-grounded answers with playable timestamp citations. | 128 caption documents produced 107 consolidated traffic events. A real question returned five standalone ISO timestamps; each is converted to a retained -5s/+10s clip window. Evidence 1 loaded at `readyState=4`, duration 15 seconds, without warnings. |
| Activity and incidents | Confirmed/rejected candidates show source, time, reasoning, state, and evidence actions; empty data remains honest. | Direct incidents API coverage and rendered Activity/Insights acceptance passed. No fabricated incident was created for normal traffic footage. |
| Alert rules | Rules can be listed, created, edited, enabled/disabled, and deleted per camera without replacing that camera's shared caption stream. | A temporary real traffic rule processed five 30-second windows, correctly emitted no incident, stopped its exact request on delete, and left the shared RT-VLM stream and captioning active. No rule remains. |
| Native Insights | Operational briefing, alert/event/source distributions, processing state, and evidence drill-down replace the embedded Kibana dashboard. | Native Insights rendered real API-derived data and honest empty states; raw Kibana remains an operational backend, not the customer UI. |
| Source management | File upload, RTSP registration, preview, pause/resume, analytics mode, derived-data reset, and deletion expose truthful progress and cleanup scope. | Traffic pause stopped embedding/indexing while retaining 6,999 indexed moments and ready history; resume restored embedding, indexing, and 30-second captions. Source cleanup/reset/delete routes have direct regression tests. |
| LAN operation | UI, APIs, media, images, reports, and WebSockets use the single LAN origin; no browser flow depends on `localhost`. | A fresh Playwright session used `10.88.8.175:7777`; every `/api/vision/*` request returned 200 and media was served from the same origin. |
| Responsive behavior | Desktop and mobile layouts remain usable without horizontal page overflow. | At 390x844, document and body widths both equaled the 390-pixel viewport. The prior Add RTSP modal acceptance also fit inside 16-pixel mobile margins with its footer actions reachable. |
| Error handling | Backend failures, unavailable detector frames, missing recordings, paused analysis, and empty results have explicit recoverable states. | API handler tests cover evidence cache/media, incidents, source intelligence, VST images, history repair gating, and lifecycle failure disclosure. |

## Automated verification

- Custom Vision Intelligence Jest suite: **35 suites and 182 tests passed**.
- Video Management Jest suite: **9 suites and 117 tests passed**.
- Agent lifecycle/control regression set: **135 tests passed**; focused
  analytics/search regressions: **98 tests passed**.
- Thor tegrastats exporter: **11 tests passed**.
- LVS GraphRAG/Neo4j and source-cleanup patch tests passed in their focused
  qualification runs.
- Application TypeScript checking passed with `tsc --noEmit`.
- The production UI image completed all 11 monorepo build/bundle tasks. The
  deployed manifest-list digest is
  `sha256:0987c11c090588c6eadab26bb5e9d05b08b85c749ddda67bc8562bfad7e008c8`.
- `git diff --check` reports no whitespace errors.
- A host-only attempt to collect every Agent Python test cannot import NVIDIA
  NAT and `langchain_core`, which are intentionally installed in the production
  Agent environment rather than on the host. The affected production paths and
  their focused tests ran in the correct environment; this is not a runtime
  failure.

## Final browser acceptance

- Fresh post-deployment Chromium session: **0 console errors, 0 warnings**.
- All observed `/api/vision/*` requests returned HTTP 200.
- `pedestrian crossing` returned 18 semantic matches; exact MP4 playback was
  fully buffered and decodable.
- The deployed GraphRAG question returned five visible Evidence buttons. Its
  first citation opened a 15-second, 1920x1080 clip at `readyState=4` with no
  media error.
- Presentation Mode used real browser fullscreen and had a visible exit.
- Readiness displayed Video I/O, Vision Agent, Analytics, Detection + tracking,
  Video embedding, Cosmos visual reasoning, and Nemotron synthesis online. It
  reported `Accelerator: Active` because this Thor tegrastats build does not
  expose a trustworthy percentage; temperature and power remain real values.

## Host and resource acceptance

`./deploy/docker/scripts/thor-local.sh doctor` finished with **40 PASS, 2 WARN,
0 FAIL**. It confirmed cgroupfs, kernel settings, the cache cleaner, exact local
Cosmos/Nemotron models, all 37 Compose services, the LAN gateway, VST/VIOS,
search, embeddings, alerts, GraphRAG dependencies, monitoring, and every
required health endpoint.

The two warnings are operational, not hidden product failures:

1. Thirty-eight internal listeners bind beyond loopback. The supported
   customer ingress is still bound only to `10.88.8.175:7777`; use Thor only on
   the trusted isolated LAN until internal listener hardening is completed.
2. The root disk is 97% used with about 34-35 GiB free. This is adequate for the
   accepted demo, but operators must not pull large images or ingest an
   unbounded set of streams before a show.

At final acceptance, about 28 GiB of unified memory remained available. All
running containers reported `OOMKilled=false`. The final UI, Agent, Alert
Bridge, embedding, detection, Cosmos, and Nemotron containers had zero current
restart count; model and data services had remained healthy through the final
build/browser soak. Kernel logs contained no OOM, watchdog, thermal, or panic
event during the final acceptance window.

## Honest limitations and show-floor boundaries

- The Thor-safe operating point is one continuously analyzed live stream plus
  recorded archives. Keep additional streams paused unless a supervised demo
  needs them and readiness/memory headroom remain healthy.
- General traffic scenes receive semantic embedding, captions, history, alerts,
  and visual reasoning, but not warehouse RT-DETR boxes. Enable **Warehouse
  detection + tracking** only for a compatible camera/model. Find Similar is
  therefore unavailable when no real detector object exists.
- The bundled VLM uses bounded retained windows for current-camera questions;
  longer historical reasoning belongs in source History/GraphRAG or selected
  evidence analysis.
- Voice input is visibly unavailable because no local speech service is in the
  approved runtime. The control is deliberately disabled, not a dead feature.
- Map remains hidden because the Thor demo profile has no approved map service.
- Port 7777 is an unauthenticated, unencrypted trusted-LAN surface. Never expose
  it to the internet; production deployment needs an authenticated TLS edge.
- Live-camera availability still depends on the simulator/camera and venue
  network. Keep known-good traffic and warehouse recordings as honest replay
  fallbacks.

Run the authoritative pre-show check from the repository root:

```bash
./deploy/docker/scripts/thor-local.sh doctor
```

## Development-readiness addendum — 2026-08-23

This addendum records the repository artifact produced by the cleanup, product,
and capability-gap pass. It does not replace the 2026-08-19 deployed-runtime
acceptance above. The running Compose stack was not rebuilt or restarted, and
no model-heavy qualification workload was invoked during this pass.

### Delivered repository state

- The custom product is a seven-workspace Vision Intelligence UI: Home, Live,
  Monitoring, Explore, Events, Capabilities, and System. Workspace URLs are
  stable, browser history is preserved, all destinations remain available in
  the 390-pixel mobile navigation, and both light and dark themes use the same
  evidence-led information hierarchy.
- Initial server data is fail-soft, major workspaces are loaded on demand, and
  the System workspace exposes observable workload admission and per-source
  search/index/retention coverage without inventing readiness percentages.
- Every active modal uses the shared focus-trap, Escape, focus-restoration, and
  nested-dialog behavior. Polygon monitoring regions support keyboard point
  creation, arrow-key movement, accelerated movement, and deletion.
- The Agent now owns the exclusive Thor visual-workload boundary for both
  direct and UI-proxied visual inspection/evidence-analysis requests. It
  refuses an active live-alert reservation, serializes the local Cosmos lane,
  yields and restores continuous captions with the source's exact saved event
  list and scenario (or the same scenario-aware defaults as the UI), and
  releases its lock even if restoration is cancelled or fails unexpectedly.
  The UI queue has the same release guarantee.
- Finite detector profiles are enforced server-side with an atomic process-wide
  claim/reservation boundary across RTSP add, live profile changes, upload
  completion, and recorded reprocessing. Retained recordings count because
  RT-CV keeps them registered until explicit deletion or reprofiling.
- The Docker runbook, image compatibility inventory, validator, curated docs
  index, and clean-device/offline recovery guidance are checked in. All eleven
  custom Agent routes are explicit Thor-local contract extensions, while the
  upstream 64-operation Agent denominator remains unchanged. Admission,
  capacity, lifecycle, and state sources are digest-bound by that contract.
- The proven-unreachable legacy Home/chat-sidebar closure and two unused NVIDIA
  logo assets were removed. Qualification evidence, accepted design assets,
  model/runtime data, and ambiguous operational artifacts were retained.

### Repository and browser verification

- Vision Intelligence application Jest: **39 suites, 146 tests passed**.
- Shared UI package Jest: **8 suites, 88 tests passed**.
- Video Management Jest: **10 suites, 121 tests passed**.
- Application TypeScript and ESLint checks passed.
- The 4 GiB-capped Next.js production build completed **46 pages**. The main
  route is **126 kB first load**, shared first-load JavaScript is **216 kB**,
  and the final stylesheet is approximately **99.4 kB**.
- Final standalone Playwright acceptance: **8/8 passed**. It covers meaningful
  rendering, all seven desktop destinations, stable deep links/history, all
  seven mobile destinations with no body overflow, readiness/appearance
  controls, light- and dark-theme WCAG scans over every workspace, and Escape
  dismissal. Axe reported no serious or critical violations in the accepted
  run. A timing-soak repeat encountered one transient Chromium
  `ERR_NETWORK_CHANGED`; all four immediate HTTP probes returned 200 and the
  affected dark-theme scan then passed **1/1** without suppressing the fault.
- Final visual inspection covered a populated 1440-pixel dark Live dashboard
  and a full 390-pixel light Home flow with six real sources and the fixed
  seven-item bottom navigation.
- Agent admission/capacity regression set: **15 passed, 1 skipped**. The skip is
  the dependency-heavy endpoint wrapper on the host; the pure lease,
  exact-session restoration, fallback, restoration-failure, concurrency,
  finite-capacity, and structured-conflict cases passed. The new modules also
  imported successfully through the running Agent image's dependency-complete
  virtual environment.
- Static API contract regression: **20 tests and 20 subtests passed**.
  Contract qualification passed **17 surfaces**, **362 declared REST
  operations (361 normalized)**, **44 MCP tools**, and **5 MCP prompts**. The
  implementation contains **16 explicit Thor-local extensions** while the
  official denominator remains **346 declared (345 normalized)**.
- The complete offline qualification harness passed **94 tests**, including its
  plan-only acceptance executor. The operator wrapper's shell, source-mode,
  read-only contract, regeneration guard, runtime-help, and JSON checks passed.
- Deployment-lock tests: **4 passed**. The validator reports **0 errors and 44
  unresolved/mutable image warnings** without invoking Docker or the network.
  The exact two-file Thor Compose graph renders successfully, and all modified
  shell entrypoints pass `bash -n`.
- The read-only security audit passed protected-env ownership/mode/blank-secret
  checks, container credential checks, and the LAN gateway binding check.

### Open operational gates

1. Preflight still stops because `/usr/local/bin/sys-cache-cleaner.sh` is not
   running. Start it after reboot with operator-approved privilege before any
   deployment or GPU-heavy demo.
2. Offline verification intentionally fails until reviewed image provenance is
   reconciled. Four staged tags changed (`cti-vss-alert-bridge:thor-local`,
   `cti-vss-rt-embed:thor-local`,
   `cti-vss-video-summarization:thor-local`, and `vss-agent-ui:thor-local`), and
   `vss-evidence-clip:thor-local` has no protected lock. Restage reviewed images
   or explicitly accept the current IDs before refreshing the lock; never
   rewrite it merely to make the check green.
3. Thirty-nine internal TCP listeners still bind beyond loopback and the
   optional `cti_vss` physical-interface firewall is not confirmed active.
   Port 7777 remains an unauthenticated, unencrypted trusted-LAN surface.
4. The running stack was deliberately left untouched. Agent admission,
   capacity enforcement, and the final UI bundle take effect on the next
   reviewed restage/redeploy.
5. Audio analysis, automatic calibration, multi-replica Agent scale-out, and
   internet exposure remain blocked pending dedicated Thor qualification. A
   multi-replica Agent would require a shared lease store rather than the
   current single-process locks.
6. Full Agent route-suite collection remains unavailable on the host because
   its production NAT, `aiohttp`, `tenacity`, and Elasticsearch dependencies
   live in the image. Ruff, formatting, compile, changed-module Mypy, focused
   host-safe tests, and an in-image import smoke passed. The full configured
   Mypy run stops in the host's NumPy stubs because they use Python 3.12 type
   syntax while this package's Mypy configuration targets Python 3.11; no
   dependency was changed just to hide either boundary.
7. `npm audit --omit=dev` could not obtain an advisory report: the configured
   mirror returned `404 NOT_IMPLEMENTED`, and the official registry retry
   failed during TLS connection setup. No dependency was changed on the basis
   of an unavailable audit.

Use [the canonical Docker deployment guide](../deploy/docker/DEPLOYMENT.md) for
the reviewed clean-device, image-lock recovery, preflight, rollback, and
trusted-LAN sequence.
