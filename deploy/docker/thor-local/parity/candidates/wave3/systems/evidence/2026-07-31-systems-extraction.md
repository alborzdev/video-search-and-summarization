# Wave-3 systems extraction evidence — 2026-07-31

## Method

The 23 versioned NVIDIA VSS 3.2.1 pages in `candidate.json` were compared
against the then-live ledger of 161 capabilities. Independently testable
semantics absent from the ledger became proposals. Additional source detail for
an existing ID became an enrichment. Contradictory prose, scoped defaults,
external prerequisites, illustrative schema material, and insecure reference
defaults became discrepancy/boundary records.

This grouping produces exactly 55 proposals, 19 enrichments, and 18 boundaries.
It is intentionally conservative: release-note headings and FAQ questions do
not automatically become one capability each.

## Important contracts

- Alert verification supports verification, context, and classification in
  real-time and on-demand modes. Its REST and Kafka/NvSchema semantics are
  distinct contracts. Prompt-file edits require restart.
- Behavior analytics supports Kafka, Redis Streams, and MQTT sinks. Dynamic
  configuration uses `mdx-notification` / `behavior-analytics-config`; dynamic
  calibration uses the `calibration` key and does not acknowledge updates.
- The Video Analytics API must error when a Kafka-backed endpoint is used with
  `brokers:null`.
- VIOS unified stream processing scales with replicas; Sensor remains a
  singleton. This is a service boundary, not generic VIOS horizontal scaling.
- A deployment selects JSON or Protobuf NvSchema; it does not mix both. The JSON
  page is illustrative, while Protobuf field numbers are wire contracts.
- Elasticsearch disk-watermark recovery repairs disk pressure before clearing
  `read_only_allow_delete`. Disabling watermarks is forbidden by this candidate.
- Optional GPU vector indexing requires an Elastic license and remains external
  optional.

## Release-note mapping

VSS 3.2.1 changes enrich the existing Cosmos3 default and add the mixed image
tag/deprecation contract. The vague CPU multimedia bullet and grouped Smart
City version statement are boundaries, not testable capabilities.

VSS 3.2.0 component bullets are mapped to the most specific existing or
proposed contract. Known failure/recovery semantics retained here include LVS
empty caption windows, shared-prompt last-writer behavior, the epoch-dated
spurious incident index, CR2 NIM redeployment recovery, in-memory reports,
shared-GPU memory limits, search retention/indexing/quality limits, ended-stream
deletion, and the version-scoped Docker 29.5 NGC pull workaround.

## FAQ classification

Four FAQ groups duplicate canonical system-page contracts: RT input protocols,
RT codecs, ELK health timeout, and ELK disk watermark recovery. Five groups are
external/non-Thor references: remote NIM, A100, H200, RTX 4500 remote LLM, and
RTX local VLM tuning.

Firewall subnet values `172.17.0.0/16` and `172.18.0.0/16` are examples. The
actual Docker bridge subnet must be discovered; this package never authorizes a
broad firewall allow rule.

## Benchmark evidence boundary

The official matrices must be copied verbatim, including configuration, units,
hardware, concurrency, stage latency, throughput, utilization, and missing
cells, into an immutable reference fixture before live merge. Selected values
in `performance-reference-contracts.json` are cross-check anchors rather than a
substitute for full rows. A separate Thor measurement file is mandatory and
must never reuse official reference values as observed results.
