# Thor Video Analytics API runtime evidence — 2026-08-10

## Result

PASS. The live Thor Video Analytics API exercised the exact 56-operation
OpenAPI surface with the released NVIDIA containers, including non-empty
value-level semantics for every data-bearing query family, successful
write/read workflows, adjacent-negative validation, Kafka-backed dynamic
configuration and calibration, and exact cleanup/restoration.

The complete qualifier passed three times. The retained final run started at
`2026-08-10T16:14:45.501Z` and finished at `2026-08-10T16:15:05.207Z`.
Its JSON receipt has SHA-256
`5917fead7e3c57a4f34ab4fb26a4c19489b534f01050f7d1c7d9be1d00fa1222`.
The query/library official evidence is
`895962811784eb8b03897f048fb9ed5d31156fc0443384ad39c49c1ed13bf8f5`
and binds oracle
`cb013af999e6287d8a95343bb6a4f18adb3cfc38cf1215f1010d262f867aa09d`.
The optional-Kafka official evidence is
`125f3ab237b425c3d0bbd530755f26040d66fc13664fab43626da26d563eb1b3`
and binds oracle
`9b06fffbab0e64fe16bf3a01184ce92b6a2582be7b3526e5689ed4a31c56b1c8`.

## Runtime identity

- Docker: 29.2.1
- Docker Compose: 5.0.2
- API image: `nvcr.io/nvidia/vss-core/vss-video-analytics-api:3.2.0`
- Disposable behavior image:
  `nvcr.io/nvidia/vss-core/vss-behavior-analytics:3.2.1`
- Behavior image ID:
  `sha256:f3fd84f9c9f63b9d00298161929b71c73f36b301782d58bf810e0583843c9fa6`
- Elasticsearch: yellow, expected for a healthy single-node deployment
- Kafka: healthy

The checked-in and running-container OpenAPI files were byte-identical at
SHA-256 `0ff2b2f412446e29149a4998e00a3c6b00c17402befa5f24d8b5b454fb625d37`.
The operation set was exactly 48 GET and 8 POST operations.

## Request and semantic evidence

- 71 total runtime HTTP requests
- 60 positive requests
- 8 adjacent-negative requests
- 3 brokerless-contract requests
- 0 HTTP 5xx responses
- all 48 unique GET operations returned HTTP 200
- all 8 unique POST operations completed a positive HTTP 201 workflow
- all 8 unique POST operations rejected an adjacent invalid request
- 14 namespaced semantic documents populated 13 isolated indices
- all 40 data-bearing GET endpoints passed non-empty, value-level assertions
- average speed, flowrate, combined speed/flow, and corridor travel time were
  positive for the seeded northbound behavior
- tripwire counts/histograms, reset-aware occupancy, FOV/ROI occupancy and
  histograms, mutually-exclusive ROI occupancy, RTLS/AMR tracker occupancy,
  and space utilization matched exact fixture values
- last-processed timestamp and road-segment speed matched the seeded frame and
  road behavior
- MTMC unique count, global object, RTLS/AMR locations, matched behavior path,
  and last record all returned the expected identities
- raw, enhanced, and BEV frames; frame proximity/restricted-area alerts; and
  the high-confidence object matched their fixture IDs and values
- behavior, severe/non-severe alert and incident, tripwire, ROI, and AMR event
  results matched their fixture identities
- coordinate sensor lookup returned the expected fixture camera
- behavior PTS readback: start 1000 ms, end 2000 ms
- frame PTS readback: 1000 ms
- calibration sensor readback matched the namespaced fixture
- road-network city readback matched `VSSOracle`
- USD scene readback matched
  `local://vss-video-analytics-oracle/scene.usd`
- calibration image returned exact SVG bytes at SHA-256
  `c4d6c3cc94c67717087cdc1ca52b226acc69d4adf99a19cb5d5e7b192c344349`
- cluster label readback matched `thor-qualified`
- occupancy reset and cluster-label Elasticsearch readbacks each contained
  exactly one namespaced record
