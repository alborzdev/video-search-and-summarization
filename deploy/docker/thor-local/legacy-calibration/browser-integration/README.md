# Thor-local VIOS calibration browser integration

This bounded derivative makes the checked-in `CalibrationWorkflow` routable in
a Thor-built VIOS UI without changing NVIDIA's released source files or the
historical Wave 6/7 source locks. `overlay.json` pins the five exact upstream
inputs and their deterministic successors:

- `/calibration` is added to the default VIOS router and navigation;
- the calibration client endpoint becomes same-origin
  `/vst/calibration-api`; and
- the JSON manager's one root-absolute project PATCH is routed through that
  configured same-origin endpoint; and
- the state-changing staged-sensor import is changed from GET to an exact
  JSON POST, preventing cross-origin image/form requests from invoking it; and
- the browser no longer addresses port 8003 or private port 8013 directly.

`nginx-vst-direct.conf` proxies only that same-origin prefix to numeric
loopback `127.0.0.1:8013`. It rewrites the prefix before forwarding, so the
existing client requests `/api/...` and `/media/...` reach `ui_server.py`
unchanged. The route enforces a 16 MiB body ceiling before proxying and disables
request spooling, independently matching the backend's multipart ceiling. The
backend has no Compose `ports` entry, uses host networking only
to share loopback with VIOS ingress, drops every Linux capability, and keeps
mutable state below `${VSS_DATA_DIR}/calibration-ui`.

The proxy inherits the VIOS ingress trust boundary; it does not add user
authentication. If port 30888 is reachable beyond the operator host or trusted
management network, place the existing ingress behind the deployment's access
control before enabling this overlay. The JSON-only POST hardening prevents a
cross-origin image or HTML form from triggering staged import, but it is not a
substitute for network authentication against a deliberate HTTP client.

## Static inspection and source materialization

Inspection is read-only and verifies all source and successor digests:

```bash
python3 deploy/docker/thor-local/legacy-calibration/browser-integration/materialize.py inspect
```

Materialization is an explicit local write into a new directory:

```bash
python3 deploy/docker/thor-local/legacy-calibration/browser-integration/materialize.py \
  materialize \
  --source-ui-root services/vios/ui \
  --output-root /absolute/new/ui \
  --acknowledgement I_ACCEPT_MATERIALIZE_THOR_CALIBRATION_UI_SOURCE
```

The output contains unchanged `streaming-lib` and a patched `vios-ui`, excluding
all local `node_modules` dependency trees. Build that output with the checked-in
Node package manifests, stage its `dist` into the standard VIOS ingress build
context, and tag the resulting local image. Dependency acquisition, image build,
and service lifecycle are deliberately not performed by this package. If Node
dependencies are absent, inventory the exact package/download size and obtain
operator approval before fetching them.

The opt-in `compose.yml` requires
`THOR_CALIBRATION_VIOS_INGRESS_IMAGE` rather than falling back to the released
image: the released compiled SPA does not contain the unreachable workflow.
Include this file only after a digest-reviewed local ingress image exists.
The overlay then starts the private adapter and replaces the ingress config.

This is source/build/lifecycle wiring, not browser or Thor runtime evidence.
Image inversion, ZIP downloads, Web API upload, the strict-export bridge, and
authorized end-to-end qualification remain open.
