# Thor message-broker consumer qualification — 2026-07-31

## Scope

This is a read-only source and mocked-unit qualification of
`tools/message-broker-consumers`. No containers or live Kafka/Redis services were
started. Existing captures remain unlimited unless an operator opts into the new
bounds.

## Closed gaps

- Kafka partition EOF detection now compares against
  `KafkaError._PARTITION_EOF`. The old `KafkaException._PARTITION_EOF` reference
  is not a valid confluent-kafka error-code contract.
- Kafka and Redis capture processes accept defaults-off per-source
  `--max-messages` and `--timeout-seconds` controls. `--poll-timeout-seconds`
  bounds a single broker read and is clipped to a finite run's remaining time.
- Redis batch size is capped to the remaining message count, so a requested
  record limit is exact and returned records can still be acknowledged.
- Kafka auto-commit/auto-offset-store are disabled. A record is committed
  synchronously only after successful decode, JSONL write, and flush; decode or
  broker errors leave it uncommitted. Processing stops on decode, output, or
  commit failure so a later Kafka offset cannot commit past a failed record.
  Bounded captures fail fast on broker errors that would otherwise prevent a
  message count from advancing.
- Kafka tombstones and empty-byte records are surfaced to the processor, counted
  as failures, and left uncommitted. Empty protobuf bytes are rejected rather
  than being accepted as an all-default protobuf message.
- Empty topic/stream entries are rejected before any child process starts.
- Bounded child-process completion is reported as expected completion rather
  than as all workers having died.
- Connection, broker, and decode errors are reflected in child and top-level
  non-zero exit status, making the finite command usable by an acceptance gate.
- Decoding covers every bundled protobuf type for which a producer/topic mapping
  is proven in source: Frame, Behavior, SpaceUtilization, Incident, and VisionLLM.
  Known notification and RT-VLM/RT-Embed error topics are decoded as JSON because
  their producers serialize JSON rather than protobuf.
- All 21 topics provisioned by `deploy/docker/services/infra/compose.yml` now
  have authoritative wire mappings. The focused test extracts that Compose set
  and fails if it differs from the decoder's provisioned-topic registry.
- Unknown topics are rejected instead of being assigned a guessed schema. Decode
  errors do not log raw payload bytes.

## Source evidence for added mappings

- `services/rtvi/rt-vlm/src/server/rtvi_stream_handler.py` constructs and
  serializes `VisionLLM` to `mdx-vlm-captions`, and serializes `Incident` to
  `mdx-vlm-incidents`.
- `services/rtvi/rt-embed/src/server/rtvi_stream_handler.py` uses the same
  `VisionLLM`/`Incident` protobuf paths for embedding results.
- `deploy/docker/services/rtvi/rtvi-vlm/rtvi-vlm-docker-compose.yml` defines the
  legacy/default aliases `vision-llm-messages` and
  `vision-llm-events-incidents`.
- `services/rtvi/rt-embed/docker/compose.yaml` describes
  `vision-embed-messages` as a VisionLLM/embedding message topic.
- `services/video-summarization/src/kafka_producer.py` serializes VisionLLM to
  `mdx-structured-events-summary`.
- `services/alert/mdx/anomaly/sink/vlm_enhanced_sink/sink_kafka.py` maps
  `mdx-vlm-alerts` to the Behavior protobuf route.
- Both shipped infra Logstash pipelines decode `mdx-embed-filtered` as
  `nv.VisionLLM`. Behavior analytics reads `mdx-embed` with
  `StreamMessageProtoDeserializer(nvSchema.VisionLLM)`, and RT-Embed config/tests
  use `mdx-embed` for its serialized VisionLLM output.
- Both shipped infra Logstash pipelines decode `mdx-rtls` /
  `mdx-rtls-region-1` as `nv.Frame`.
- The Kafka and Redis Logstash inputs use their plain codec for `mdx-mtmc` and
  `mdx-amr`, followed by the JSON filter, establishing JSON wire payloads.
- RT-VLM and RT-Embed `_send_error_message_to_kafka` serialize their error
  payload with `json.dumps`; behavior-analytics defines `mdx-notification` as a
  JSON configuration/calibration envelope.

## Provisioned-topic wire matrix

| Wire contract | Provisioned topics |
|---|---|
| `nv.Frame` | `mdx-raw`, `mdx-bev`, `mdx-frames`, `mdx-rtls`, `mdx-rtls-region-1` |
| `nv.Behavior` | `mdx-behavior`, `mdx-behavior-plus`, `mdx-alerts`, `mdx-events`, `mdx-vlm-alerts` |
| `nv.SpaceUtilization` | `mdx-space-utilization` |
| `nv.Incident` | `mdx-incidents`, `mdx-vlm-incidents` |
| `nv.VisionLLM` | `mdx-vlm`, `mdx-vlm-captions`, `mdx-structured-events-summary`, `mdx-embed`, `mdx-embed-filtered` |
| JSON | `mdx-mtmc`, `mdx-amr`, `mdx-notification` |

Mapped provisioned topics: **21/21**. Genuinely schema-unknown provisioned
topics: **none**. Non-provisioned custom or renamed topics remain rejected until
an authoritative producer/schema contract is supplied.

## Verification

Run from the repository root:

```bash
python3 -m py_compile \
  tools/message-broker-consumers/base_consumer.py \
  tools/message-broker-consumers/kafka_to_file.py \
  tools/message-broker-consumers/redis_to_file.py \
  tools/message-broker-consumers/tests/test_consumers.py

pytest -q tools/message-broker-consumers/tests/test_consumers.py
```

Result:

```text
.......................                                                  [100%]
23 passed in 0.10s
```

The focused tests stub the unavailable host broker clients and verify EOF
handling, countable Kafka errors, source-defined protobuf and JSON decoding,
payload-redacted failures, exact message bounds, timeout-clipped polling, Redis
batch bounds, error exit status, tombstone/empty-payload rejection, and numeric
argument validation. They also compare the extracted infra Compose topic set
against the complete authoritative mapping matrix.

## Remaining runtime evidence

- Run a finite capture against the Thor-local Kafka and Redis services once the
  unified stack is approved to start, and compare decoded output with producer
  fixtures.
- No topic provisioned by the local infra Compose remains unmapped. A custom or
  renamed topic outside that set still requires an authoritative wire contract
  before it can be added.
- This local debugging utility exposes no SASL/TLS options. Those are not needed
  for the loopback Thor broker profile, but would be required before using it
  with an authenticated remote broker.
