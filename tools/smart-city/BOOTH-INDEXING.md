# Finite Smart City search indexing

Source implementation, October 26, 2026. This work is not deployed or GPU-qualified by the CPU checks. No live source policy, model or service setting was changed during development.

The Smart City profile now defaults to **on-demand** semantic indexing. Resume keeps its detector, tracker, map and rules active. It does not start continuous Cosmos Embed generation. Existing non-city profiles retain the continuous default. An explicitly saved per-source policy takes precedence over profile defaults.

The source still uses normal VSS recording and on-demand visual questions. This policy controls embeddings only. It does not start or stop caption generation, delete vector history, remove recordings, or change the detector interval.

## Agent API

The route prefix is `/api/v1/rtsp-streams/{source-id}/indexing`. Mutations verify the exact registered source name/ID. Finite windows require a desired-active live source and the `on-demand` mode.

| Method | Body | Effect |
| --- | --- | --- |
| GET | None | Read policy, actual managed generation connectivity, finite session and search-index evidence. |
| PUT | `{"name":"Intersection southwest","mode":"on-demand"}` | Save policy, stop generation and remove its embedding resource. CV is unaffected. Modes: `on-demand`, `disabled`, `continuous`. |
| POST | `{"name":"Intersection southwest","action":"start","durationSeconds":120}` | Start one finite live indexing lease. Default 120 seconds; strict bounds 30-600. A duplicate active start returns 409. |
| POST | `{"name":"Intersection southwest","action":"cancel"}` | Stop managed generation and its remote resource. Cancelling continuous indexing switches its policy to disabled, preventing the reconciler from restarting it. |
| POST `.../search-request` | `{"name":"Intersection southwest","sessionId":"returned-uuid","query":"a bus stops","topK":6}` | Prepare the existing direct search request for that current finite session. It does not run a model. A stale session or unacknowledged generation returns 409. |

The search helper returns `endpoint: /api/v1/embed_search`, `method: POST` and `request`. Send that body to the existing direct search API. It carries `source_type: rtsp`, `query`, strict `exact_sensor_ids`, `timestamp_start`, `timestamp_end` and `top_k`. The exact-source filter accepts UUID/name aliases through exact terms on both released embedding document schemas. Invalid explicit source/time scope raises an error instead of becoming an unfiltered search. Legacy callers without `exact_sensor_ids` retain their prior behavior.

The status response separates these facts:

- `mode` and `indexingRequested`: durable intent and whether work is currently allowed.
- `generationConnected` / `generationManaged`: actual in-process SSE connection and task existence. Neither proves searchable vectors.
- `session`: UUID, requested/acknowledged start, fixed deadline, terminal end and state. Completed, cancelled, failed and interrupted sessions do not reconnect.
- `cleanup.status`: confirmed, failed or not-checked. A failed remote stop is visible as `state: stop-failed`; reconciliation retries it.
- `evidence`: a source/time-scoped Elasticsearch document count, latest timestamp and separately gated `liveFresh`. Missing Elasticsearch is unverified, not a successful indexing claim.
- `searchScope`: explicit source/time parameters. `applied: false` means merely reading status has not run a scoped search.

Typical states are idle, recovering, running, stopping, completed, cancelled, interrupted, disabled, paused, stop-failed or policy-error. After a deadline, the task can briefly remain stopping while bounded remote cleanup completes. It must not be presented as confirmed stopped before cleanup returns. A completed lease means work stopped; it does not certify complete vector coverage.

## UI wiring

Keep the traffic status separate from the indexing status. The existing analysis response adds `indexingPolicy` and `indexingRequired`; a healthy Smart City detector can have `analysisActive: true`, `indexingRequired: false`, and embedding/indexing steps false.

An indexing control can offer **Index next two minutes**, **Cancel indexing**, and **Search this session**. Show the selected camera and the returned start/end times next to search results. Disable finite start while a session is active, the source is paused, or `configured` is false. Show stop-failed and unavailable evidence honestly.

The delivered `CityIndexingControl` is a small **Search capture** button and popover. It reads status only while open and visible, offers an explicit two-minute capture, and labels the current session by its request time. It shows the actual camera, source clock interval, connection state, indexed clip count and stop failures. Search stays disabled until the current session has an acknowledged start and actual indexed documents. It uses neither general chat nor a continuously running model request.

```tsx
import { CityIndexingControl } from './CityIndexingControl';

<CityIndexingControl
  sources={sources.map(source => ({ id: source.id, name: source.name }))}
  onOpenEvidence={match => openExistingClip({
    sourceId: match.sensor_id, start: match.start_time, end: match.end_time,
  })}
/>
```

