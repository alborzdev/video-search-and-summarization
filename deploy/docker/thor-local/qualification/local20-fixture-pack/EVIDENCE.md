# Static evidence and non-evidence boundary

## Pinned candidate sources

Eight raw sources are locked and validated:

```text
f6f994992620fe34da36695be82b9092fc04b64a3f065a2472f614a71f77935b  manifest.json
90c6c747aa5f921186660d6da9a72e51ac245f35c6f62d3b2e34f951c7904ea2  manifest.schema.json
5b98998e21ce43838ff19ca8f59761e43fdbe0ae541319829e236eb9d27ec887  fixture.schema.json
b0b0d09c7ea38d5662f14ec961a4fc683f1a06e81996b4cf47f830393f07766d  generation-receipt.schema.json
ddeffaa3ddf8360244d17c5ed265ae637a5f228eb1adae46ee780d78dde2e517  fixtures/search-documents-bboxes.json
28c1fe5c84ee5a81e6ca32908b667dd6af4b141d971b928740756c50b06a0e8f  fixtures/alerts-incidents-tracks.json
5252536b9e3d310887e3c6cf2e0559f89f9984345a57e5333df484e9626a11c5  fixtures/hitl-state-transcript.json
7899df8025ffc61968888d5b6a7490805794ab2cab9a3e8d24724e83eb7dfaf2  fixtures/vios-remediation.json
```

Static semantic checks bind:

- exact MP4/MKV identities and the B-frame `2` failing / B-frame `0`
  reference pair;
- exact text, image, object, and selected-bbox search routes, with valid
  normalized boxes and referential integrity;
- verified/rejected candidate-alert publication decisions;
- speed, flow, collision, stall, and wrong-way track-event inputs;
- generate, refine, cancel, restart, and persistence HITL state transitions;
- VIOS failure, source-preserving local-transcode remediation, and distinct
  derived identity metadata;
- exact coverage of the nine named local runtime requirements.

## Executed checks

Static validation completed successfully:

```text
status: valid_candidate_fixture_pack
requirements: 9
media_recipes: 4
json_fixtures: 4
runtime_evidence: false
capabilities_promoted: false
```

The focused adversarial suite was executed with bytecode writes disabled:

```text
31 passed in 0.46s
```

All generation subprocesses were mocked. No FFmpeg, Docker, network, download,
model, service lifecycle, VSS runtime, or media generation action was executed.

## What this does not prove

The pack proves only deterministic candidate contracts and their static safety
controls. It does not prove that FFmpeg is present, that a generated container
has the prescribed codec structure, that a local RTSP loop works, or that VSS,
LVS, Search, Alerts, Smart City, HITL, or VIOS accepts or interprets an input.
There is no media verification mode; a generation receipt would hash candidate
bytes but is not runtime or codec-probe evidence.

Each target requirement therefore remains open until a separately authorized,
bounded runtime executor admits these fixtures, records tool/media identity,
captures the real response, enforces cleanup, and validates its requirement's
semantic oracle. No Warehouse sample is needed by this candidate fixture pack.
