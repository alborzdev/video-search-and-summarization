# Thor RT-Embed runtime qualification — 2026-08-10

## Result

The VSS 3.2.1 RT-Embed derivative ran locally on AGX Thor with the staged
`cosmos-embed1-448p-anomaly-detection` model. The container used image ID
`sha256:336dde22db12fe9ebfe3b64130dc593f9a267cbeaf00eea9f958ce0816534699`,
reported release `3.2.1` and API `3.1.0`, remained healthy with zero automatic
restarts, and advertised exactly 22 paths / 24 operations in its live OpenAPI
document.

The following live operations passed through `http://127.0.0.1:8017`:

- readiness, detailed readiness, liveness, startup, version, metadata,
  manifest, models, metrics, and asset statistics;
- list, upload, inspect, exact-content download, and delete for an owned file;
- batched text embedding;
- synchronous uploaded-file video embedding;
- server-sent-event uploaded-file video embedding, including the final usage
  event and `data: [DONE]`; and
- RFC 2397 `data:video/mp4;base64,...` video embedding.

The six mutating live-stream control operations were not called. Both stream
inventory endpoints returned zero registrations, and no operator RTSP URL was
provided. This qualification does not invent an RTSP fallback or claim live
stream embedding from an empty inventory.

## Text and video embeddings

One two-item text request returned two finite 768-dimensional vectors in the
advertised shared text/video embedding space. The text inputs were `a white
car driving on a road` and `a person walking near a building`.

The owned video fixture was the tracked 10-second H.264 1920x1080 file
`services/alert/warmup/test.mp4`, 2,575,454 bytes, with SHA-256
`f2c16bf02e1d43fa52faf902ff981185c62df092189b41c735c5c27647b44205`.
Uploading it with purpose `vision` succeeded. File listing returned the exact
new UUID, metadata retained the supplied creation time and sensor name, and
the content endpoint reproduced the fixture SHA-256 exactly.

Synchronous embedding with five-second chunks and one-second overlap returned
three finite 768-dimensional vectors for offsets 0-5, 4-9, and 8-10 seconds.
The service reported three chunks and one second of query processing time.
Observed per-chunk inference latency was 392-612 ms and end-to-end chunk
latency was 495-1,108 ms; these are observations from this tiny fixture, not a
general Thor performance envelope.

The SSE variant returned the same three 768-dimensional chunk events, one
usage-only event (`total_chunks_processed=3`, `query_processing_time=1`), and
the required `[DONE]` terminator. The RFC 2397 data-URI variant independently
returned three finite 768-dimensional vectors for the same 10-second media.
Data-URI input remained transient rather than creating a stored file.

Every uploaded test asset was deleted by exact UUID. Final asset statistics
were `asset_count=0`, `asset_count_with_storage=0`, and `aged_out_count=0`.

## Upload and local-file boundaries

The live multipart route accepts either an uploaded `file` or a server-side
`filename`, not both. Supplying both correctly returned HTTP 422
`InvalidParameters`; the normal uploaded-file form passed. Optional
`creation_time` and `sensor_name` fields each passed independently.

The service has no broad `FILE_URL_ALLOWED_DIRS` configuration. A bounded
request for `file:///etc/hosts` returned HTTP 403 `Forbidden` with the explicit
message that file URLs are disabled. No asset was created.

## Loopback security correction

Before correction, Docker published the unauthenticated RT-Embed API as
`0.0.0.0:8017`, and a request through Thor's physical-interface address
returned HTTP 200. NVIDIA's RT-Embed guidance requires a local deployment
without Bearer authentication to remain loopback-only.

The Thor overlay now overrides the upstream port mapping to
`127.0.0.1:8017:8000`. The host-network Agent uses the existing
`COSMOS_EMBED_ENDPOINT=http://127.0.0.1:8017` setting rather than constructing
the embedding URL from physical `HOST_IP`. Only RT-Embed and Agent were
recreated, with pulls and builds disabled. Both became healthy with zero
restarts. Post-change loopback readiness returned HTTP 200, while the same
physical-interface request could not connect. A post-change text embedding
returned one finite 768-dimensional vector, and the exact-model Thor demo
runtime identity/readiness verifier still passed.

At the final observation, the host retained about 15 GiB available unified
memory, no swap, and 30 GiB free disk. The system cache cleaner remained
active. No model cache, VIOS media, Elasticsearch index, or unrelated
container was deleted.
