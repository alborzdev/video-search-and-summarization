# Exact processed-preview performance changes — 2026-10-26

The new native worker and gateway changes are deployed on both actual Isaac cameras. Focused CPU controls pass; final combined and browser measurements are recorded separately below when available. Source-only, native publication and browser presentation rates are distinct.

## Why this subset

The saved 58.81-second run in `.spark/city/runtime/fps-gantryoff-pipeline-60s-20261023T2113Z/samples.ndjson` shows two avoidable preview losses after analysis:

| Counter delta | SW camera | NE camera |
| --- | ---: | ---: |
| Selected and encoded JPEGs | 636 / 10.81 per second | 639 / 10.87 per second |
| Sampler drops | 65 / 1.11 per second | 62 / 1.05 per second |
| Replaced pending network JPEGs | 21 / 0.36 per second | 25 / 0.43 per second |
| Published JPEGs | 615 / 10.46 per second | 613 / 10.42 per second |

There were no source-queue overruns, identity/geometry failures, oversized JPEGs, or POST failures in that saved window. Encoding kept up with the frames selected in this window. This does not establish that JPEG encoding cannot become a bottleneck at a higher input rate. Source rendering and inference still share the GPU and can remain the larger limit.

## Implemented changes

1. `PreviewSampler` now uses an integer token bucket with two frames of burst capacity. Two closely spaced current frames can pass when average delivery remains under the configured per-source cap. Pauses cannot accumulate a long backlog; clock rollback cannot create new credit. Pending queues remain bounded and prefer the latest image.
2. Each of the maximum two sources has its own libcurl sender, reusable connection, and one latest pending JPEG. A slow metadata/HTTP response from camera A no longer makes camera B wait for that response. Existing 100 ms connection and 500 ms request deadlines remain. There are no retries for obsolete preview images.
3. The Python store captures a read-only history row briefly, then hashes pixels, creates the public snapshot, serializes JSON, and assembles the envelope outside the analytics lock. Before publishing, it checks the exact row, source session, generation, age, model, geometry, and publication order again. A rule/session change, eviction, stale row, or newer published frame prevents publication of the old work.
4. Native status adds bounded cumulative timing summaries for selection-to-JPEG, JPEG-to-POST-start, and actual POST duration. Every phase reports count, mean, last, maximum, and histogram bounds for p50/p95 in milliseconds. These are worker-stage timings, not capture-to-screen latency. Histogram percentile values are upper bounds; summaries reset on worker restart. Gateway and Next.js proxy explicitly allow only valid numeric summary fields.

The exact-frame `city.preview.v1` identity checks, browser image/overlay pairing and displayed-map temporal rules remain unchanged. No new boxes or map positions are borrowed from a newer analytics snapshot. Full events and histories remain available through their separate APIs. The later display projection below limits repeated preview history.

## CPU verification

- Header sampler/outbox/timing tests pass, including 600 burst-paired arrivals preserved below the configured average cap, a rate-bound flood, long pauses/rollback, per-source queues, and histogram bounds.
- The full native worker source compiles and links in the existing DeepStream image without GPU devices or running a pipeline.
- `make preview-sender-test` runs the **production** libcurl sender loops against a controlled loopback HTTP server. With camera A's POST deliberately held, camera B publishes within the 400 ms test deadline. Releasing A permits both to finish. Timing counts and bounded shutdown pass. The test uses no CUDA context, GStreamer pipeline, source, or inference.
- Python preview tests: **28 passed**, including concurrent ingest while JSON encoding is held and rule/session/eviction/expiry/newer-publication races. The paired pixels retain the old frame's boxes when a newer observation arrives during encoding.
- UI exact-frame hook/parser and gateway proxy tests: **50 passed** across three suites. UI TypeScript checking passes.

For the sender test, use an executable isolated tmpfs because Docker's default `/tmp` tmpfs is `noexec`:

```sh
docker run --rm --network none --read-only --memory 1g --cpus 2 \
  --tmpfs /tmp:exec,size=128m \
  --mount type=bind,src=/home/sparkdev/vss/services/rtvi/rt-cv/smart-city,dst=/work,readonly \
  --entrypoint make vss-city-perception:mv3dt-demo-20261023 \
  -C /work preview-sender-test
```

## Compatible bounded display projection

A live response before this change carried 200,501 JSON bytes and 51,959 JPEG bytes. Its 97 prior events occupied 141,752 JSON bytes and 11 tracks occupied 48,644 bytes, mostly trails. This was one observed response, not a matched performance benchmark.

The deployed gateway now retains all active events from the exact captured row and the eight newest other outcomes. Unknown outcomes retain their unknown state. Trails keep up to twelve original samples across the original time span, including both endpoints. Bounding boxes, current positions, source/model/frame identity, rule geometry, metrics and calibration are unchanged. The new `displayScope` describes these limits and omitted-outcome count. Full captured history rows, durable events, Reports and event evaluation are unchanged. This is compatible with the existing strict parser; no revision cache or alternate video clock is introduced.

The 218 city backend tests pass. The new test proves old active events survive after many newer closed outcomes, trail endpoints/timestamps remain original, payload falls below one third on the controlled large-history case, and captured history is not mutated. Existing hashing/encoding/session/rule-reset races still pass. Deployment used confirmed pauses for both owned sources, a CPU gateway restart and the normal launcher. Both sources recovered real inference, exact previews, all 15 rules and recent retained recordings. A first live projected response had 39,111 JSON bytes with 13 tracks and one event; differing scene/history content means this is not a percentage comparison.

## Next live experiment

After the operator deploys the changes, run one bounded comparison at the same source resolution, model, detector interval, preview cap, and browser visibility. Compare source/analyzed FPS, selected/encoded/published deltas, sampler/network replacements, new stage summaries, displayed FPS, and exact-frame/session errors. Do not raise several rates or change resolution in the same comparison. Confirm that faster posting does not take resources away from rendering/inference.

## Remaining work

Earlier saved final envelopes were about 158–170 KB each, of which roughly 110–121 KB was JSON. The display projection above now bounds repeated event/trail history. Immutable rules/calibration still travel with every exact frame. A later revision cache can remove that remaining static repetition. It needs explicit cache-miss/session-reset tests and must preserve historical map semantics. A string-table codec would make duplicate work harder to inspect without removing it.

Hardware video/WebRTC can be a later experiment. Plain browser video playback does not itself prove which analytics frame is on screen. Any migration must demonstrate outgoing video timestamp identity and matching metadata before replacing the current exact JPEG envelope. Until then, the existing bounded fetch/decode/display path is the trustworthy reference.
