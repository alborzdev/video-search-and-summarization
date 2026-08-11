# Evidence

The retained 2026-08-10 ARM64 Thor run mounted the NVIDIA Alert Bridge
WebSocket source read-only and performed a real loopback WebSocket upgrade. It
observed `pong`, one `alert`, and `status` in order. Redis fields and message
identity matched, the callback completed before acknowledgement, and the
consumer group had zero pending entries. A non-JSON frame produced no
application response and the socket remained open.

After disconnect, active connections were zero. The isolated listener and
container, both owned streams, and the owned consumer group were absent;
non-owned Redis keys and the normal alert service state matched pre-state.
Redis remained healthy. External Slack is not part of this local proof.

Artifact locks:

- contract: `42783e5281f0055a35d3fa58a140069a38a035c6396a61e07eab2594d4d267b2`
- receipt schema: `9480df34a1ee182026a5f852bd40ce21c0009d22474941bfdddd735b2da990f9`
- runtime receipt: `a2195a4f62fbf0b440775400d8403fadb29b3d7af4261edeafa52a127868238c`
- compiler: `fb23f98ab69396ec98ca336967388b83c6d48fd13954a3332a7d28afa84ce8a8`
