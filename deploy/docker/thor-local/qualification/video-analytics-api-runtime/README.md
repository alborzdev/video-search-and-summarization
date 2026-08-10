# Thor Video Analytics API runtime qualification

This qualifier exercises the complete VSS 3.2.0 Video Analytics HTTP surface
that ships with VSS 3.2.1 on the live Thor deployment. It also proves the
Kafka-backed dynamic configuration and calibration path with the official
behavior-analytics 3.2.1 image.

## Safety boundary

The harness fails closed unless:

- `vss-video-analytics-api`, `kafka`, and `elasticsearch` are running;
- the two normal Thor behavior consumers are running;
- both disposable qualifier container names are absent;
- the checked-in and running-container OpenAPI bytes exactly match the locked
  56-operation manifest;
- all qualifier-owned Elasticsearch indices and temporary templates are
  absent; and
- the persistent RTLS, road-network, and USD mapping templates have the exact
  nested and wrapper-qualified fields required by the API queries.

It stops the two normal behavior consumers, runs one disposable official
3.2.1 consumer, exercises the API, and restores the original consumers. Its
fixtures use the `vss-oracle-video-analytics` namespace. Cleanup deletes only
the indices, temporary templates, and uploaded files absent from the pre-run
snapshot, plus the disposable container. Cleanup runs on success and failure.
Kafka notifications are append-only and may remain in the broker retention
window; the fixture namespace prevents them from colliding with production
sensor data.

## Run

From the repository root:

```bash
node deploy/docker/thor-local/qualification/video-analytics-api-runtime/harness.mjs
```

The command emits a JSON receipt to standard output and exits nonzero unless
all assertions and cleanup postconditions pass. No sudo, model pull, sample
stream, warehouse dataset, or VSS Agent `/generate` call is involved.

## Coverage

- exact OpenAPI identity: 56 operations (48 GET, 8 POST);
- every GET with contract-valid parameters;
- every unique POST with a successful fixture workflow;
- an adjacent invalid request for every unique POST operation;
- 14 isolated semantic documents across 13 Elasticsearch indices;
- non-empty, value-level readbacks across all 40 data-bearing GET endpoints,
  including speed/flow/travel time, tripwire/ROI/FOV/tracker occupancy,
  space utilization, road-segment speed, MTMC locations, raw/enhanced/BEV
  frames, alerts, incidents, tripwire/ROI/AMR events, and sensor lookup;
- exact behavior/frame PTS, calibration, road network, USD assets, image
  bytes/metadata, occupancy reset, and cluster-label readbacks;
- dynamic configuration ACK and behavior checkpoint;
- dynamic calibration upload/upsert/delete checkpoints;
- an official isolated API instance with `kafka.brokers: null`, proving healthy
  startup, a populated non-Kafka raw-frame read, the exact HTTP 422
  broker-required contract for real-time tracker locations, and zero Kafka
  connection attempts;
- exact cleanup and restoration.

This proves the complete routed API surface, the advertised non-empty query
families, write/read/Kafka plumbing, and the optional-Kafka failure contract.
The brokerless proof uses a second official API container on loopback port
18081; it never stops or reconfigures the shared Kafka broker.
