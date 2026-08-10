# Evidence

Status: passed current on Thor (`2026-08-10`).

The bounded native-browser transaction passed against NvStreamer live service
`2.1.0-26.05.4`. It established:

- isolated startup of the exact offline arm64 Thor-local NvStreamer image;
- deterministic 320x180, 10-fps H.264 baseline/AAC API upload and automatic
  live RTSP publication;
- native VIOS Media Streams UI selection of the executor-owned source;
- live WebSocket configuration plus real browser SDP and ICE negotiation;
- an unmuted live video track, ready state 4, service-default 1920x1080 first
  presentation and source-native 320x180 final presentation;
- decoded frames advancing from 2 to 26 across two sustained 12-frame deltas,
  with nondecreasing presentation and integer service timestamps;
- targeted HTTP 200 `PLAYING` status while the peer was active;
- exact HTTP 400 `InvalidParameterError` rejection when `peerId` was removed,
  with no retained peer resource;
- explicit native UI stop, stop-frame observation, video removal, WebSocket
  close, targeted peer absence, and an empty aggregate live-session result;
- zero external browser requests and exact Docker inventory, running-set,
  reserved-port, temporary-tree, and main-VIOS restoration.

The source contract and retained runtime configurations are digest-bound by
`fixture-contract.json`. The generated screenshot was used only as a bounded
runtime observation; its digest is retained but the image itself is not.

Retained immutable artifacts:

- `runtime-receipt.json`:
  `1d482e06ea5a2a59eb1d064ee475f67c4d6303461864b390f5847999f9d93fe4`;
- `official-runtime-evidence.json`:
  `01a6f1e7e37445235256218ea9d87268d1b8fefbbc5d3766b789a93951d8009c`;
- `fixture-contract.json`:
  `b8b1436835a8db5f7cfc29f8eb12cda959e3df1056b9a3003123a44f3eaffc89`;
- `execute.py`:
  `6ab593ae40042dc8e843aab18a9c6533dd54c70e691af286cf0f863ccd98f26d`;
- `harness.mjs`:
  `3935cc7f234c3212916eb470944ba18b5b29b6b497214982a06ab804eadfa6a4`;
- bound capability oracle:
  `bcce967d3f8c6dedd4be5d0da3afc586db751cd5c74abafca87e319da85048f8`.

No WebRTC credentials, peer IDs, media-session IDs, SDP, or ICE candidates are
retained. The transaction did not invoke either user-gated sample-stream add or
the user-gated VSS Agent generation endpoint.
