# Thor Video Analytics API runtime qualification

This qualifier exercises the complete VSS 3.2.0 Video Analytics HTTP surface
that ships with VSS 3.2.1 on the live Thor deployment. It also proves the
Kafka-backed dynamic configuration and calibration path with the official
behavior-analytics 3.2.1 image.

## Safety boundary

The harness fails closed unless:

- `vss-video-analytics-api`, `kafka`, and `elasticsearch` are running;
- the two normal Thor behavior consumers are running;
- the checked-in and running-container OpenAPI bytes exactly match the locked
  56-operation manifest;
- all qualifier-owned Elasticsearch indices and temporary templates are
  absent; and
- the persistent road-network and USD mapping templates have the exact
  wrapper-qualified numeric fields.

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
- semantic readbacks for behavior PTS, frame PTS, calibration, road network,
  USD assets, image bytes/metadata, occupancy reset, and cluster label;
- dynamic configuration ACK and behavior checkpoint;
- dynamic calibration upload/upsert/delete checkpoints;
- exact cleanup and restoration.

This proves the complete routed API surface and its write/read/Kafka plumbing.
It does not by itself claim populated, hand-computed non-empty results for
every analytics query family; those deeper semantic scenarios remain tracked
separately in the parity ledger.
