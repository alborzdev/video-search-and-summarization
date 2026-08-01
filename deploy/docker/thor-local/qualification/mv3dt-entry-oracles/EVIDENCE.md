# MV3DT entry-oracle evidence boundary

## Static identities

The inert planner fail-closes on raw drift in nine existing inputs:

| Existing input | SHA-256 |
|---|---|
| custom-input validator | `09c3497f8cd7302d871cf528c09467273ac6a3717535f772e05d0eb2e63d6aff` |
| Thor MV3DT launcher | `e697a2a41a146bc84b701558918af1f24d10ba10cd4ffc05d9fd3d9818080499` |
| camInfo generator | `910996b10ef5e135ba2752b7286841dce03bf20679f62e0ae4c28bbb682bb675` |
| FOV topology generator | `bc64ddf385f717793d6683eb4b57989067462c6a0f638ee46e9d7243285288fc` |
| advertised-entry plan | `2fc3a8fbcbfd8afa62e657cf0d4b3f34d568294b089bd71f0f87354e9196745c` |
| parity manifest | `1f56d63437bd7742cf7488b9bd85b25fc886cdaf39a3c2b46aabecbc6b7201ce` |
| Thor MV3DT compose overlay | `a040c05a062d747e6cf02762e4b82210833db50c4c37afae556bd78b536a9a5b` |
| MV3DT tracker configuration | `1053cc0a13f58b465cf28c5b59c65aa85f4feeb7d25c6aa7272d876f02a54b96` |
| four-camera DeepStream configuration | `6f1a5b76c26a0e8aa0ad42e3ab2327b1acf0fa1c8e66dcafefc2e1b6965db80d` |

It also canonical-hash binds the four required advertised-entry oracles and requires every live oracle and entry to remain `open_unexecuted` with empty runtime evidence.

## What the schemas mean

The schemas define the minimum machine-readable record that a future, separately authorized custom-data run would need. Passing validation means a receipt is internally consistent with the exact-four admission and semantic observation rules. It does not authenticate the producer, independently replay the message captures, or admit evidence into a live ledger. Reviewers must still inspect the digest-addressed source artifacts and the authorized runtime context before any separate admission decision.

The receipt deliberately distinguishes:

- per-camera local detections on `mdx-raw`;
- fused global tracks on `mdx-bev`;
- time-ordered BodyPose model load before actual inference use;
- same-global-ID transitions across distinct cameras that are members of the admitted directed topology edges;
- executor-created resources from preexisting operator resources.

This prevents configuration presence, container health, a model file on disk, or cleanup intent from being substituted for semantic runtime evidence.

## Prohibited inference

The package contains no runtime receipt and proves none of the four advertised behaviors today. It does not use the Warehouse sample, start or stop services, load RT-DETR or BodyPose3DNet, consume MQTT/Kafka, or generate detections. The official advertised-entry oracles remain open.
