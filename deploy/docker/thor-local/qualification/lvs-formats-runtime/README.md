# Thor LVS advertised-format runtime qualification

This package proves the NVIDIA VSS 3.2.1 LVS advertised-format contract on
Thor with real local inference. It deterministically derives tiny MP4, AVI,
MOV, MKV, and WebM variants from the tracked ten-second fixture, uploads each
through the running LVS file API, summarizes it once with the exact locally
advertised model, and immediately deletes it. An invalid-media adjacent
negative must return HTTP 400 / `InvalidFile` without creating an asset.

Execution is inert unless the exact acknowledgement in `contract.json` is
provided. The executor uses numeric loopback only, disables proxies and
redirects, never calls the VSS Agent, never registers RTSP, never starts or
stops a service, never stages a model, and excludes the Warehouse bundle. A
`finally` path deletes only an owned upload that the run actually created.

```bash
python3 deploy/docker/thor-local/qualification/lvs-formats-runtime/execute.py plan

python3 deploy/docker/thor-local/qualification/lvs-formats-runtime/execute.py \
  execute \
  --ack I_ACK_LVS_FIVE_FORMAT_SUMMARIZATION_AND_EXACT_CLEANUP

python3 deploy/docker/thor-local/qualification/lvs-formats-runtime/verify.py
```

The checked-in receipt retains hashes, sizes, media metadata, status codes,
counts, booleans, and durations only. It omits summaries, prompts, request IDs,
raw owned IDs, URLs, headers, credentials, and external data.
