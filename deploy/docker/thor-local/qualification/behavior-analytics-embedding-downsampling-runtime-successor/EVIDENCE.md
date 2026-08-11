# Evidence

On 2026-08-11, Thor ran the released `nvcr.io/nvidia/vss-core/vss-behavior-analytics:3.2.1` image at immutable image ID `sha256:f3fd84f9c9f63b9d00298161929b71c73f36b301782d58bf810e0583843c9fa6` through the Fusion Search application.

Both tests sent 13 Kafka `nv.VisionLLM` protobuf records for one sensor: twelve identical unit embeddings followed by an orthogonal novel embedding. Sliding-window emitted four records (`0, 1, 2, 12`), proving neighbour-window compression and novel-transition retention. SDT emitted three (`0, 11, 12`), proving trend compression, transition handling, and graceful flush of its pending final candidate. Both containers exited zero, were not OOM-killed, and had zero restarts.

All ten qualification topics and both disposable containers were removed. The normal `vss-behavior-analytics` and `vss-behavior-analytics-thor-candidates` containers remained running. The receipt and exact implementation/configuration inputs are hash-locked and verified by strict JSON Schema.

This evidence binds only index 207. It makes no claim for the broader complete behavior pipeline, all output families on all three sinks, embedding quality, or scale/performance.
