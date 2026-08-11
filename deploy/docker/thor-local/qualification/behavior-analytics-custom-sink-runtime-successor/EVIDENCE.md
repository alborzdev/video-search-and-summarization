# Evidence

On 2026-08-11, Thor loaded a concrete `JsonlFileSink(Sink)` inside released image `nvcr.io/nvidia/vss-core/vss-behavior-analytics:3.2.1` at immutable ID `sha256:f3fd84f9c9f63b9d00298161929b71c73f36b301782d58bf810e0583843c9fa6`.

The runtime confirmed that the class was non-abstract and implemented `write`, `write_msg`, and `close`. A batch write used NVIDIA's `JsonBytesSerializer` for two ordered analytics event dictionaries, extracted and serialized both keys, and preserved a binary header. A single-message write preserved an opaque binary payload exactly. A protobuf write used NVIDIA's `ProtoBytesSerializer`, then decoded the retained bytes back into an `nv.Incident` with category `FOV Count Violation`, sensor `Camera_01`, and object `person-1`.

Destination routing produced three event JSONL records and one incident JSONL record. Output bytes are hash-retained, double-close was safe, the container exited zero without OOM or restart, the disposable container was removed, and both normal Behavior Analytics containers remained running with zero restarts.

The evidence intentionally does not claim built-in factory registration, production durability/throughput, or a network backend. It proves the advertised `Sink` extension contract and a working local implementation in the released Thor runtime.
