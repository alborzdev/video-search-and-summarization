# Evidence

On 2026-08-11, Thor ran `Analytics3DApp` from the released `nvcr.io/nvidia/vss-core/vss-behavior-analytics:3.2.1` image at immutable ID `sha256:f3fd84f9c9f63b9d00298161929b71c73f36b301782d58bf810e0583843c9fa6`.

The probe published 90 Kafka `nv.Frame` protobufs for `bev-sensor-1`; 89 non-empty frames received a deterministic in-zone pallet. The service emitted 9 `SpaceUtilization` protobufs across `buffer_zone_1`, `buffer_zone_2`, and `buffer_zone_3`. Positive observations covered every advertised metric family: occupied up to 1.21 m², free up to 13.49 m², total up to 13.49 m², utilization ratio up to 0.09, 5–12 extra pallets, and 5–12 m² utilizable free space. Every output contained free and utilizable layout geometry. `free + occupied = total` held within 0.01 m² and ratio consistency within 0.00011.

The container exited zero without OOM or restart. Its seven isolated Kafka topics and disposable container were removed, while both normal Behavior Analytics containers remained running. All inputs and implementation surfaces are hash-locked.

This evidence excludes the 100 GB Warehouse sample bundle, physical cameras, RT-CV 3D/MV3DT inference, and scale/performance claims.
