# Wave-three evidence boundary

## Exact accounting

- Advertised gap-plan entries: 87
- Previously selected candidate entries: 29 (8 in wave one + 21 in wave two)
- Entries open before this wave: 58
- Wave-three candidate entries: 23
- Entries left without a candidate executor: 35

Both predecessor inventories are digest locked. Their 29 IDs must be unique
and disjoint from this package. The plan, manifest, predecessor chain, and all
source files are checked before any source-contract adapter executes.

## Selected subset

The package checks two RT-VLM media source contracts: alert-category field to
incident metadata mapping, and audio-transcript response serialization.

It checks all eight RT-VLM API *source shapes*: OpenAI-style chat/completions,
text-only chat, multimodal multi-turn chat, token SSE, original and
CV-compatible stream APIs, the file API, and the grouped
health/metadata/models/metrics routes. These do not prove live HTTP behavior,
protocol conformance, media processing, inference, or response semantics.

Four additional RT-VLM source contracts cover remote OpenAI-compatible client
selection, vLLM tuning options, Kafka/Redis error-publication selection, and
Prometheus/OpenTelemetry wiring. They do not access a remote endpoint, broker,
exporter, model, or artifact, and do not prove availability, performance, or
readiness.

The remaining source-contract cases cover:

- LVS SSE/MCP server enablement and endpoint wiring;
- the upstream MV3DT Compose service names plus the Thor offline override;
- the agent health, upload handshake/completion, video-delete, and RTSP
  add/delete route registrations;
- VA-MCP, LVS MCP, and VIOS MCP server/endpoint wiring.

The LVS SSE entry and LVS MCP entry intentionally share the same digest-locked
sources but assert different bounded fragments. The MV3DT check does not load,
download, inspect, or require the optional Warehouse sample dataset.

## Deliberate exclusions

The remaining 35 entries have no candidate executor. All 87 retain their live
gap status. This wave excludes any claim needing a
live endpoint, server lifecycle, browser/UI interaction, media codec or audio
execution, model inference or artifacts, GPU/scale measurement, emitted
Prometheus/OpenTelemetry data, Kafka/Redis delivery, external cloud/object
stores, Slack, Enterprise RAG, real MCP sessions or tool calls, or 3D runtime
inference and calibration.

Source syntax, routes, models, configuration rows, and documentation fragments
are not treated as proof of those literal runtime semantics.

## Result semantics

Every result has:

- `observation: observed_match`
- a `subset:` evidence scope
- `contract_scope: exact-digest-locked-source-fragments-only`
- `runtime_executed: false`
- `workflow_proven: false`
- `service_readiness_proven: false`
- `model_availability_proven: false`
- empty `runtime_evidence`
- `official_capability_effect: none_candidate_only`

These are candidate observations for later review. They do not update shared
acceptance, parity, oracle, or runtime-lane artifacts.
