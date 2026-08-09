# Thor local runtime qualification — 2026-08-09

This note retains the bounded runtime observations collected on the local AGX
Thor after the VSS 3.2.1 exact-model milestone. All calls used numeric loopback
endpoints. Temporary media owned by the run was deleted, and no credential or
external inference endpoint was used.

## Core runtime

- The live qualifier completed 33 probes: 32 passed, one optional probe was
  skipped, and none failed or was unavailable.
- The Agent exposed 64 routes. RT-VLM, RT-Embed, Alert Bridge, LVS, VIOS,
  VA-MCP, Prometheus, Grafana, Kibana, and the public ingress were reachable.
- Docker used the required `cgroupfs` driver.

## VIOS and analytics

- VIOS `2.1.0-26.05.4` listed the three online file sensors `pit-POV`,
  `sample-sim-traffic`, and `sample-sim-jaywalking`.
- A recorded snapshot from `sample-sim-traffic` returned HTTP 200 JPEG
  (110,905 bytes). A two-second clip returned HTTP 200 MP4 (194,059 bytes).
- A correctly initialized VA-MCP session listed all nine tools. Sensor and
  incident queries returned valid empty results for the fresh analytics store.
- Every live VA-MCP tool was then invoked through a separate initialized
  protocol `2024-11-05` session. VIOS sensor listing returned `pit-POV`,
  `sample-sim-jaywalking`, and `sample-sim-traffic`; direct sensor/place,
  incident, single-incident, average-speed, four-bucket person histogram, and
  average-person analysis calls all returned valid bounded results for the
  empty analytics indexes. The `react_agent` initially lost those sensor names
  because its nested LangChain wrapper returns a structured/Pydantic value
  while the upstream helper accepted only JSON text. The bounded parser now
  accepts only the known structured, JSON, or literal sensor-list shapes, and
  VA-MCP loads that audited local source through a read-only mount. After its
  isolated restart, `get_sensor_ids` returned all three sensors and the local
  analytics agent correctly reported that `sample-sim-traffic` had no
  incidents in the requested one-minute interval. No analytics state was
  mutated.
- Direct Video Analytics queries returned valid empty results for alerts,
  incidents, severe alerts/incidents, frames, object counts, object lists,
  sensor lookup, and last-processed timestamp. A valid behavior query initially
  exposed an unmapped `end` sort field on the empty bootstrap index; the
  bootstrap mapping now defines both `timestamp` and `end` as dates, and the
  same request returns HTTP 200 with an empty behavior list.

## Alerts and observability

- Alert Bridge health, alert-submission dependencies, verification-config
  persistence, realtime-rule listing, and realtime-incident listing returned
  valid HTTP 200 responses through numeric loopback. The public ingress also
  routed Alert Bridge REST calls correctly.
- The WebSocket service initially reported degraded because it opened the
  image's default `config.yaml` instead of the launcher's substituted
  `CONFIG_PATH`. The service now uses `CONFIG_PATH` by default. Its Redis
  consumer reports healthy, and real ping/pong exchanges passed through both
  `ws://127.0.0.1:9080/ws/alerts` and the public
  `ws://127.0.0.1:7777/alert-bridge/ws/alerts` route.
- Alert Bridge Prometheus export is enabled on dedicated loopback port 9081.
  The registry returned HTTP 200, Prometheus scraped the `alert-bridge` job as
  healthy, and all eight configured Prometheus jobs were present with zero
  unhealthy targets.
- On-demand verification accepted an existing VIOS traffic snapshot set with
  HTTP 202, exposed bounded queued/running/completed job state, invoked the
  exact local Cosmos3 model, parsed a rejected verdict with visual reasoning,
  and wrote the transformed `Person in Monitored Zone` incident to the local
  Elasticsearch sink. Both the intended four-frame request and a one-frame
  request completed with verification response code 200. During the first
  one-frame probe Cosmos3 returned the exact bare token `NO` despite the JSON
  response-format request; the Thor Alert Bridge derivative now accepts only
  exact binary `YES`/`NO`/`A`/`B` fallbacks while continuing to reject all
  other malformed non-JSON text. Its response-parser suite passed 123 tests,
  and the rebuilt image is
  `sha256:74879bdea9efaaf5786f0570fcec2dbb193f3a7df6b0f72b609984e33da881fb`.
  Every owned Elasticsearch qualification document was deleted by exact ID,
  and a prefix query confirmed that zero test documents remained.

## Local inference

The owned input was
`services/vios/test/bdd_tests/data/test_video.mp4`: 2,617,799 bytes, 40.1
seconds, H.264 1920x1080 at 30 fps plus AAC-LC, SHA-256
`c569a1a381a9b8f1f86cd4cb665285044cc16d05a79c96e992f938ca3a2470ad`.

