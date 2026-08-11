# Evidence

On 2026-08-11, Thor ran the released `nvcr.io/nvidia/vss-core/vss-behavior-analytics:3.2.1` image at immutable ID `sha256:f3fd84f9c9f63b9d00298161929b71c73f36b301782d58bf810e0583843c9fa6`.

The source-locked base `Analytics2DApp` receipt decoded 121 event protobufs: 56 ROI entries, 53 ROI exits, six tripwire-in events, and six tripwire-out events. It also decoded 24,924 incident protobufs: 14,786 confined-area violations, 10,043 restricted-area violations, and 95 proximity violations.

The supplemental FOV run used the same tracked 2D calibration and compact playback fixture. It enabled FOV-count incidents for `Person` with an object threshold of one and 0.1-second incident/expiration thresholds, then published 300 Kafka `nv.Frame` protobufs. The application decoded 18 active `FOV Count Violation` incidents across `Camera_01` and `Camera_02`. Every incident had one contributing object ID, positive time bounds, and a start no later than its end. None had expired during the observation window, which is retained explicitly as `ongoing_at_capture` rather than misrepresented as completion evidence.

The disposable FOV container exited zero without OOM or restart. Its isolated Kafka topics and container were removed, and both normal Behavior Analytics containers remained running. All inputs, implementation surfaces, prior evidence, and the probe are hash-locked. No external request, VSS Agent generation, RT-CV/VIOS mutation, or Warehouse bundle was used.