Pass the exact registered VST/Agent name, rather than a formatted display label. `onOpenEvidence` is optional. The narrow Next proxy at `/api/vision/city-indexing` uses the existing `VISION_AGENT_INTERNAL_URL`, allows fixed source-indexing routes, and cannot turn continuous indexing on. Its `search` action verifies a server-prepared session/source/time request before calling the existing direct search endpoint. It filters unverified source/time results and strips vectors from the browser response. The chosen result interval remains fixed beside those results even while a live capture advances. No polling continues after the popover closes.

Proxy requests are `GET ?sourceId=...`, or `POST` with `{sourceId,name,action,...}`. Actions are `start` with `durationSeconds:120`, `cancel`, `policy` with `mode:on-demand|disabled`, or `search` with `{sessionId,query,topK:6}`. The UI cannot submit an upstream URL, an arbitrary embedding vector, a wildcard source scope or a broad tool payload.

```ts
const base = `/api/v1/rtsp-streams/${encodeURIComponent(sourceId)}/indexing`;
await agentFetch(base, {
  method: "POST",
  body: JSON.stringify({ name: sourceName, action: "start", durationSeconds: 120 }),
});

// After status reports a session with an acknowledged startedAt:
const prepared = await agentFetch(`${base}/search-request`, {
  method: "POST",
  body: JSON.stringify({ name: sourceName, sessionId, query, topK: 6 }),
});
// Preserve the returned source/time params. Do not route this through general chat.
const results = await agentFetch("/api/v1/embed_search", {
  method: "POST", body: JSON.stringify(prepared.request),
});
// Label these results with prepared.sessionId and prepared.scope.
```

`agentFetch` means the application's existing authenticated Agent proxy, with JSON headers/error handling. The helper does not add a new transport or bypass admission. The direct embed search endpoint must exist in the selected VSS profile. The checked-in search/full profiles already register it; a minimal profile can correctly report it unavailable.

## Lifecycle and limits

Intent is atomically saved beside the existing source-analysis state as `source-indexing-state.json`; `VSS_SOURCE_INDEXING_STATE_FILE` can override its path. It does not change the existing YAML schema. Corrupt policy state fails closed. Active finite leases are marked interrupted on Agent restart and require an explicit new start. The fixed deadline also surrounds a silent or disconnected SSE stream. Explicit pause/cancel first retires the lease, then cancels/awaits the managed task and uses source-scoped stop/delete endpoints. No global index deletion is performed.

Only the latest finite session per source is offered by this helper. Older vectors remain intact. General assistant search does not automatically inherit a booth session. Search scope is source aliases plus camera timestamps; the vectors have no booth-session tag. Requested wall-clock bounds are not proof of synchronized camera clocks or complete coverage. Bounds select a chunk's start timestamp, so a returned clip can extend past the upper bound. Indexing remains live-window collection, not retrospective indexing of an arbitrary old recording. Search-index and recorder delays remain possible after generation stops.

The CLI provides the same explicit operations:

```sh
python3 tools/smart-city/booth_indexing.py --source-id SOURCE --name 'Exact source name' policy on-demand
python3 tools/smart-city/booth_indexing.py --source-id SOURCE --name 'Exact source name' start --seconds 120
python3 tools/smart-city/booth_indexing.py --source-id SOURCE status
python3 tools/smart-city/booth_indexing.py --source-id SOURCE --name 'Exact source name' search 'a bus stops' --session-id SESSION
```

These commands mutate only the named source where requested. They were not run against the live deployment during development. The `search-request` command prepares the body without executing a model.

## Source verification

The sanitized source receipt is `docs/qa/smart-city-2026-10-26/booth-indexing-source-controls.json`. Agent tests use the existing Agent image's Python 3.13/NAT runtime with the checkout mounted read-only, no network, no GPU runtime and a 2 GiB memory bound. The existing host environment `/tmp/vss-city-backend-test-env/bin/{python,ruff,mypy}` supplies the already installed CPU test tools; no dependencies were installed for this change. Scoped Ruff, format and six-module Mypy checks passed.

The UI's two focused Jest suites, full TypeScript check and scoped ESLint run in the existing source-mounted UI container. The exact focused command is:

```sh
docker exec -e NODE_OPTIONS=--max-old-space-size=2048 \
  -w /workspace/apps/nv-metropolis-bp-vss-ui vss-city-polish-ui \
  node ../../node_modules/jest/bin/jest.js --runInBand \
  components/vision-intelligence/smart-city/__tests__/CityIndexingControl.test.tsx \
  __tests__/api/vision/city-indexing.test.ts
```

Replace the `node ...jest...` tail with `node ../../node_modules/typescript/bin/tsc --noEmit --incremental false` for the full UI type check. These CPU checks do not prove a successful deployed capture, actual vector delivery, camera clock alignment, rendered browser layout or any FPS gain. Deployment and bounded live capture/search/stop checks remain necessary.
