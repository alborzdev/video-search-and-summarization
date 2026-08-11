# Evidence

Overlay 38 adds official row 331, `always-on lifecycle`, using the retained
`realtime-alert-always-on-runtime-successor` receipt. One declared local rule
started exactly once; duplicates before and after an Alert Bridge restart were
inert. Restart replay stopped the surviving RT-VLM worker and created one
replacement, while camera removal left zero workers and removed the owned
stream. Exact unrelated runtime and running-container state were restored.

Overlay 37 adds official row 330, `rule replay`, using the retained
`realtime-alert-rule-replay-runtime-successor` receipt. A live local RTSP rule
was persisted and replayed twice. Both replays preserved rule identity,
creation time, immutable configuration, and RT-VLM stream identity while the
public API, Elasticsearch, and RT-VLM each exposed exactly one matching
object. Exact unrelated state was restored and no Agent `/generate` call was
made.

`matrix.json` binds seventy-eight exact VSS 3.2.1 advertised candidate rows in the selected Metadata500 ledger to schema-valid live Thor receipts. Overlay 38 adds index 331: the configured always-on rule converged to one RT-VLM worker across duplicate events and Alert Bridge restart recovery, then cleanly stopped. Overlay 37 adds index 330: two successful replay cycles preserved one rule's identity, configuration, creation time, and single RT-VLM stream. Overlay 36 added index 169: the deployed Alerts View/Manage surface and a complete create, persist, render, and delete rule lifecycle using one UI-created temporary RTSP sensor. The browser submitted the canonical VIOS sensor-stream URL already registered in RT-VLM despite a different live-catalog proxy URL, produced no console error or Agent generation call, and removed all owned rule, sensor, incident, temporary-media, and stream state. Overlay 35's indices 60–63 and all earlier receipts remain unchanged.

Overlay 34 adds index 208. The released Behavior Analytics image instantiated `SinkKafka`, `SinkRedisStream`, and `SinkMQTT` through the real factory and routed frames, behaviors, events, incidents, anomalies, cluster, and space-utilization through each backend. All 21 records were observed at their exact destination, keys and headers were retained, payload bytes matched across backends, and all protobufs decoded to the expected identities. Namespaced records and disposable containers were removed while normal services remained running.

Overlay 33's pipeline evidence used one released-image `Analytics2DApp` run in which 4,417 objects across 600 frames all carried valid boxes, tracker IDs, and finite 4-D embeddings. Live config changed `behaviorMaxPoints` from 200 to 3, Cartesian calibration reloaded, and the service returned all 600 enhanced frames plus 971 behaviors. Every behavior retained an embedding and transformed location; 1,571 positive FOV and 726 positive ROI metric entries proved the metrics stages. The container exited zero, isolated topics were removed, and normal services stayed running. The deterministic 4-D vectors prove continuity, not model quality or production dimensionality.

Overlay 32's retained custom-sink evidence proves a concrete `Sink` implementation with batch JSON, single opaque bytes, protobuf data, keys, binary headers, routing, and idempotent close without claiming a new built-in factory key.

Overlay 31's retained events/incidents evidence covers all four directional ROI/tripwire event forms plus proximity, restricted-area, confined-area, and FOV-count incidents. Its FOV incidents were ongoing at capture, so expiry/completion remains explicitly unclaimed. The Behavior Analytics evidence still excludes 3D detector/MV3DT runtime.

Overlay 30's retained space-utilization evidence covers all six advertised metric families, three calibrated zones, both layout families, and arithmetic consistency.

Overlay 29's retained embedding evidence exercised both sliding-window and SDT through the released Fusion Search application, including SDT's graceful pending-candidate flush.

Overlay 28's retained broker-control evidence accepted and applied namespaced configuration and calibration revisions over Kafka, Redis, and MQTT with auditable prior/new checkpoint identities.

Overlay 27's retained dynamic-control evidence passed all 24 NVIDIA dynamic-configuration scenarios and all seven dynamic-calibration scenarios, including accepted-update acknowledgements, partial filtering, invalid/stale rejection, atomic file landing, watchdog application, controller snapshot, empty response, no-response timeout fallback, image/Cartesian/geo implementation selection, and the immutable existing-type boundary.

Overlay 26's retained 2D run processed 20,000 frames and 171,436 objects across three calibrated cameras, decoded 38,286 behavior records, 121 directional ROI/tripwire events, 24,924 incidents, 1,778,483 trajectory points, positive FOV/ROI occupancy counts, and 426 proximity plus cluster entries.

Overlay 25's retained API run covered 56 Video Analytics operations, 40 non-empty data-bearing GETs, eight positive and eight adjacent-negative POST workflows, dynamic config/calibration, and optional Kafka behavior. Its loopback VA-MCP run advertised nine tools and exercised all eight read-only tools with header sessions, real sensors, incidents, FOV, speed, and analysis results while preserving Docker and VST state. No `react_agent`, VSS Agent `/generate`, external request, or Warehouse sample was used. External Slack and row 423 audio recording remain unclaimed; the row-379 Thor JPEG decoder defect remains outside that passing P6-PPM-scoped claim.

This is a runtime-evidence overlay, not a trusted canonical admission receipt. Canonical candidate state remains explicitly unchanged and visible in every matrix row.
