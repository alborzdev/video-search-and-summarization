# Evidence

Fresh 2026-08-11 Chromium/Playwright runs passed against VIOS service
`2.1.0-26.05.4` in VSS 3.2.1. Live WebRTC completed signaling, reached
`PLAYING`, decoded 25 frames with a sustained 12-frame delta, exposed a live
unmuted video track, and closed its WebSocket/session. Replay WebRTC completed
signaling, decoded 53 frames, and retained positive frame deltas after API
seek, UI seek, and an intentionally unsupported action. The two supported
seeks returned HTTP 200; the negative returned the expected HTTP 501 without
stopping playback.

The receipts prove distinct live and replay WebSocket routes, timing controls,
session lifecycles, and teardown. Both container/running inventories and main
VIOS state were restored. Session identifiers, SDP, ICE, and media payloads are
not retained. No VSS Agent call, main configuration mutation, RT-CV mutation,
or Warehouse sample access occurred.

Artifact locks:

- contract: `7267692c470b5cadb983fe83ea1d22d7f5c0382f3faab1a367c6d58c1e816220`
- receipt schema: `e658170e383de67f214a1173d2174272dfdaff94c1d32cb03c6cd2555bae276a`
- runtime receipt: `dc9df69e579f17de8494e6c23f9ad4f10677e40bb3f4a5039ad3b604f6815585`
- compiler: `9ad4842a03b1d066006a10902c0840239ffbc2031a1be2d3a0070a2dca324194`
