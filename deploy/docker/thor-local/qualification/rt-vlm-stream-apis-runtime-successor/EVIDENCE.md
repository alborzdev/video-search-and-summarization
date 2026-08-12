# Evidence

The retained run uses the deployed local Cosmos RT-VLM container without model
inference. A checked-in H.264 clip is loop-published to a disposable arm64
MediaMTX container attached only to `mdx_default`.

The original plural API proves fixed external UUID ownership, full place
metadata round-trip, list visibility, and a batch delete containing one success
and one structured per-item error. The CV-compatible singular API proves camera
ID/name/URL round-trip, accepted CV metadata and headers schemas, duplicate-ID
rejection, exact remove identity, and missing-camera rejection. Both catalog
representations see the live assets and return byte-canonically to their prior
state after cleanup. No VSS Agent call, VIOS mutation, model request, external
request, credential, or Warehouse sample is involved.

`runtime-receipt.json` is schema-validated, bound to the exact contract and
source locks, and contains no raw UUID.
