# Thor Alerts UI runtime qualification — 2026-08-10

This note retains the bounded Alerts-tab runtime evidence collected from the
local VSS 3.2.1 CV-verification stack on AGX Thor. The browser harness allowed
only GET, HEAD, and OPTIONS requests. It did not create, update, or delete an
alert rule, candidate-verification rule, incident, sensor, stream, or Slack
configuration, and it did not invoke Agent generation.

## Live backend state

Numeric-loopback preflight calls established the state shown by the UI:

- Video Analytics `GET /incidents` returned HTTP 200 with zero incidents for
  the requested ten-minute interval.
- VIOS `GET /v1/sensor/list` returned HTTP 200 with three online sensors:
  `pit-POV`, `sample-sim-jaywalking`, and `sample-sim-traffic`.
- Alert Bridge `GET /realtime` returned HTTP 200 with zero realtime rules.
- Alert Bridge `GET /verification/config` returned HTTP 200 with one candidate
  verification configuration.

## Browser qualification

The final headless Chromium run started at `2026-08-10T07:44:41.459Z`, took
2,031 ms, and exited successfully at `http://127.0.0.1:3001`. It exercised:

1. The Alerts view and its default query controls.
2. The auto-refresh settings panel.
3. The Manage Alerts realtime-rule inventory.
4. A temporary client-side draft solely to load the VIOS live-stream catalog.
5. The Candidate Verification rule inventory.

The live UI matched the advertised defaults: VLM-verified filtering enabled,
all verdicts, ten-minute query range, 100 alerts per API call, auto-refresh
enabled at 1,000 ms, and View Alerts selected. The sensor filter contained all
three online VIOS sensors. The incident result was the valid empty state, with
no UI or console error.

Manage Alerts loaded the empty realtime-rule inventory without error. Opening
one client-side draft caused the documented `GET /v1/live/streams` refresh;
the HTTP 200 catalog offered the same three online sensor names. The draft was
discarded without saving. Candidate Verification then loaded the one retained
configuration with HTTP 200 and no error.

The harness observed 14 loopback GET requests, including the incidents,
sensor-list, live-stream-catalog, realtime-rule, and verification-config paths.
It observed zero mutating requests, zero prohibited requests, and zero browser
console errors.

Final screenshots retained outside the repository for this run:

- `/tmp/vss-alerts-runtime-view.png`: 71,279 bytes, SHA-256
  `fec3e775e95c1c68e7c855ed66a7571e956dd5a4190aa9736c3bae4ba520dcf7`.
- `/tmp/vss-alerts-runtime-manage.png`: 92,482 bytes, SHA-256
  `e2e7d0b225942f35513257b9ceca2ec72ca8791083bdc88903ae6c2e3bb88892`.

## Code verification and boundary

- All 19 Alerts test suites passed: 241 tests total.
- The Alerts package declaration/type check passed in an isolated temporary
  output directory.
- The same package had already compiled successfully in the deployed
  production multi-package UI image.

This evidence qualifies the Alerts defaults, empty incident rendering,
View/Manage navigation, live sensor catalog, realtime-rule inventory, and
candidate-verification inventory. It does not claim the entire advertised
Alerts capability row. Runtime create/delete semantics require a confirmed
switch to VLM realtime mode; Agent incident-query generation and actual rule
creation were intentionally not invoked in this bounded read-only run.
