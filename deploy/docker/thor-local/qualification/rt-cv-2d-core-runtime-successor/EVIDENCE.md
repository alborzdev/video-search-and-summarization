# Evidence

The retained Thor run passed in 129.599092 seconds with Docker using the
required `cgroupfs` driver. The isolated RT-CV container used the exact cached
VSS 3.2.1 arm64 image and the effective runtime configuration reported:

- `HARDWARE_PROFILE=AGX-THOR`;
- tracker `compute-hw=2`;
- source `low-latency-mode=0`;
- `max-batch-size=16`;
- `maxTargetsPerStream=32` (16 × 32 = the VPI limit of 512);
- `visualTrackerType=2`; and
- `vpiBackend4DcfTracker=2`.

The finite local-file lane decoded eight qualifier-only protobuf frames with
39 detections, including `Person` and `Pallet`, seven repeated track identities,
and finite 1,152-dimensional embeddings. The loopback RTSP lane decoded eight
frames with 51 detections, the same class coverage, eight repeated track
identities, and finite 1,152-dimensional embeddings. Both lanes reported one
active stream with positive FPS/frame counters and finite latency, then passed
their exact add/remove lifecycle and returned to zero streams.

`/live`, `/ready`, `/startup`, and `/metadata` returned HTTP 200. The active
Prometheus response contained `fps_metrics`, `frame_number_metrics`,
`latency_metrics`, `memory_metrics`, `stream_count`, and
`utilization_metrics`. The clean post-restart RTSP run contained zero
`VPI_ERROR` messages, zero automatic restarts, and no OOM event.

Cleanup removed every qualifier container, publisher, Kafka topic, consumer
group, and temporary file. The main `vss-rtvi-cv` snapshot was identical
before and after with zero streams, and the three intentionally paused
workloads remained stopped. No network download, VSS Agent call, main RT-CV
stream mutation, VIOS stream mutation, credential, raw broker message, raw
camera identity, raw URL, or raw vector was used or retained.

Artifact locks:

- contract: `e6959a5733b55a3e47c2adc575455719b6e88166ba897a1b1f74608c72fa0b1e`
- receipt schema: `f394594996c200893047622a89224505822c89dea5f9a286841d8d8cd668ffe4`
- runtime receipt: `c3739e024b56f0a9d6166c3a92b9e138e330b885a4a531d80b92c3937885b164`
- executor: `c9bbf58b566b32861e5bfc8ad3507ed2091ffb70e8c95f42fb57a3dc5e44b8cd`
