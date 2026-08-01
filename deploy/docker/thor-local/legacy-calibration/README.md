# Thor clean-room legacy calibration backend slice

This Apache-2.0, provider-free Python backend advances the manual/GIS
architecture gap without inspecting or emulating NVIDIA's amd64-only legacy
image. It performs real bounded work for Cartesian, image, GIS, and
multi-camera projects: validation, a 3x3 planar homography solve,
ROI/tripwire/road-link validation, deterministic `calibration.json` and
`road-network.json` export, validation against the checked-in strict VSS
schemas and both calibration consumers, and strict readback.

It deliberately identifies itself as `thor-clean-room-provider-free-v1`. It is
not the official Google Maps UI, the proprietary legacy server, AutoMagicCalib,
or runtime qualification. Two deliberately separate adapters now exist:

- `rest_server.py` preserves the strict compiler-project REST subset. It is not
  compatible with the checked-in VIOS browser client.
- `ui_server.py` stores the browser's incomplete, incremental project/sensor
  state separately on private numeric loopback port `8013`. It implements the
  client-observed bare-array project CRUD shape, partial sensor JSON updates,
  persisted homography, bounded multipart PNG/JPEG upload and confined static
  media, and an operator-staged provider-free sensor import.

The digest-locked browser derivative now routes the checked-in workflow and
defines its same-origin VIOS proxy without changing historical upstream source
locks. A reviewed, locally built ingress image and authorized browser run are
still required. Image inversion, image/warped ZIP downloads, outbound Web API
upload, official Google Maps identity, and runtime qualification remain open.
See `browser-integration/README.md` and `REST_API.md`.

The input project must explicitly supply semantics that cannot safely be
invented: one of the three legal VSS output calibration types, the OSM URL,
road city/intersection identity, each camera's origin, geo-location, local
coordinates, scale factor, attributes and place, every tripwire's direction,
and geographic `lat`/`lon`/`alt` plus cardinal direction for every road link.
A multi-camera project is a workflow type, not a legal VSS
`calibrationType`; it must explicitly choose `geo`, `cartesian`, or `image` for
the exported document.

Run the unit and functional tests:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/legacy-calibration/tests
```

Execute a generated/operator-custom project without a service lifecycle:

```bash
python3 deploy/docker/thor-local/legacy-calibration/backend.py project.json \
  --output-root /private/operator-approved/output
```

Inspect the client-compatible server's inert plan:

```bash
python3 deploy/docker/thor-local/legacy-calibration/ui_server.py
```

No client service is started by the package or its tests. Sensor import never
dereferences the UI's editable `mmsURL`. An operator instead stages a bounded
local manifest after creating a project:

```bash
python3 deploy/docker/thor-local/legacy-calibration/ui_server.py stage-sensors \
  --data-root /private/operator-approved/calibration-state \
  --project-id 1 \
  --input /private/operator-approved/sensors.json
```

The manifest is exactly `{"sensors":[...]}`. Each row requires a plain
`sensorId`, may provide a distinct plain `id`, and may contain only documented
UI Sensor fields. `POST /api/importSensors/1/` with exact JSON body
`{"action":"import-staged"}` then consumes that staged file;
there is no DNS, proxy, redirect, VST, map-provider, or Web API request.

The exporter never overwrites a project directory. Inputs are strict bounded
JSON, output filenames are fixed, IDs cannot traverse paths, and the Warehouse
sample is neither accepted nor required. The provider-free alternate identity
is stored in a schema-legal sensor attribute rather than an incompatible
top-level extension.
