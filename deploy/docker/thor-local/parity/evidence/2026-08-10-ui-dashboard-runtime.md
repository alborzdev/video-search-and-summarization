# Thor VSS Dashboard runtime evidence — 2026-08-10

`runtime.ui.dashboard-tab` passed a bounded read-only rendered-browser run on
Thor at target commit `afef8a4a28291db768b1f1795758094302b70de7`.

The run selected the Dashboard tab in the live VSS UI, rendered the embedded
Kibana 9.3.3 `Thor VSS Overview` dashboard and its `Detected Objects` and
`Behavior Events` panels, verified desktop and mobile layout, proved there was
no mobile horizontal overflow, and required HTTP 404 for a nonexistent adjacent
dashboard ID. It created, changed, and deleted no persistent resources.

The machine-readable receipt, exact runtime identities, source locks, fixture,
schema, harness, offline verifier, and focused tests are retained in
`deploy/docker/thor-local/qualification/ui-dashboard-playwright-runtime-successor`.

Kibana was intentionally running without local security. Its visible “Your
data is not secure” notice and `/internal/security/user_profile` errors remain a
separate open local-security/demo-polish gap. They did not prevent the dashboard
from rendering and are not represented as clean console output.

The canonical oracle still carries its original planning-only two-request
bound, which cannot describe a real embedded Kibana browser render. The receipt
is therefore recorded as `passed_current_candidate`; canonical promotion must
first replace that planning bound with the reviewed browser/API envelope rather
than forcing an invalid ledger state.
