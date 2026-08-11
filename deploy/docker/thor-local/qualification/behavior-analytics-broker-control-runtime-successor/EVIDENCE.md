# Evidence

- Behavior image: `vss-behavior-analytics:3.2.1`, exact arm64 image ID retained in the receipt
- Brokers: Kafka 8.2.0, Redis 8.6.2, and disposable Mosquitto 2.0
- Control path per backend: startup snapshot, direct update, success acknowledgement, atomic main/worker application
- Configuration identity: distinct hashed baseline (`behaviorMaxPoints=200`) and revision (`3`) checkpoints
- Calibration identity: distinct baseline and backend-versioned Cartesian update hashes
- Input per backend: 300 frames from the compact repository fixture, not the excluded Warehouse bundle
- Kafka output: 300 enhanced frames, 471 behaviors, all three cameras
- Redis output: 240 enhanced frames, 127 behaviors, all three cameras
- MQTT output: 298 enhanced frames, 469 behaviors, all three cameras
- Post-update semantics: maximum trajectory length 3 on every backend
- Post-calibration semantics: every returned enhanced frame had FOV and ROI metrics
- Exit integrity: all three Behavior containers and Mosquitto exited 0 without OOM or restart
- Cleanup: disposable containers, Kafka topics, Redis streams, and MQTT broker are absent; normal Behavior services remain running

The receipt retains no raw generated reference IDs; it stores only their SHA-256
identities. It also locks the exact source/sink factories and implementations,
app wiring, per-backend configs, fixture and calibration, checkpoint identities,
output counts, container log digests, infrastructure identities, and cleanup
postconditions. No VSS Agent generation, external request, main VIOS mutation,
main RT-CV mutation, or 100 GB Warehouse sample occurred.