- dynamic configuration progressed from pending to success and produced a
  behavior-analytics config checkpoint
- dynamic calibration upload, upsert, and delete produced at least three
  behavior-analytics calibration checkpoints

## Optional Kafka behavior

A second official `vss-video-analytics-api:3.2.0` container started on
loopback port 18081 with the checked-in fixture setting `kafka.brokers` and
`kafka.retries` to `null`. The shared broker remained running and unchanged.

- `/livez` returned HTTP 200 with `isAlive: true`.
- `/frames` returned the seeded raw frame `150`, proving ordinary
  Elasticsearch-backed endpoints remain functional without a Kafka client.
- `/tracker/unique-object-count-with-locations` without a historical timestamp
  returned HTTP 422 with the exact broker-required message documented by the
  implementation.
- container logs contained no Kafka connection failure or port-9092 attempt.
- cleanup removed the brokerless container exactly.

## Mapping defects and corrections

The official API image stores road-network and USD documents below
`roadNetwork` and `usdAssets` wrappers, but its packaged template definitions
used unwrapped field paths. A road fixture beginning with integer zero and then
using a fractional coordinate therefore caused Elasticsearch to infer `long`
and reject the later float with HTTP 500.

The checked-in service sources now use wrapper-qualified paths. Thor's
idempotent Elasticsearch bootstrap also pre-creates the same exact templates,
which makes the released 3.2.0 image work immediately without rebuilding it:

- `mdx-road-network-template`, priority 553: seven float fields below
  `roadNetwork.intersections.segments.*`
- `mdx-usd-assets-template`, priority 552: three double fields below
  `usdAssets.assets.bbox.dimension.*`

Both live templates were asserted field-by-field before mutation. Calibration,
road-network, and USD uploads subsequently returned HTTP 201, and their GET
readbacks returned the expected semantic identities.

The released RTLS template also omitted the `objectCounts` nested mapping even
though the tracker-occupancy histogram implementation performs a nested
aggregation on that field. Direct tracker reads worked, but RTLS histogram
counts were silently absent while AMR counts remained. The checked-in primary
bootstrap and behavior-analytics integration bootstrap now define:

- `mdx_rtls_template`, priority 507: `objectCounts` as `nested`, with
  `locationsOfObjects` mapping-disabled while remaining available in `_source`.

The live template was updated idempotently before the retained run. The
qualifier asserts the nested mapping before mutation, and the resulting
histogram returned both Person=3 and AMR=1 fixture counts.

## Cleanup and restoration

The successful receipt proved:

- the complete fixed qualifier-owned index allowlist absent;
- both qualifier-created calibration templates absent;
- the upload directory exactly matched its empty pre-run snapshot;
- the disposable behavior container absent;
- the disposable brokerless API container absent;
- both original behavior containers restored and running; and
- no cleanup failures.

The qualifier was also hardened after an intentionally observed early-failure
path: readbacks now explicitly refresh/poll Elasticsearch, and cleanup removes
only uploaded files absent from the pre-run snapshot. The one 183-byte orphan
from that diagnostic run was moved to the desktop trash and is recoverable.

## Static regression checks

- Elasticsearch bootstrap shell syntax: pass
- qualification JavaScript syntax: pass
- `git diff --check`: pass
- complete upstream Video Analytics unit suite: **1,079 passing**
- `bash deploy/docker/test-scripts/test-thor-runtime-infrastructure.sh`:
  pass

The three temporary npm dependency trees used for that unit run were deleted
afterward (approximately 212 MB); no package lock or dependency source change
was retained.

## Scope boundary

This pass qualifies the exact HTTP route set, validation behavior, populated
query semantics, write/read semantics, Kafka update plumbing, and optional
Kafka behavior. No known Video Analytics API runtime gap remains on this Thor.
The VSS Agent `/generate` safety gate is a separate component boundary and was
not invoked by this qualifier.
