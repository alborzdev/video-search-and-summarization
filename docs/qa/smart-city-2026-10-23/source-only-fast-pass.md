# Smart City fast improvement pass

## Status

The user stopped long-running qualification on October 23 and requested fast parallel implementation instead. The current two-camera demo at `http://127.0.0.1:7782/?workspace=smart-city` remains running. **The changes below are staged in source; the UI, gateway, controller and native worker have not been rebuilt or restarted for this pass.** Command-line helper changes apply on their next invocation.

The interrupted runs are not passes. [The user-stop receipt](sprint-user-stopped-qualification.json) records observer-only termination; no scheduled question had started. [The earlier command-session interruption](sprint-command-session-interruption.json) is also preserved. Builds, rendered checks of the new UI, actual startup/stop exercises, model requests and sustained live qualification are deferred.

## Implemented changes

- **Less background browser work.** Hidden tabs stop analyzed-preview reads/decode, preview-health polling and city SSE subscriptions. Raw WebRTC fallback does not start in their place. Returning to the tab refreshes configuration and requires new matching frames. Server-side camera analysis and recording continue.
- **Useful uncertainty explanations.** Rule cards show backend-provided causes such as interrupted tracking, unavailable speed, duration requalification or an object whose exit was not confirmed. Missing metrics have a muted indicator. Older snapshots still work without reason fields.
- **Clearer map presentation.** The legend gets a dark backplate over pale imagery without covering the zoom controls. Larger invisible hit targets make map objects easier to select. Keyboard focus, camera-specific labels and primary-pointer panning improve interaction. The deployed screenshots predate these changes; responsive rendering remains to be checked after packaging.
- **Safer editing.** Late save results cannot close or attach errors to a newer draft. Deleting the rule currently being edited closes its draft. Camera clicks cannot change points during a save or erase a completed line. Switching between polygon rule types preserves the boundary. Invalid points, counts, durations and crossed polygons cannot be saved; a small-polygon intersection tolerance bug is fixed in both the UI and backend.
- **Less snapshot work and correct filtering.** Historical requests avoid copying live data they discard. History metric lookup is linear. Exact previews avoid an unnecessary deep copy while preserving immutable public output. Camera event filtering happens before the 100-event limit. Media lookup skips frames with no media timestamp.
- **More reliable controls.** Stop attempts cleanup of both owned sources and Isaac even when one operation fails, then reports incomplete cleanup. Start waits for an already-active bridge that is still booting. Controller readiness snapshots its process reference to avoid a concurrent-removal race.
- **Explicit monitor cancellation.** `--cancel-file` ends observation with a non-pass cancellation receipt while preserving the running cameras. Real failures retain the existing pause behavior. An HTTP response is distinguished from confirmed source cleanup.
- **Native input and shutdown fixes.** Unsigned frame, dimension and queue arguments reject overflow and trailing junk. A stopped or failed publisher does not accept late live submissions after its consumer exits. Constant receipt regexes compile once rather than for each observation. Model weights, inference thresholds and fusion policy are unchanged.

## Evidence and remaining checks

Fast checks are bounded CPU/unit checks, not live deployment qualification. Separate receipts retain exact source hashes and results:

- [Backend changes: 114 tests in 2.81 seconds](source-only-fast-pass-backend.json)
- [Browser work, inspector and editor guards: focused UI batches](source-only-fast-pass-frontend.json)
- [Map and editor interactions: final source hashes and 19-test Editor retest](source-only-fast-pass-map-editor.json)
- [Runtime tools: 82 control checks and 57 monitor tests](source-only-fast-pass-runtime.json)
- [Native controls, cached regex checks and SDK limits](source-only-fast-pass-native.json)

The UI batches passed 24 visibility/camera tests, 61 presentation/inspector/proxy tests and 43 map/editor/workspace tests. The later 19-test Editor run covers the final polygon correction and overlaps the preceding batch. These are short checks, not a claim of one complete frontend suite or a production build.

Before deploying this source revision, build the native worker and production UI, load the gateway/controller changes, verify both actual camera previews and all six rules, inspect the new mobile/laptop legend and reason text, exercise hidden-tab recovery and editor interactions, and run the full integrated qualification with actual recorded-video questions. Do not treat old image hashes or earlier test receipts as evidence for the new source.

Camera identities remain local. MV3DT is still disabled. Map positions and speeds remain estimates. Detector fine-class errors and possible VLM description errors remain; this pass does not claim improved model accuracy or a full booth-day endurance result.
