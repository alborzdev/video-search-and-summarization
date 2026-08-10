# Thor LVS file-summarization runtime qualification — 2026-08-10

This note retains end-to-end runtime evidence for NVIDIA VSS 3.2.1 Long Video
Summarization (LVS) on AGX Thor. All media, caption inference, aggregation,
Kafka/Elasticsearch support, and HTTP serving remained on this Thor. No Agent
`/generate` call was made, no external inference endpoint was used, and the
existing VIOS sensor/recording inventory was not modified.

## Runtime identity and control plane

- `vss-lvs` was healthy on host networking from image
  `cti-vss-video-summarization:thor-local`, image ID
  `sha256:1037a857158cfbc9c2be87bea92838c60cc1d528357ec5c3d9feea483bd9aefd`.
  Its NVIDIA base is selected as `vss-video-summarization:3.2.1` by the
  reproducible Thor build.
- `GET /v1/healthz` returned HTTP 200 with `version: 3.2.1rc1`; the separate
  legacy metadata field returned `version: 3.0.0`, `sub_version: d16a216`.
  This note records both values rather than conflating them.
- `/v1/ready`, `/v1/live`, `/v1/startup`, `/v1/healthz`, `/v1/metadata`,
  `/models`, and `/metrics` all returned HTTP 200. The three lifecycle probes
  correctly returned empty success bodies.
- `POST /recommended_config` with a 300-second video, 60-second response
  target, and five-second use-case event returned HTTP 200 with
  `chunk_size: 60`.
- LVS model discovery advertised exactly
  `nim_nvidia_cosmos3-nano-reasoner_bf16-final`. RT-VLM independently
  advertised that same ID at its loopback-only OpenAI endpoint.
- LVS aggregation was configured to the local loopback endpoint
  `http://127.0.0.1:30081/v1`. That server was healthy and advertised exactly
  `nvidia/NVIDIA-Nemotron-3-Nano-4B-FP8`.
- Prometheus reported one completed file query and zero pending immediately
  after the primary semantic run. The metrics response was 8,630 bytes with
  SHA-256
  `e9d653c81a12fbacaec7412d0b04a7596cfbb5d0a4fa5434c941a332f8f44953`.

The read-only upstream-main compatibility probe is also now live rather than
static: `GET /files?purpose=invalid` returned HTTP 422 with the exact enum
constraint `Input should be 'vision'`. The version-prefixed `/v1/files` route
is intentionally absent and returned 404, matching the implementation route.

## Primary VIOS-to-LVS result

The existing `pit-POV` stream
`4b37c652-3d8f-4af3-8cfd-a16d5ef85d26` retained this canonical VIOS timeline:

```text
2025-01-01T00:00:00.000Z -> 2025-01-01T00:00:19.205Z
```

The canonical VIOS binary extraction endpoint returned an MP4 with H.264
1280x720 video, AAC audio, 60 fps, duration 19.209 seconds, 16,393,475 bytes,
and SHA-256
`e5b69d273716e6a261480470fc4372daf3909c69905b6a0e2ac952791af78df5`.
LVS received the exact autonomous skill defaults
`scenario="activity monitoring"` and `events=["notable activity"]`, the exact
advertised Cosmos model ID, ten-second chunks, 20 fixed frames per chunk, and
seed 1.

`POST /v1/summarize` returned HTTP 200 in 51.819404 seconds. The completion
processed two chunks, used the exact requested model, ended with
`finish_reason: stop`, and contained a valid JSON string rather than a Markdown
fence or reasoning trace. The 1,502-byte raw response has SHA-256
`790381a79416cddbf88a51374c325967569592eb63be26e913825e5034ee009c`.
Its raw semantic payload was:

```json
{
  "events": [
    {
      "id": 1,
      "start_time": 10.03,
      "end_time": 18.76,
      "type": "notable activity",
      "description": "A black race car with Monster Energy branding and the number 54 prominently displayed is seen driving away from the pit area onto the racetrack. The vehicle accelerates smoothly along the track, passing by other cars in the background as it heads into the distance under overcast skies."
    }
  ],
  "total_events": 1,
  "video_summary": "A black race car bearing Monster Energy branding and the number 54 is observed departing the pit area and entering the racetrack. The vehicle accelerates smoothly along the track, maintaining a steady pace as it passes other cars in the background. The activity continues under overcast skies, with the car progressing steadily into the distance."
}
```

The event bounds are ordered and fall inside the retained recording. The event
type exactly matches the requested event vocabulary, and both the event
description and overall summary are nonempty.

An earlier client attempt was rejected before inference with HTTP 422 because
its body was empty after incorrect shell-side `events` escaping. That result is
not counted as semantic evidence. The corrected request constructed
`events:[$event]` inside `jq` and was the only full-length semantic call.

## Advertised format matrix

The official FAQ advertises MP4, AVI, MOV, MKV, and WebM. MP4 was proven by the
full VIOS clip above. To prove the other containers without wasting disk or
model time, the same 10-13 second visual section was encoded as 384x216, 5 fps,
three-second local fixtures. The complete fixture pack was only 1,278,551
bytes. Every request used six fixed frames, one three-second chunk, seed 1,
the same scenario/event fields, and the exact Cosmos model.

