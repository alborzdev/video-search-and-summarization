# Evidence

The retained 2026-08-10 Thor run used image
`sha256:b3e5b92fa2546e9b69a3dba7cac324ce36a3cce65f2e0d61ad41a8a84a74a563`,
which remains installed locally as `vss-vios-nvstreamer:3.2.1-thor-local`.
It proved:

- H.264 High-profile input with exactly two B-frames decoded 120 frames over
  RTSP/TCP and produced a valid snapshot;
- HEVC with four slices per picture (120 pictures and 360 continuation slices)
  decoded 120 frames through the RFC7798 RTSP path and produced a snapshot;
- hardware and CPU/software H.264 and H.265 paths produced decoded media, with
  software outputs at zero B-frames;
- non-B-frame H.264, HEVC, software H.264, and software H.265 republished AAC
  at 48 kHz over RTSP.

The direct H.264+B-frame+AAC path lost audio; the same run proved the documented
local software-transcode substitute removes B-frames and retains AAC. This
bounded limitation does not invalidate the broader audio-republish row. Six
owned streams, the isolated container, and both temporary trees were removed;
the isolated sensor list was empty and main VIOS was unchanged. No Warehouse
sample or VSS Agent call occurred. Audio recording is explicitly not claimed.

Artifact locks:

- contract: `e626886e20fbdf4b473bf29fdd697af9c0652b3ee370ff9e4246cc5eb5acdf0c`
- receipt schema: `557ab4ef19eb22eed44ba87b2e3ece7dfeb43ec7adf4749fe8a7f63da0d866c3`
- runtime receipt: `46dad305ff28d2a445f8f9f9f2ec9d86b2685bb13553dddd3a0f0bc6142c4aba`
- compiler: `24187feb4b991dbc991a56e647f991381053a7f22bfc89d23893fc6e2977e233`
