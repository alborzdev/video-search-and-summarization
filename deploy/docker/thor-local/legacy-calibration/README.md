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
or runtime qualification. A clean-room loopback port-8003 subset implements
nine client-observed project, sensor, and homography operations; five image,
upload, import, and warp/file operations remain explicitly unavailable. The
interactive editor, legacy-client-compatible bodies and responses, multipart
uploads, browser routing/CORS, official Google Maps identity, and an authorized
Thor runtime run remain open. See `REST_API.md`.

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

The exporter never overwrites a project directory. Inputs are strict bounded
JSON, output filenames are fixed, IDs cannot traverse paths, and the Warehouse
sample is neither accepted nor required. The provider-free alternate identity
is stored in a schema-legal sensor attribute rather than an incompatible
top-level extension.
