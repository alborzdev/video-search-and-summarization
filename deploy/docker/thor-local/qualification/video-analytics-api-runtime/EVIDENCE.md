# Thor Video Analytics API runtime evidence — 2026-08-10

## Result

PASS. The live Thor Video Analytics API exercised the exact 56-operation
OpenAPI surface with the released NVIDIA containers, including successful
write/read workflows, adjacent-negative validation, Kafka-backed dynamic
configuration and calibration, and exact cleanup/restoration.

The retained successful run started at `2026-08-10T09:50:20.607Z` and finished
at `2026-08-10T09:50:37.415Z`.

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

- 68 total runtime HTTP requests
- 60 positive requests
- 8 adjacent-negative requests
- 0 HTTP 5xx responses
- all 48 unique GET operations returned HTTP 200
- all 8 unique POST operations completed a positive HTTP 201 workflow
- all 8 unique POST operations rejected an adjacent invalid request
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

## Mapping defect and correction

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

## Cleanup and restoration

The successful receipt proved:

- all ten qualifier-owned indices absent;
- both qualifier-created calibration templates absent;
- the upload directory exactly matched its empty pre-run snapshot;
- the disposable behavior container absent;
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

This pass qualifies the exact HTTP route set, validation behavior, core
write/read semantics, and Kafka update plumbing. Empty-but-schema-valid results
for unseeded metric, tracker, frame, alert, incident, and event queries are not
treated as proof of their full non-empty business semantics. Those deeper
fixture correlations and Kafka-absent behavior remain open in the parity
ledger rather than being overstated here.