| Container | Codec | Fixture bytes | Fixture SHA-256 | HTTP / seconds | Chunks | Events | Summary chars | Response SHA-256 |
|---|---|---:|---|---:|---:|---:|---:|---|
| MP4 | H.264 | 16,393,475 | `e5b69d273716e6a261480470fc4372daf3909c69905b6a0e2ac952791af78df5` | 200 / 51.819404 | 2 | 1 | 346 | `790381a79416cddbf88a51374c325967569592eb63be26e913825e5034ee009c` |
| AVI | MPEG-4 | 305,714 | `aeafd9b82d37416069b88b59e86edc7d2e9319153e07c6cbd7d38783b8401eac` | 200 / 25.094191 | 1 | 1 | 530 | `6a367eabbdb0fe4083648e2ec7302271e768eb6acb7f8fc440e68d2d1023a149` |
| MOV | H.264 | 278,900 | `5960814cfc0d610b5663b3a29b9a197960dea5cda6c6835089d73093c818ffbd` | 200 / 23.213378 | 1 | 1 | 481 | `8195e2a924de2987d5806f799bd427cfbbe01769fabda9cca6d0dd6214195381` |
| MKV | H.264 | 278,938 | `e6e6cce6a49c431c9213474d4a450db4270453f469b8251d7c1b33be841c0838` | 200 / 19.746472 | 1 | 1 | 355 | `b0e585c4fab8e07b356a410259ef3d57961d7720b36c74bb04cc64ea4971e204` |
| WebM | VP9 | 136,045 | `d11da6f7b54f8a4bff54adfdaba41f5a4248d63bfbbdff07f4c67896f3b3b1f5` | 200 / 25.296060 | 1 | 1 | 638 | `7d7ab47c3c0fb2d908edb16e22b5330a1a0c67376b4f766ca9ab46c02dc4b6fc` |

Each response passed the same outer completion checks and inner JSON checks:
exact model, `summarization.completion`, one choice, `finish_reason: stop`,
nonempty `video_summary`, array-valued `events`, and numeric `total_events`.
This qualifies `runtime.lvs.supported-formats` rather than merely asserting
that FFmpeg can open the files.

RT-VLM's SSRF control rejected the first AVI fixture URL on `127.0.0.1` with
HTTP 422 and an explicit loopback-denied message. The fixture server was then
bound only to Thor's actual `10.88.8.175` interface, which is the same local,
non-loopback pattern used by VIOS. No SSRF exception or security-control
weakening was introduced.

## Concurrent-request serialization

Two three-second requests (AVI and WebM) were submitted 1.2 milliseconds apart
and both eventually returned HTTP 200 with valid summaries. During the run,
167 Prometheus samples at 250-millisecond cadence observed:

- `video_file_queries_pending`: 0 -> 2 -> 1 -> 0
- `video_file_queries_processed`: 6 -> 7 -> 8
- total wall time: 47.313 seconds
- WebM response: 32.197646 seconds, SHA-256
  `db6bca0baf5e15f43ea09b583ae2a2ecd0c746eb0cd832e8b76ad07eb27692fe`
- AVI response: 47.231966 seconds, SHA-256
  `bdcfd3dfd5c6f2e28f7c57cadf3409607ca5662e53b36844190a9865f6b81ce4`
- metric sample artifact SHA-256
  `37e5d02e5b498d0bc80114dad220979815154b06c94d2db1e371b9ec1b23623c`

The RT-VLM logs provide the model-boundary proof that the pending gauge alone
cannot: both inputs were downloaded and admitted, but the WebM chunk completed
at `08:32:24.898Z` and the AVI chunk did not complete until
`08:32:45.775Z`. No second model chunk completed during the first interval.
Thus the additional request waited for serialized model execution while the
HTTP control plane remained responsive. This qualifies the observable
one-active/additional-pending behavior in `runtime.lvs.single-request-queue`;
pre-download and decoder preparation may overlap.

## Source verification and scope

Focused local tests passed after creating the NVIDIA logger's expected
temporary `/tmp/via-logs` directory:

```text
85 passed, 82 subtests passed in 1.88s
4 Thor LVS purpose-patch tests passed
```

The OpenAPI source independently requires `model`, `scenario`, and `events`,
sets `additionalProperties: false`, and exposes both canonical
`/v1/summarize` and compatibility `/summarize` routes.

This evidence qualifies local LVS file summarization, all five advertised file
containers, request serialization at the model boundary, core health/model/
metrics/config probes, and the live upstream-main `Purpose` enum behavior. It
does not yet claim all 17 LVS REST operations, the 13-tool LVS MCP surface,
Agent HITL/media orchestration, stream captioning/summarization, audio-enabled
summarization, the NVIDIA reference performance envelope, or graph QA. Those
remain separate runtime capabilities in the parity ledger.
