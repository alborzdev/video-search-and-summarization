# Runtime evidence — 2026-08-10

The runtime receipt is `runtime-receipt.json` (SHA-256
`c850adad8fe65bfe4a40741fa24f86de3abbc80baf8de54cf903c034bfe6f93c`).
The canonical capability wrapper is `official-runtime-evidence.json`
(SHA-256
`a4bfd3a6562f95214624f7f84f8115162031285dc231b3f2e168ecb7233addab`).
It was captured from image
`sha256:b3e5b92fa2546e9b69a3dba7cac324ce36a3cce65f2e0d61ad41a8a84a74a563`,
labeled with codec package set
`ed28389b37a2d74a484251e874b4a131e9eb2a8350b4013ba0c209154bfdf3b4`.

The first isolated CPU snapshot failed because
`/usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstlibav.so` could not load
`libbs2b.so.0`. A read-only bind-mount proof changed the same request from HTTP
500 to HTTP 200 and produced a valid 640×360 JPEG. The immutable bundle was
then extended from NVIDIA's exact 59 upstream packages to a 63-package Thor
closure with `libbs2b0`, `libcdio19t64`, `libsbc1`, and `libsidplay1v5`.
Both VIOS derivative images were rebuilt using `--network=none`, and a scan of
every retained GStreamer plugin reported zero unresolved libraries without any
host-library mount.

Observed current runtime results:

- H.264 input: High profile, 640×360, 15 fps, `has_b_frames=2`, AAC 48 kHz.
- HEVC input: 120 pictures, four slices per picture (120 first + 360
  continuation slices), AAC 48 kHz.
- Default path: valid 640×360 snapshots for non-B H.264, two-B-frame H.264, and
  HEVC; both B-frame H.264 and HEVC decoded 120 frames over RTSP/TCP.
- Software path: logs explicitly show hardware decoders skipped, software
  decoder+encoder selected, `x264enc`/`x265enc` at 1200 kbps with zero B-frames,
  and AAC linked through `audioencoder` to the muxer.
- Software outputs: H.264 measured 1,051,572 bps and HEVC measured 1,228,692
  bps; both were 640×360 at 12 fps, zero B-frames, and exposed AAC 48 kHz over
  RTSP when `includeAudio=true` was requested.

The direct two-B-frame H.264/AAC file exposes only video over RTSP. Non-B-frame
H.264/AAC and HEVC/AAC both expose audio, and the software-transcoded H.264
substitute exposes audio. This limitation is not generalized to VIOS audio or
NvStreamer audio as a whole.

No warehouse sample data, external service, main VIOS configuration change, or
main VIOS sensor addition occurred. The NvStreamer-to-VIOS recording handoff
remains behind the exact approval gate `approve RT-CV sample stream add`.
After receipt capture, all six isolated NvStreamer stream IDs were deleted
through the file-delete API, the sensor list was empty, the owned qualifier
container was stopped and removed, and the two exact temporary trees were
deleted. Those postconditions are locked by the canonical wrapper.
