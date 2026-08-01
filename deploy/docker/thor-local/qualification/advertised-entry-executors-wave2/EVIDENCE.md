# Wave-two evidence boundary

## Exact accounting

- Advertised gap-plan entries: 87
- Previously selected candidate entries: 8
- Entries open before this wave: 79
- Wave-two candidate entries: 21
- Entries left open: 58

The predecessor inventory is digest locked and its eight IDs must be disjoint
from this package. The plan, parity manifest, predecessor inventory, and every
source used by an adapter are checked before any adapter executes.

## Selected subset

The package covers nine RT-VLM media helper contracts: file upload, HTTP/S and
S3 request validation, allowlisted file URI resolution, inline data URI
decoding, RTSP request validation, dense-caption JSONL serialization, incident
trigger extraction, and reasoning formatting/metadata helpers.

It covers five performance/observability helper contracts: sampling parameter
selection, GOP parser-buffer selection, decoder cache lifecycle, asset size and
expiry helpers, and absolute timestamp metadata construction.

It covers four model source contracts: Cosmos Reason 1/2, Cosmos 3 Nano/Super,
Nemotron Omni, and Qwen 3.5/MoE. These prove only exact cross-source listing
consistency. They do not prove model artifact availability, compatibility,
execution, or Thor readiness.

It covers three synthetic-data helper contracts: semantic labels, RGB/depth
PNG and HDF5 conversion helpers, and ground-truth naming/bounding-box helpers.
The video-overlay and full-dataset conversion paths are explicitly not run.

## Deliberate exclusions

The remaining 58 entries stay open. This wave excludes any claim needing a
live endpoint, service lifecycle, browser/UI interaction, media codec or audio
execution, real video/model inference, exact model artifacts, GPU or scale
measurements, Prometheus/OpenTelemetry runtime evidence, Kafka/Redis failure
injection, external cloud/object stores, remote endpoints, Enterprise RAG,
Slack/alert delivery, warehouse or 3D runtime inference, or external datasets
and evaluation implementations.

Source presence, configuration rows, routes, or documentation alone are not
treated as proof of those literal advertised semantics. In particular, the
100 GB warehouse sample/data path is neither downloaded nor required by this
candidate-only wave.

## Result semantics

Every result has:

- `observation: observed_match`
- a `subset:` evidence scope
- empty `runtime_evidence`
- `official_capability_effect: none_candidate_only`

These are candidate observations for later review. They do not update shared
acceptance, parity, oracle, or runtime-lane artifacts.
