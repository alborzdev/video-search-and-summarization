# Thor RT-VLM audio and codec lane

This directory contains a source-complete but deliberately inactive alternate
lane for VSS 3.2.1 audio understanding. It is not included by the normal Thor
launcher, so the existing `datasheet-vision` Qwen/OpenAI-compatible lane stays
image-only and unchanged.

## Two separate capabilities

Multimedia codec support and audio understanding are not the same feature.

- The codec derivative adds the 59 ARM64 Ubuntu Noble package identities named
  by the VSS 3.2.1 non-root installer. The tracked
  `codec-bundle.lock.json` fixes every version, filename, size, SHA-256, and
  credential-free `ports.ubuntu.com` source URL. Connected staging resolves
  through signed metadata but succeeds only when every result equals that lock.
  They provide FFmpeg/GStreamer demux and decode
  support for formats including MP4, AAC through libav, MP3, FLAC, Ogg, H.264,
  H.265, VP9, and software AV1. This lets RT-VLM decode supported containers
  and tracks; it does not make an image-only model understand sound.
- Native audio understanding additionally requires an Omni checkpoint, the
  service-wide `VLM_MODEL_SUPPORTS_AUDIO=true` flag, and `enable_audio=true` on
  each request. RT-VLM then decodes 16 kHz PCM and passes it to the model's
  audio modality. The pinned lane uses no separate Riva service.

VSS 3.2.1 documents Nemotron Omni and Qwen Omni model families. This Thor lane
intentionally narrows that broad surface to one checkpoint:
`nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-FP8`. The repository's LVS
example also names `nvidia/Nemotron-Nano-V3-Omni-GA0420-FP8`; that is a distinct
identifier and is not silently treated as the same artifact here.

## Audio-specific RT-VLM API contract

| Contract | VSS 3.2.1 default | Audio-lane value |
| --- | --- | --- |
| `VLM_MODEL_TO_USE` | `openai-compat` in the profile Compose | `vllm-compatible` |
| `VLM_MODEL_SUPPORTS_AUDIO` | `false` | `true` |
| `VLM_TRUST_REMOTE_CODE` | `false` | `true` |
| `INSTALL_PROPRIETARY_CODECS` | `false` | remains `false`; codecs are baked |
| request `enable_audio` | `false` | `true` per audio-aware request |
| `FORCE_SW_AV1_DECODER` | empty | unchanged; the offline pack includes software AV1 |

The exact 3.2.1 source exposes audio through existing RT-VLM routes rather than
a separate audio endpoint:

- `GET /v1/models` reports the server-level `audio_support` boolean.
- `POST /v1/generate_captions` accepts `enable_audio`; the normal caption
  response may include `audio_transcript` only when an ASR path actually
  produced one. Native Omni understanding is reflected in generated content
  and must not be claimed as a separate transcript unless that field is
  present.
- `POST /v1/chat/completions` carries `enable_audio` into the same media query.
- CV-compatible stream metadata can carry `enable_audio`; plural stream
  registration still uses the ordinary `/v1/streams/...` lifecycle, followed
  by a caption request with the audio flag.

The two-key gate is intentional. A request with `enable_audio=true` is rejected
when the service did not start with audio capability. A service with audio
capability still ignores audio for requests that leave `enable_audio=false`.

## Offline codec preparation

Audit the exact VSS 3.2.1 source contract without network access:

```bash
python3 deploy/docker/thor-local/audio/codec_bundle.py source-audit
```

During an explicitly connected staging window, stage the packages. This is
additive and refuses to overwrite an existing bundle:

```bash
python3 deploy/docker/thor-local/audio/codec_bundle.py stage
```

`stage` never updates the lock. A future Noble update therefore fails closed
with an explicit lock-drift error. Refreshing the tracked lock is intentionally
a maintainer-reviewed code change: review all 59 signed resolutions, update the
single shared lock and the VIOS installer's expected lock digest together, then
rerun the adversarial codec suites. There is no automatic lock-refresh command.

Then verify and construct the immutable image without build networking or a
registry pull:

```bash
python3 deploy/docker/thor-local/audio/codec_bundle.py verify
docker build --network=none --pull=false \
  -f deploy/docker/thor-local/audio/Dockerfile.rtvi-vlm-codecs \
  -t cti-vss-rt-vlm:3.2.1-thor-audio-offline .
```

The image entrypoint always resets `INSTALL_PROPRIETARY_CODECS=false` and
sources the baked codec root. Startup cannot fall back to the released
downloader.

## Pinned local Omni snapshot

Model bytes are never downloaded by this lane. Stage the approved Hugging Face
snapshot outside the Git checkout at a full 40-character commit, then record
every regular file and hash in a protected manifest:

```bash
python3 deploy/docker/thor-local/audio/omni_snapshot.py lock \
  --model-dir /absolute/private/models/nemotron-omni-fp8 \
  --repository nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-FP8 \
  --revision FULL_40_CHARACTER_HUGGING_FACE_COMMIT \
  --output /absolute/private/models/nemotron-omni-fp8.manifest.json
```

The inventory accepts either a materialized regular-file tree or the canonical
Hugging Face `snapshots/<revision> -> ../../blobs/<identity>` layout. Canonical
links must remain inside the exact repository blob store and their resolved
bytes are hashed; all other links are rejected. This avoids a second full copy
of a 30B checkpoint without weakening byte verification. Unpinned revisions,
missing config/tokenizer metadata, missing SafeTensors, unsupported executor
architectures, and missing remote implementation Python are rejected. The
operator remains responsible for establishing the initial snapshot's
provenance from the named revision.

## Read-only gate and launch rendering

The 80 GiB `MemAvailable` gate is an additional admission floor, not a
performance or support claim. The default utilization is 0.45 and the gate
also enforces `available >= (utilization + 0.20) * MemTotal`, preserving the
documented fixed 20% unified-memory reserve. Increasing utilization therefore
raises the required available memory instead of weakening the reserve. The
model remains read-only; vLLM cache and initialization locks live in an
ephemeral, executable tmpfs selected by `VLM_RUNTIME_STATE_DIR` because vLLM
may execute compiled cache objects. NVIDIA publishes no exact
AGX Thor memory envelope for either distinct Omni identifier, so runtime
qualification must measure and may raise the floor.

```bash
export THOR_LOCAL_OMNI_MODEL_DIR=/absolute/private/models/nemotron-omni-fp8
export THOR_LOCAL_OMNI_MODEL_MANIFEST=/absolute/private/models/nemotron-omni-fp8.manifest.json
export THOR_LOCAL_OMNI_MODEL_ID=EXACT_ID_EXPECTED_FROM_RTVI_V1_MODELS

bash deploy/docker/thor-local/audio/thor-omni-audio.sh audit
bash deploy/docker/thor-local/audio/thor-omni-audio.sh launch-command
```

Both commands are read-only. `launch-command` prints a four-service,
`--no-build --pull never` Compose command but does not execute it. The overlay
uses `!reset null` to remove the default RT-VLM build definition, mounts the
model read-only, blanks NGC/Hugging Face/OpenAI/VIA credentials, pins batch,
process, and sequence counts to one, routes the agent to the local RT-VLM
provider, and enables the audio request flag in the agent, LVS, and alert path.

This lane is not qualified until all of the following are current: the codec
bundle is staged, the labeled image exists, the exact model snapshot exists,
the memory gate passes, `/v1/models` returns the configured id with
`audio_support=true`, and a tiny known-speech H.264/AAC fixture proves visible
content, audible content, audio-disabled control behavior, LVS, and alerts.
