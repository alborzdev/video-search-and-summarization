# Wave-five evidence boundary

## Exact accounting

- Gap-plan entries: 87
- Previously selected candidates: 57 (8 + 21 + 23 + 5)
- Entries without a candidate before this wave: 30
- Selected here: 6
- Total entries with isolated candidates: 63
- Entries left without a candidate executor: 24

The selected literals are `B-frame handling`, `HEVC multislice/RFC7798`,
`H.264/H.265`, `audio recording`, `audio RTSP republish`, and `CPU multimedia
support`.

## What is observed

The executor verifies exact digest-locked source and packaging contracts for:

- H.265 slice parsing, B-frame state propagation, the low-latency decoder guard,
  and explicit zero-B-frame software output settings;
- guarded HEVC continuation-slice detection, same-access-unit pacing, H.265
  DONL/DOND declarations, and discrete framer/RTP sink selection;
- the exact Thor H.264/H.265 allowlist and matching parser, framer, RTP sink,
  hardware encoder, and software encoder branches;
- the `disableAudio`/AAC selection path, remux audio consumer, and AAC
  transcode-to-mux path;
- `includeAudio=true`, `MediaTypeAudio`, and shared A/V loop synchronization;
  and
- libav/x264/x265 software selection, the exact 59-package ARM64 codec lock,
  and two immutable networkless VIOS derivative Dockerfiles.

The executor parses only bounded checked-in inputs and emits deterministic JSON.
Its policy and result schemas reject live-state promotion or runtime evidence.

## What is not observed

No VIOS or NvStreamer process is contacted or started. No codec fixture is
decoded, encoded, republished, or recorded. No RTP packet, multislice access
unit, AAC track, extracted clip, or isolated CPU pipeline is observed.
Therefore all six source-plan entries and their runtime oracles remain
`open_unexecuted`; none may be promoted in the acceptance, official-capability,
oracle, or runtime-lane ledgers.

The large optional Warehouse sample bundle is neither necessary nor used.
