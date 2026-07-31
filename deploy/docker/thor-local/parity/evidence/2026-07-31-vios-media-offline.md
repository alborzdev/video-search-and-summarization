# VIOS codec and audio lane — Thor evidence

Date: 2026-07-31
Scope: source audit, connected package staging from signed Ubuntu metadata, and
networkless image builds; no container lifecycle, image pull, API mutation,
credential use, or warehouse sample data.

## Outcome

The Thor source now has an immutable, startup-without-network path for both
`vss-vios-streamprocessing` and `vss-vios-nvstreamer`. It replaces the former
Dockerfile-time `apt` repair with a tracked exact 59-package ARM64 lock plus its
ignored byte-for-byte bundle,
networkless build declarations, and a runtime entrypoint that refuses either
additional-package flag.

The canonical lock SHA-256 is
`97701cf9abc00fdb3fec331abd13228b0d45ce347951a96456b9946882557c78`.
It is shared by VIOS and RT-VLM, and records exact versions, filenames, sizes,
archive hashes, and credential-free allowlisted Ubuntu source URLs. Connected
staging cannot update it; any future repository resolution drift fails closed.

`vios_media.py source-audit` currently passes the pinned source contracts for:

- B-frame detection, database propagation, decoder-mode selection and output
  encoder B-frame control;
- HEVC continuation-slice handling and Live555 H.265 RTP source/sink wiring,
  including DONL/DOND support associated with RFC 7798;
- H.264/H.265 NVIDIA and CPU parser/decoder/encoder paths;
- AAC transcode/remux, audio recording consumers, `includeAudio=true` RTSP
  subsessions, and A/V loop synchronization;
- Thor allowlists for H.264/H.265 and PCMU/PCMA/MPEG4-GENERIC;
- the exact VSS 3.2.1 signed-metadata ARM64 package identity set.

## Staged host evidence

- Host architecture: `aarch64`.
- Host `ffmpeg` exposes `libx264`, `libx265`, and AAC encoders; `ffprobe` is
  version `6.1.1-3ubuntu5`.
- The ignored canonical codec bundle contains exactly 59 ARM64 Debian archives
  (about 46 MiB) and matches the tracked lock byte-for-byte.
- `vss-vios-streamprocessing:3.2.1-thor-local` is staged as ARM64 image
  `sha256:3c9cd12bf4c1199def87215586e1fb5404cae41f1125b11414f0cfd94e1da0a4`
  (3,454,879,215 bytes).
- `vss-vios-nvstreamer:3.2.1-thor-local` is staged as ARM64 image
  `sha256:a0930533371a2235418aeec8811acda07b2244c97c7a6304873ac6472dbe5749`
  (3,456,581,520 bytes).
- Both derivatives were built with network disabled and have the immutable
  bundle/lock labels and fail-closed offline entrypoint required by preflight.
- Read-only health probes to `127.0.0.1:30888` (VIOS) and
  `127.0.0.1:31000` (NvStreamer) both return curl status 7 / HTTP 000; the
  services are stopped, so no media behavior was exercised.

## Current preflight result

Exit status: `0`.

`vios_media.py preflight` passes the source contract, exact lock, all 59 bundle
archives, and both image labels/entrypoints. This is reproducible staging proof,
not a live media qualification: VIOS and NvStreamer remain stopped and no codec
behavior is promoted to `passed_current`.

## Remaining qualification

Run the small custom-fixture matrix in `vios-codecs/README.md` against an
already-running profile. Required evidence is H.264 B-frame republish,
four-slice HEVC/RFC7798 RTSP consumption, H.264/H.265 media operations, AAC RTSP
republish, recorded AAC clip extraction, and an isolated
`use_software_path=true` run.

The large warehouse sample bundle is neither necessary nor used.