- RT-Embed reported `cosmos-embed1-448p-anomaly-detection`. Text inference
  returned 768 numeric dimensions. Video inference returned ten ordered
  chunks, each with 768 dimensions and offsets spanning 0-40 seconds.
- RT-VLM reported
  `nim_nvidia_cosmos3-nano-reasoner_bf16-final`. Non-streaming captioning
  returned five coherent chunks. SSE captioning returned five timed chunks,
  a final usage event (3,889 prompt, 191 completion, 4,080 total tokens), and
  terminal `data: [DONE]`.
- Non-streaming text chat returned the exact requested sentinel. SSE multi-turn
  chat retained the supplied codeword and terminated with `data: [DONE]`.
- RT-Embed and RT-VLM both reported zero stored assets after cleanup.

## Video summarization and LVS MCP

- LVS fetched a VIOS-hosted ten-second `sample-sim-traffic` clip and used the
  exact local Cosmos3 Nano model. `POST /v1/summarize` returned a structured
  narrative plus a timestamped black-car event. The compatibility
  `POST /summarize` route also passed with an existing file ID, a 0-10 second
  media offset, object/event/scenario focus, reasoning, sampling controls, and
  structured output enabled.
- A second ten-second `sample-sim-jaywalking` request returned a timestamped
  pedestrian-crossing event. Supplying both resulting file IDs in the direct
  LVS `id` array was accepted but processed only the first ID. This is retained
  as an upstream direct-API limitation; the separate Agent multi-video report
  workflow remains to be exercised through its endpoint and HITL contract.
- The live LVS SSE MCP transport negotiated protocol `2024-11-05` and exposed
  all 13 tools. Readiness, liveness, model listing, empty file listing,
  recommended configuration, and Prometheus retrieval returned valid tool
  results. The MCP `summarize_video` streaming path passed its bounded SSE
  validator, and exact-ID `list_files`, `get_file_info`, and confirmed
  `delete_file` cleanup completed with zero assets remaining.
- The file-caption route initially accepted its public `prompt` field but
  replaced it with an empty summarization template. The Thor derivative now
  preserves the supplied caption prompt (and still allows the documented
  default when empty). After rebuilding only LVS,
  `POST /generate_vlm_captions` returned one 0-5 second natural-language chunk
  describing a white car moving along the road. The owned file was deleted and
  LVS returned to an empty file inventory.
- `POST /recommended_config` returned chunk size 60 for the documented
  300/60/5 input, while missing required summarization fields and an unknown
  request field each failed closed with HTTP 422.

## Native audio boundary

The installed Cosmos model honestly reports `audio_support: false`. An
`enable_audio: true` request returned the expected HTTP 400 capability error;
the same AAC fixture succeeds in the visual lane. No supported 30B Omni
snapshot exists locally. At the observation point Thor had 61 GB free disk,
5.3 GiB available unified memory, and no swap, while the complete VSS stack was
running. The supported FP8 Omni lane needs about 39 GB for weights and the
checked-in admission policy requires 80 GiB available memory. Native semantic
audio therefore remains blocked by a specific absent artifact and current
capacity, not by missing VSS wiring or codecs.

## Browser UI and dashboard repair

A real headless Chromium session at `http://127.0.0.1:3001` exercised Search,
Alerts, Dashboard, and Video Management at 1440x900. Navigation, the three
online video cards and thumbnails, alert sensor inventory, chat panel, and
zero-horizontal-overflow layout rendered.

The first Dashboard run exposed a real Kibana failure in both Thor overview
panels: the empty `mdx-raw-*` and `mdx-behavior-*` patterns did not expose
`timestamp` as a date, so Kibana rejected its time-bar configuration. The Thor
dashboard initializer now idempotently creates empty one-shard bootstrap
indexes with an explicit `timestamp: date` mapping before importing saved
objects. After rebuilding and rerunning the initializer, both `Detected
Objects` and `Behavior Events` rendered the correct `No results found` state
with no visualization error. No synthetic analytics documents were inserted.

## Verification

- The inert stateful acceptance compiler now resolves all 500 advertised
  capabilities, 350 REST operations, 42 MCP tools, five MCP prompts, and 16
  installed VSS skills across 17 API surfaces. Its Agent surface lock was
  refreshed from the pre-sync 56-operation contract to the current exact
  64-operation manifest, and the compiler plus its 41 safety/coverage tests
  are now part of the unified static milestone.
- `deploy/docker/test-scripts/test-thor-runtime-infrastructure.sh` passed.
- The final read-only runtime qualifier reported 33 total probes: 32 passed,
  one optional Video Analytics OpenAPI probe skipped, and zero failed or
  unavailable.
- `deploy/docker/test-scripts/test-thor-static-parity-milestone.sh` finished
  with `PASS: unified static-only Thor parity milestone`.
