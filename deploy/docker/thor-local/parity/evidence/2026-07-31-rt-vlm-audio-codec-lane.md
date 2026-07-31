# RT-VLM audio/codec static lane evidence — 2026-07-31

## Source baseline

- Official stable tag: `v3.2.1` at
  `7640d917047cf7b0fd3085eefb8282754b56bc94`.
- Released RT-VLM image selected by the stable Compose:
  `nvcr.io/nvidia/vss-core/vss-rt-vlm:3.2.1`.
- Local ARM64 image id:
  `sha256:5403e0c8fa8b149e7ad15ab1b063b78d610e7a50297dba6ca550ac5cc5ef9504`.
- Existing Thor source derivative:
  `cti-vss-rt-vlm:thor-local`, ARM64 id
  `sha256:4a36610edd536525e755ffb53d4fb9b5f34ab480eb9aace2a487094456c4ccea`.
- Both images use `/opt/nvidia/rtvi/start_rtvi_vlm.sh`. The existing derivative
  overlays current source but has no offline-codec label or staged codec proof.
- The existing image-only Qwen snapshot is locally staged at revision
  `9cdc6310a8cb770ce18efaf4e9935334512aee45`; its matching
  `cti-vss-qwen3-vl` container exists and was stopped during this audit. It is
  not an audio-capable Omni checkpoint.

The exact stable code/config surface was inspected in:

- `deploy/docker/services/rtvi/rtvi-vlm/rtvi-vlm-docker-compose.yml`;
- `services/rtvi/rt-vlm/src/api_models/captions.py`;
- `services/rtvi/rt-vlm/src/api_models/live_stream.py`;
- `services/rtvi/rt-vlm/src/api_models/nim_compat.py`;
- `services/rtvi/rt-vlm/src/server/rtvi_vlm_server.py`;
- `services/rtvi/rt-vlm/src/server/rtvi_stream_handler.py`;
- `services/rtvi/rt-vlm/src/vlm_pipeline/vlm_pipeline.py`;
- `services/rtvi/rt-vlm/src/vlm_pipeline/video_file_frame_getter.py`; and
- `services/rtvi/rt-vlm/src/models/vllm_compatible/vllm_compatible_model.py`.

The audio-specific defaults are `VLM_MODEL_SUPPORTS_AUDIO=false`,
`VLM_TRUST_REMOTE_CODE=false`, `INSTALL_PROPRIETARY_CODECS=false`,
`FORCE_SW_AV1_DECODER` empty, and request `enable_audio=false`. The native lane
requires `VLM_MODEL_TO_USE=vllm-compatible`, both model flags true, and the
request flag true. Audio is carried by `GET /v1/models` (`audio_support`),
`POST /v1/generate_captions`, `POST /v1/chat/completions`, and stream metadata;
there is no separate native-audio route.

## What is now source-complete

The new Thor-owned lane supplies:

1. a source-locked parser for the 59 ARM64 package identities in the VSS 3.2.1
   non-root codec installer (source SHA-256
   `20f1c024c11405ed88192ed9e26a2841348249b8c4238bccd5cce355f7051238`),
   with package-set SHA-256
   `c34db3c88287c8c049190bafdc0096d91f70bdf14a3b0ffdcc30c01fbc11f44f`;
   and one tracked shared exact-byte lock (SHA-256
   `97701cf9abc00fdb3fec331abd13228b0d45ce347951a96456b9946882557c78`)
   whose versions, filenames, sizes, hashes, and allowlisted URLs must match
   signed staging exactly;
2. additive connected staging through signed Ubuntu Noble metadata and an
   exact HTTPS `ports.ubuntu.com` allowlist that records SHA-256, Debian
   package, version, architecture, size, filename, and URL for every package;
3. frozen verification plus an immutable RT-VLM derivative whose build has no
   network and whose startup entrypoint cannot invoke the mutable codec
   installer;
4. an exact, read-only local model snapshot inventory pinned to the full Hugging
   Face Git revision for
   `nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-FP8`;
5. an opt-in Compose overlay that erases the normal source build, mounts only
   the local model, blanks external provider credentials, uses
   `vllm-compatible`, enables `VLM_MODEL_SUPPORTS_AUDIO` and remote code, pins
   concurrency to one, and propagates the per-request audio flag through agent,
   LVS, and alerts; and
6. a read-only host/model/image/memory/mutual-exclusion gate that only renders
   a `--no-build --pull never` command.

The default Qwen/OpenAI-compatible Thor lane is not modified and remains
image-only. The shared ignored codec bundle is now staged with all 59 locked
ARM64 archives, and the networkless derivative
`cti-vss-rt-vlm:3.2.1-thor-audio-offline` is staged as ARM64 image
`sha256:f20843fef63fb7296116ce1bf25a118e6c023350e970d8d3410ec58f36286a4b`
(14,175,440,526 bytes). Its owned codec overlay is isolated at
`/opt/nvidia/rtvi/thor-codecs`, so it does not overwrite directories owned by
the released base image.

## Codec versus understanding result

The codec pack is an ordinary media decode prerequisite. It includes the
FFmpeg/GStreamer support used for MP4/AAC, MP3, FLAC, H.264, H.265, VP9, and
software AV1, but cannot create semantic audio capability in Qwen-VL. Native
Omni understanding is a separate, mutually exclusive lane requiring both
`VLM_MODEL_SUPPORTS_AUDIO=true` and request `enable_audio=true`.

The source also contains an ASR process abstraction, but the stable Omni path
skips that process and supplies decoded PCM directly to vLLM. Therefore native
Omni output must not be reported as a discrete `audio_transcript` unless the
response actually includes that field.

## Current blockers (observed, not inferred away)

- No approved Nemotron/Qwen Omni snapshot was found locally.
- `MemAvailable` was about 33 GiB of 122 GiB and swap was zero; the conservative
  80 GiB pre-start floor therefore fails.
- No versioned tiny known-speech H.264/AAC fixture exists.
- No current RT-VLM, LVS, alert, or agent runtime proof exists for this lane.
- NVIDIA's stable documents do not publish an exact AGX Thor memory envelope
  for the 30B FP8 Omni model; the 80 GiB floor is deliberately conservative
  admission policy pending measurement, not a qualified capacity claim.

The codec packages were staged from signed Ubuntu metadata and the derivative
was built with Docker build networking disabled. No container was started,
stopped, or created; no image was pulled, no credential was read, and no cloud
inference or model download was used.

## Static verification

`deploy/docker/test-scripts/test-thor-audio-offline.sh` (11 tests) proves the exact stable
source digest/package count, snapshot tamper detection, absence of runtime
download tools, both audio gates, networkless image contract, removed Compose
build definition, read-only model mount, blank provider credentials, one-way
provider switch, and agent/LVS/alert audio propagation. Static success is not a
runtime qualification result.
