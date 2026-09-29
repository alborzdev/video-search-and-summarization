# Vision Intelligence operator guide

## After a reboot

From the repository root:

```bash
./deploy/docker/scripts/thor-local.sh stop
./deploy/docker/scripts/thor-local.sh status
./deploy/docker/scripts/thor-local.sh doctor
```

The 128 GiB host is safety-locked against the full local Cosmos3 + Nemotron
graph after two hardware-watchdog resets. Keep the periodic cache cleaner and
all GPU-heavy services stopped. Restore the application only after selecting a
split local-model lane or a remote endpoint for one model and passing the
official-edge audit; never replay an older all-service Compose command.

After a split/remote topology is implemented and accepted, open
**http://10.88.8.175:7777** on Thor or another device on the approved local
network. That is the complete application gateway. While the safety lock is
active, both the gateway and the direct UI diagnostic port may be unavailable
because the application is intentionally stopped.

If Thor's LAN address changes, refresh the runtime only after a split/remote
replacement topology has been implemented and accepted. `thor-local.sh doctor`
intentionally prints no co-resident recovery command while this safety lock is
active.

Do not start a presentation until the header says **NVIDIA THOR · ONLINE** and
the readiness popover shows all seven application capabilities online: video,
agent, analytics, detection, embedding, Cosmos, and Nemotron. The complete
`doctor` command is the authoritative pre-show check.

## Recommended demonstration

1. Begin on **Home**. Use the environment brief to establish connected-source,
   local-processing, and evidence state without opening an admin surface.
2. Open **Live** with the traffic replay or a connected simulator camera.
   Explain that Live/Replay, Analyzing/Paused, and availability are backend
   state. Use the grid for multiple sources and focus one source for media,
   analytics layers, source-scoped questions, Activity, Insights, and History.
3. Ask a suggested visual question. The answer stays in the current source
   context. Current visual questions reserve the one Cosmos visual lane and
   restore compatible continuous work after the reservation is released.
4. Open **History** inside the focused Live source to ask what happened earlier.
   If history is stale, **Sync new history** starts a guarded background build;
   the System admission panel explains when that build is unavailable.
5. Open **Monitoring** to show rules by source. Create a semantic condition or,
   for a qualified detector profile, a polygon rule. Polygon vertices support
   pointer input and a complete keyboard path: **Add point**, arrow keys to move
   a focused point, Shift+arrow for a 5% step, and Delete/Backspace to remove it.
6. Open **Explore** and try:
   - `Find vehicles at the intersection`
   - `Find forklift activity`
   - `Show people entering restricted areas`
7. Play a result and, when useful, scrub to a detector frame and choose **Find
   similar object**. Select two or more clips as evidence, analyze them, ask a
   grounded follow-up, and create an investigation/report. Change Recorded
   video to Live archive only after the live source has had time to index.
8. Open **Events** for evidence-backed activity and native operational insights,
   then **Capabilities** to explain what each workflow uses and where its proof
   comes from.
9. Open **System**. **Edge system** shows service health, compute admission, the
   exact per-source search/retention status, and the pixels-to-evidence pipeline.
   **Sources** contains recorded/RTSP inventory, upload, preview, pause/resume,
   analysis profile, cleanup, and deletion. **Alert rules** remains available as
   a source-administration view. Avoid destructive source actions in the pitch.
10. Use **Presentation Mode** for the customer-facing portion; use **Exit
   Presentation** to leave browser fullscreen.

Every primary workspace has a stable link:
`?workspace=home|live|monitoring|explore|events|capabilities|system`. Browser
back/forward preserves the selected workspace and unrelated query parameters.

## Compute and evidence safety

- **System → What Thor can run now** is a read-only admission snapshot. It never
  starts, stops, or pre-empts work. Interactive visual questions and evidence
  synthesis are admitted only when the shared lane is safe; heavy history work
  requires fresh telemetry. Calibration and experimental audio remain blocked
  until this device has explicit qualification.
- Admission decisions use stable reason codes. A conflict returns HTTP 409; a
  readiness, qualification, or telemetry gate returns HTTP 503. A queued
  operation remains visible rather than masquerading as a failure.
- **System → What remains usable as evidence** reports source counts, not an
  invented percentage. Each source independently shows semantic-index and
  retained-recording state plus the last known time and a truthful remediation.
  If a refresh fails, the UI keeps the last complete snapshot and labels it.
- Detector-backed profiles have finite capacity. A profile assignment that
  would exceed its advertised source limit is rejected server-side; pause or
  reassign the existing source before retrying.

## Show-floor recovery

- If a thumbnail or clip does not load, first refresh once and open **System
  readiness**. Do not repeatedly click Play while VST is preparing a clip.
- If a source is offline, use the known-good traffic or warehouse replay and
  describe it honestly as recorded evidence.
- If readiness is not fully online, run `thor-local.sh doctor` and inspect only
  the named service with `docker logs --tail 150 <container>`.
- Do not recover Cosmos and Nemotron together on this 128 GiB host. Move one
  model to a split/remote endpoint, run the corresponding admission audit, and
  only then start application consumers.
- Do not run connected bootstrap, pull large images, prune runtime images, or
  delete VSS data on a show floor.
- Agent startup leaves registered live sources inactive in the constrained
  lane. Resume a source explicitly only after the replacement topology passes
  runtime acceptance; never treat endpoint health alone as that acceptance.
- The LAN gateway intentionally has no login or TLS boundary. Use it only on a
  trusted, isolated simulator or tradeshow network; never port-forward 7777 to
  the internet or expose the internal model, database, broker, VST, or Agent
  ports.
