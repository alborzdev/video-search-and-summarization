# Video Management Playwright successor

This additive package replaces the selected Video Management row's
manual-receipt-only implementation gap with a concrete Playwright client. It
connects to an operator-preexisting browser over numeric-loopback CDP and never
launches a browser, UI, API, Docker container, or service.

The flow under test is: VSS UI -> Video Management -> two-file MP4/MKV upload,
progress and optional template state -> adjacent invalid plus valid RTSP add ->
bulk-delete confirmation cancel -> exact owned deletion -> unrelated-state
restoration. Each fixture must be larger than 10 MiB and at most 12 MiB, so
the real shared 10 MiB uploader emits exactly two chunks per file. The client
captures those four outgoing requests, checks the complete nvstreamer chunk
sequence and identifiers, reconstructs each multipart media payload, and
requires its SHA-256 to equal the reviewed fixture digest.

Codex Browser is not installed in this environment, so the reviewed fallback
is regular Playwright `connectOverCDP`. Runtime requires an explicit absolute
Node executable and Playwright entry module, each SHA-256 pinned in the
manifest. The manifest also pins complete regular-file trees for the
`playwright` and `playwright-core` packages and verifies their package names,
matching versions, and direct dependency edge. The candidate remains
non-promoting because no live receipt or reviewed canonical envelope exists.
The client closes only the page it creates and exits without issuing
Playwright `Browser.close`, preserving the operator-preexisting browser. The
browser, UI, and deployed APIs must already exist on numeric-loopback origins;
the UI, Agent, and VST may share Thor's HAProxy public origin while CDP remains
separate. VST requests use the deployed `/vst/api` prefix. VST-allocated file
and RTSP sensor IDs are discovered from exact,
collision-free run-bound names in the post-state; the manifest never pretends
that a caller-selected sensor UUID was created. The executor disables ambient
environment inheritance and records no
raw URLs, resource IDs, paths, screenshots, response bodies, or credentials.
After pre-state capture, any failure reconciles only exact expected IDs plus
names, attempts every registered owned deletion in reverse order, and requires
owned absence plus an unchanged unrelated stream projection before exit.
Fallback Agent deletion accepts only a bounded JSON response with exact
`status: success` and the matching `video_id` or RTSP `name`; HTTP 2xx with
`partial`, `failure`, a missing/foreign identity, malformed JSON, or an
oversized body fails cleanup. Empty VST sensor entries remain present in the
state projection, so an orphaned sensor with no streams cannot masquerade as
successful deletion. The shipped UI helpers enforce the same exact-success
and identity boundary. The deployed UI and HAProxy topology files are
source-locked alongside those helpers.

The 240-second parent timeout is only an outer failsafe. The browser workflow
has an internal 175-second deadline followed by a reserved 45-second cleanup
window and a 20-second parent margin. Playwright actions/waits are clamped to
the remaining workflow time; VST reads and fallback Agent deletes use bounded
`AbortSignal` timeouts, and cleanup reads/deletes are capped at seven seconds
each. The destructive dialog states that deletion is irreversible and cannot
be undone, and the harness requires that exact warning before both cancel and
confirm paths.

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
