# NvStreamer synchronized playback evidence

The current retained execution passed on Thor on 2026-08-10:

- raw receipt SHA-256:
  `56289140451822cf97202eff3b2cb81fa34116bcda4231ca3f5d9a2e211a4663`;
- official evidence SHA-256:
  `eb13cebb154ac082803143e01e08df978991f40e1d15a5a0265d9f03aa8bd07e`;
- exact fixture: 793,162 bytes, SHA-256
  `211900643528d726b65e7e2ac6648dcf4b34bb53040e923d90bd3d42427bff0a`;
- first client held for 3,039 ms with zero shared-clock markers;
- after the second client joined, both decoded their first frame in 1,210 ms
  with 0 ms observed completion skew;
- NvStreamer emitted exactly one positive shared `m_baseGstTime`;
- exact prior Docker inventory/running set restored and all ports released.

`official-runtime-evidence.json` is bound to the exact fixture, executor,
runtime receipt, promoted ledger row, and canonical capability-oracle SHA-256.

The retained receipt proves all of the following:

- two byte-identical H.264 files at 30 fps, zero B-frames, and keyint 30;
- `nv_streamer_sync_file_count=2` in the exact derived runtime config;
- the first RTSP client remains blocked while alone;
- the second client releases the barrier;
- both clients decode one frame with at most 250 ms completion skew;
- exactly one positive shared `m_baseGstTime` marker;
- no warehouse sample, main-VIOS sensor, RT-CV stream, or Agent call;
- exact prior Docker/running-set restoration and all ports released.
