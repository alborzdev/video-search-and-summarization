# Evidence

The retained Thor run passed in 31.415783 seconds. It generated and published
the exact 75,449-byte H.264 color timeline, proved the RTSP stream over TCP,
registered one qualifier-owned direct RT-VLM stream, and received one real SSE
caption result from the local Cosmos 3 Nano Reasoner. The semantic oracle found
blue, green, and red in chronological order.

The run made one model request and fourteen RT-VLM HTTP requests. Cleanup
returned both live-stream DELETE operations as HTTP 200, restored the original
zero-stream and zero-asset state, stopped the publisher, removed MediaMTX, and
removed the temporary fixture root. RT-VLM remained healthy with zero restarts
and no OOM event.

Artifact locks:

- contract: `d68d055983a1b3a8ba971b965317e2f061090453b18895e2738299b5867a5516`
- receipt schema: `4abb1c0aea75210f262974fe288a94302bdcc3a3e0ee91f702f910e6e93454c2`
- runtime receipt: `b91da01061bb02573a4cf9adfe3e1ed6d9e61b3f1b2eb17261947536cc64160f`
- executor: `7576cd569a5c506e8f88501e9aeea8a2369b1d6ce3168b3281a838054e167223`

The receipt retains hashes and booleans, not the owned stream UUID, RTSP URL,
prompt, caption prose, request/session identifiers, or credentials. The
Warehouse bundle, VSS Agent, VIOS, and RT-CV were not used.
