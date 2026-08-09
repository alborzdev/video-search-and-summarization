# Thor local runtime qualification — 2026-08-09

This note retains the bounded runtime observations collected on the local AGX
Thor after the VSS 3.2.1 exact-model milestone. All calls used numeric loopback
endpoints. Temporary media owned by the run was deleted, and no credential or
external inference endpoint was used.

## Core runtime

- The live qualifier completed 31 probes: 30 passed, one optional probe was
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

- `deploy/docker/test-scripts/test-thor-runtime-infrastructure.sh` passed.
- `deploy/docker/test-scripts/test-thor-static-parity-milestone.sh` finished
  with `PASS: unified static-only Thor parity milestone`.
