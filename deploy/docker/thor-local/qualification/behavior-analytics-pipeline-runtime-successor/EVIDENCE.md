# Evidence

On 2026-08-11, Thor ran `Analytics2DApp` from released image `nvcr.io/nvidia/vss-core/vss-behavior-analytics:3.2.1` at immutable ID `sha256:f3fd84f9c9f63b9d00298161929b71c73f36b301782d58bf810e0583843c9fa6`.

One isolated Kafka run exercised every input and stage in the advertised contract. Its 600 frames carried 4,417 objects; all 4,417 had valid boxes, tracker IDs, 0.99 confidence, and finite four-element embeddings added in memory to NVIDIA's compact tracked fixture. The app acknowledged a dynamic update and applied distinct baseline/updated checkpoints, changing `behaviorMaxPoints` from 200 to 3. It also reloaded Cartesian calibration version `qualification-kafka-2.0` in the main process and both workers.

The service returned 600 enhanced frames with 4,417 objects, FOV metrics on every frame, ROI metrics on every frame, 1,571 positive FOV metric entries, and 726 positive ROI metric entries. It emitted 971 behavior protobufs across five tracked identities and all three fixture sensors. Every behavior contained a transformed location and a finite 4-D embedding; the maximum retained trajectory length was exactly three.

The container exited zero without OOM or restart. Its isolated topics and disposable container were removed, and both normal Behavior Analytics containers remained running with zero restarts. All inputs, control configuration, implementation surfaces, and the probe are hash-locked. The 100 GB Warehouse sample bundle was not used.
