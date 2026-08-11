# Evidence

The retained 2026-08-10 Thor run used VSS 3.2.1 NvStreamer service
`2.1.0-26.05.4` from the exact installed ARM64 image. Upload, UI upload, and a
local-mounted H.264/AAC file all became online streams with automatic RTSP
output. A direct probe observed H.264 320×180 video and AAC 48 kHz audio; a
6,804-byte MJPEG snapshot decoded; and Chromium observed a live WebRTC track
whose clock advanced. A nine-byte invalid file returned HTTP 400.

All three owned streams were deleted, owned media and sensors were absent,
the prior Docker inventory/running set matched exactly, and all ports were
released. Main VIOS and RT-CV were not mutated; no Warehouse sample or VSS
Agent call occurred.

Artifact locks:

- contract: `aa7ef364bcfb0af1634e49373262b39fe2bb72f90de9aebe609769c4d04a50f5`
- receipt schema: `70839a566a82f65adea80918803cc4bed861708292720473e9707eaf288f8d3f`
- runtime receipt: `be51bda9bfdc159836420d12e593e5d86e83d2c6f19318f06b93d9e83d829766`
- compiler: `8b7bb2ed08251ab85aaf8dfdf10320333aba94b41523b0836c0f07dab874227d`
