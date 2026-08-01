# Sparse4D entry-oracle evidence boundary

## Locked existing inputs

The inert planner fail-closes on raw SHA-256 drift in the existing Sparse4D validator, launcher, environment renderer, offline patcher, compose overlay, Prometheus configuration, advertised-entry plan, wave-7 inventory, and parity manifest. `contract.json` contains the exact nine path/digest pairs. It also canonical-hash binds the two live advertised-entry oracles and requires them to remain `open_unexecuted`, sample-free, and without runtime evidence.

## What passing validation means

The strict schema and semantic validator establish internal consistency only. They require exact media/calibration/model/anchor identities; Thor capacity and isolation gates; model-loaded versus model-used proof; four-camera local detections; fused 3D/BEV outputs; cross-camera correlations; health, throughput, resource, latency, and stream-growth measurements; and exact namespace-owned cleanup.

All capture IDs must be globally unique and timestamped inside the authorized run window. Model event hashes must equal their admitted asset hashes, and each loaded capture must precede its used capture. Fused source tracks must exist in per-camera observations, and the fused and correlation evidence must each cover the exact four-camera set. Every required service must be healthy. Throughput frames must agree with `fps * sample_seconds` within the larger of one frame or 5%; latency percentiles must be monotonic. Cleanup must remove all and only created stream/output resources.

Passing does not authenticate a producer, replay a capture, authorize lifecycle actions, or admit anything into official state. A reviewer must still inspect the digest-addressed artifacts and authorization context before a separate admission decision.

## Prohibited inference

This package contains no runtime receipt and proves neither advertised behavior today. It does not use the Warehouse sample, stage assets, prepare a lane, start or stop containers, load models, read streams, produce detections, or clean runtime resources. The official Sparse4D advertised-entry oracles remain open.
