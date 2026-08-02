# Video Management Playwright successor

This additive package replaces the selected Video Management row's
manual-receipt-only implementation gap with a concrete Playwright client. It
connects to an operator-preexisting browser over numeric-loopback CDP and never
launches a browser, UI, API, Docker container, or service.

The flow under test is: VSS UI -> Video Management -> two-file MP4/MKV upload,
progress and optional template state -> adjacent invalid plus valid RTSP add ->
bulk-delete confirmation cancel -> exact owned deletion -> unrelated-state
restoration.

Codex Browser is not installed in this environment, so the reviewed fallback
is regular Playwright `connectOverCDP`. Runtime requires an explicit absolute
Node executable and Playwright entry module, each SHA-256 pinned in the
manifest. This does not pin the entry module's transitive dependency graph, so
the candidate remains non-promoting until a reviewed complete tool-tree digest
is added. The client closes only the page it creates and exits without issuing
Playwright `Browser.close`, preserving the operator-preexisting browser. The
browser, UI, and mock APIs must already exist on distinct numeric-loopback
origins. The executor disables ambient environment inheritance and records no
raw URLs, resource IDs, paths, screenshots, response bodies, or credentials.
After pre-state capture, any failure reconciles only exact expected IDs plus
names, attempts every registered owned deletion in reverse order, and requires
owned absence plus an unchanged unrelated stream projection before exit.

The 11 selected units are semantic checkpoints, not an honest bound on DOM
interactions and API fan-out. This candidate therefore retains the predecessor
limits of 240 seconds, 40 browser actions, and 32 API exchanges and remains
`canonical_bound=false`, `executor_ready=false`, and
`promotion_eligible=false` until a reviewed canonical envelope and live receipt
exist.

Default validation is inert and tests are mock-only:

```bash
python3 deploy/docker/thor-local/qualification/ui-video-management-playwright-successor/executor.py plan
pytest -q deploy/docker/thor-local/qualification/ui-video-management-playwright-successor/tests
```

The live client is separately gated:

```bash
python3 deploy/docker/thor-local/qualification/ui-video-management-playwright-successor/executor.py execute-playwright \
  --manifest /absolute/reviewed/ui-video-management.json \
  --acknowledgement I_ACK_UI_VIDEO_MANAGEMENT_PLAYWRIGHT_RUNTIME
```

No live run is performed by static qualification.
