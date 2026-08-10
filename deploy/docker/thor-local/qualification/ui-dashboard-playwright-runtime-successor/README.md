# Thor UI Dashboard Playwright runtime evidence

This package retains a bounded, read-only rendered-browser qualification of
`runtime.ui.dashboard-tab` against the already-running Thor VSS UI and Kibana.
It uses regular Playwright because the Browser plugin was absent, connects only
to an operator-preexisting numeric-loopback CDP browser, and never launches or
closes that shared browser.

The positive path selects the Dashboard navigation control, binds the embedded
Kibana iframe to the exact `thor-vss-overview` saved object, verifies the
`Detected Objects` and `Behavior Events` panels, captures desktop and mobile
screenshots outside the repository, and proves the mobile layout has no
horizontal overflow. The adjacent negative reads a nonexistent saved-object ID
and requires HTTP 404.

The source lock also binds the local Kibana configuration that disables
Kibana's insecure-cluster upsell overlay. That setting is presentation-only:
the package continues to report the unauthenticated local-security condition,
and the deployment firewall remains a separate acceptance boundary.

The run is read-only: it does not start or stop a service, create or delete a
saved object, add a stream, upload media, change configuration, or use the
Warehouse sample bundle. The retained receipt contains hashes and dimensions,
not raw page content or URLs.

```bash
node deploy/docker/thor-local/qualification/ui-dashboard-playwright-runtime-successor/harness.mjs plan
python3 deploy/docker/thor-local/qualification/ui-dashboard-playwright-runtime-successor/verify.py
python3 deploy/docker/thor-local/qualification/ui-dashboard-playwright-runtime-successor/build_official_evidence.py
pytest -q deploy/docker/thor-local/qualification/ui-dashboard-playwright-runtime-successor/tests
```

An authorized rerun requires the exact acknowledgement plus explicit
numeric-loopback UI, Kibana, CDP origins and the already-installed Playwright
entry module. The harness writes only temporary screenshots under `/tmp` and
prints the sanitized receipt to stdout.

`runtime-receipt.json` is the complete sanitized browser-run receipt.
`official-runtime-evidence.json` is its smaller, deterministic projection bound
to the exact canonical capability oracle. The current capability ledger uses
the latter; the projector fails closed if the receipt, source locks, target
commit, oracle, or read-only postconditions drift.
