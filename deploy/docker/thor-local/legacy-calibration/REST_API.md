# Local legacy calibration REST subset

## VIOS browser-client compatibility adapter

`ui_server.py` is the incremental compatibility surface for the checked-in
VIOS `CalibrationWorkflow`. It is inert by default and uses private numeric
loopback `127.0.0.1:8013`, deliberately avoiding Thor's port-8003 VLM. Its
state lives below an explicit absolute `DATA_ROOT/ui-projects` and is never
passed to the strict VSS compiler until a future explicit export bridge is
implemented.

Implemented client contracts:

| Method | Path | Client-compatible behavior |
| --- | --- | --- |
| GET, POST | `/api/projects/` | Bare `Project[]`; create accepts exactly `name` and `calibrationType`, allocates a numeric ID, and returns the complete checked-in UI shape. |
| GET, PATCH, DELETE | `/api/projects/{numeric_id}/` | Full Project response, bounded partial scalar updates, or exact-owned deletion. Editable URLs are persisted but never dereferenced. |
| GET, PATCH | `/api/sensors/{plain_id}/` | Full Sensor response; bounded partial JSON updates and full-document echo are accepted. Server-owned identity/media fields cannot change. |
| PATCH multipart | `/api/sensors/{plain_id}/` | Exact seven-part client upload; one PNG/JPEG plus calibration state, at most 16 MiB total. Filename input is ignored in favor of SHA-256 identity. |
| GET | `/api/approxHomography/{plain_id}/` | Solve from `sensorPolygon`/`edgeLengths`, persist `sensor.homography` as the JSON string the client subsequently reads. |
| GET | `/api/homography/{plain_id}/` | Same bounded clean-room solve with exact-route identity. |
| POST | `/api/importSensors/{numeric_id}/` | Consume only the locally staged bounded sensor manifest with exact JSON body `{"action":"import-staged"}`; no `mmsURL` request. |
| GET | `/media/projects/{numeric_id}/sensors/{plain_id}/{sha256}.(png|jpg)` | Serve only digest-verified media currently referenced by that sensor. |

The compatibility store permits incomplete UI state. This is essential: the
browser creates an empty project, imports sensor metadata, uploads an image,
then patches drawing coordinates over several requests. The strict exporter
continues to require a complete VSS-valid project and remains in `backend.py`.

Still explicit `501` responses:

- `/api/invertImage/{sensor_id}/`
- `/api/getWarpedFiles/{project_id}/`
- `/api/getImageFiles/{project_id}/`
- `/api/uploadWebApi/{project_id}/`

The first three require a reviewed local image decode/warp/ZIP implementation.
The last must not become an arbitrary server-side request primitive; a future
implementation may target only a configured local VSS analytics API and must
disable DNS ambiguity, environment proxies, and redirects.

The Thor browser derivative in `browser-integration/` now deterministically
adds the `/calibration` route/navigation entry, changes the client base URL to
same-origin `/vst/calibration-api`, and supplies a VIOS Nginx route proxying to
private numeric loopback port 8013. It preserves the released source bytes and
their historical qualification locks. A local ingress image must still be
built from the materialized successor and exercised under authorization, so
browser equivalence and runtime evidence are not claimed. For isolated development,
`serve` may receive repeated `--allowed-origin http://127.0.0.1:PORT` flags;
only explicit numeric-loopback origins get CORS preflight/response headers.
There is no wildcard or credentialed CORS mode.

Inspect the inert plan:

```bash
python3 deploy/docker/thor-local/legacy-calibration/ui_server.py
```

An operator-approved future launch requires an absolute data root and the
exact acknowledgement `I_ACCEPT_LOCAL_VIOS_CALIBRATION_UI_SERVER_8013`. This
package does not launch it automatically.

## Strict compiler-project adapter

`rest_server.py` is a clean-room REST adapter over the local
calibration backend. The default command is an inert plan. It does not bind a
socket until `serve` receives the exact acknowledgement, and then binds only
numeric loopback `127.0.0.1:8003`. Project data is confined to an explicit
absolute local data root. No map provider or other outbound client exists.

Implemented path/method-named clean-room endpoints:

| Method | Path | Behavior |
| --- | --- | --- |
| GET, POST | `/api/projects/` | List or create bounded provider-free projects. |
| GET, PATCH, DELETE | `/api/projects/{project_id}/` | Read, validate-update, or delete one owned project. |
| GET, PATCH | `/api/sensors/{sensor_id}/` | Read or replace one uniquely identified camera. |
| GET | `/api/approxHomography/{sensor_id}/` | Return the clean-room solved homography with approximate-route identity. |
| GET | `/api/homography/{sensor_id}/` | Return the solved homography and reprojection RMS. |

POST bodies use the checked-in clean-room backend project contract, not an
undocumented proprietary body shape. PATCH project bodies are strict merge
objects; sensor PATCH bodies are exact camera objects. Bodies are bounded to
one MiB and reject duplicate keys and non-finite numbers.

This is not a legacy-client-compatible API. The checked-in VIOS client sends a
different project/sensor model, expects a bare project array, performs partial
sensor patches, uploads multipart images, and requires browser routing/CORS.
Those body, response, multipart, and browser contracts remain open even for
the nine path/method pairs above. The adapter must not be wired to that UI or
described as the proprietary port-8003 server.

Explicitly missing and returning `501`:

- `/api/invertImage/{sensor_id}/`
- `/api/importSensors/{project_id}/`
- `/api/getWarpedFiles/{project_id}/`
- `/api/getImageFiles/{project_id}/`
- `/api/uploadWebApi/{project_id}/`

Those statements apply to `rest_server.py`; its strict store remains unchanged
and intentionally does not share incremental UI state with `ui_server.py`.
There is still no official legacy UI equivalence or runtime qualification
claim.

Inspect the inert plan:

```bash
python3 deploy/docker/thor-local/legacy-calibration/rest_server.py
```

An operator-approved future launch must name a private absolute data root and
provide `I_ACCEPT_LOCAL_LEGACY_CALIBRATION_SERVER_8003`. This package does not
auto-start or install a service.
