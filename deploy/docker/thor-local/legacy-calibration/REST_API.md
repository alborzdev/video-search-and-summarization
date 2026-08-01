# Local legacy calibration REST subset

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

Those upload, image inversion, import, and warp/file endpoints need separate
clean-room contracts and implementations. There is still no official legacy
UI equivalence or runtime qualification claim.

Inspect the inert plan:

```bash
python3 deploy/docker/thor-local/legacy-calibration/rest_server.py
```

An operator-approved future launch must name a private absolute data root and
provide `I_ACCEPT_LOCAL_LEGACY_CALIBRATION_SERVER_8003`. This package does not
auto-start or install a service.
