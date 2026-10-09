# Thor offline primary camera

The local Anvil T5 camera is registered as `anvil-t5-main-camera`, stream
`dd61590d-ad69-4d16-8fba-0159f86e86a0`. Its input is the camera at
`10.88.9.42:554/Preview_01_main`; credentials remain in private local runtime
configuration, outside Git. Video I/O reported H.264, 2560×1920, 30 FPS and an
online connection. This source replaces the mock as the default selection.

## Persistent selection

`PUT /api/vision/primary-source` accepts `{ "streamId": "<registered-id>" }`
and validates that the source is a registered live camera. `GET` returns that
preference. The UI stores only the stream ID in
`VISION_HISTORY_DIR/.primary-source.json`, with mode 0600 and atomic replacement.
This deployment mounts that directory from `.thor/data/vision-history`.

Live operations, the video workflow and monitoring prefer this camera, including
while it is temporarily disconnected. An operator's explicit source choice still
wins. The NVStreamer mock and its historical evidence remain available; mock AI
analysis and recording were paused for this change. Main-camera analysis remains
paused and recording is manual.

## Camera-only Ethernet

1GbE2 is `enP2p1s0f1`, NetworkManager profile `Wired connection 2`.
The profile now has `10.88.9.50/32`, no gateway, a host route
to `10.88.9.42/32`, and IPv4/IPv6 `never-default` enabled. Automatic DNS from this
link is ignored. The original profile settings are backed up privately in
`.thor/camera-network-original.txt`.

The host route sends camera traffic through Ethernet from `10.88.9.50`; internet
traffic continues through Wi-Fi while it is enabled. The persistent NetworkManager
dummy connection `vss-local` on `vss-local0` owns `10.88.9.76/32`, preserving
VSS's configured address independently of Wi-Fi and camera link state,
including the UI at `http://10.88.9.76:3001` and the native RTSP proxy at
`rtsp://10.88.9.76:30557/live/dd61590d-ad69-4d16-8fba-0159f86e86a0`.
The local address and route selection were verified. The final cold-start test
disabled Wi-Fi for the entire launch, then restored it automatically.

## One-click offline launch

The trusted Desktop and Applications shortcut **Start VSS · Anvil T5** invokes
`tools/thor/desktop.py start --gui`. It checks prepared local images, model
caches and UI dependencies; restores local networking; applies Jetson clocks;
restarts the saved memory guard; starts missing service stages serially; restores
NVStreamer; checks services, the UI and the persisted primary source; then opens
the live view. A private log and progress window explain each stage. Failed
startup stops partial services while preserving saved data. Process-group
cancellation prevents an interrupted model stage from continuing in the background.

The clock permission is restricted to the root-owned `/usr/bin/jetson_clocks`
with no arguments and its read-only `--show` option. No sudo password is stored.
Warm runs reuse healthy services and do not bounce active camera networking.
Recording and analysis desired states are preserved.

Three actual Wi-Fi-off cold attempts were performed. The first exceeded the
12-minute test deadline because dependency jobs were repeated between stages.
The launcher now reuses successful dependency jobs. The second found the video
analytics MCP service trying to contact Hugging Face for `all-MiniLM-L6-v2`.
That model is now pinned, verified and mounted read-only with HF/Transformers
offline flags in both agent services. A fresh CPU container with networking
disabled successfully produced a 384-dimensional text embedding from the cache.

The third cold start passed in **590.99 seconds** with Wi-Fi continuously off,
all service probes passing, the main camera online and 53.75 GiB available.
The 10 GiB memory guard was active and the boot ID was unchanged. Receipts are in
`artifacts/thor-main-camera-2026-10-09/offline-cold-*.json`. This was a service
cold start on the current boot; no host reboot test is claimed.

After launch, the in-app browser rendered the main camera with decoded
2560×1920 frames (`readyState=4`, playing). Video workflow selected **Anvil T5
Main Camera** by default. No relevant browser console warnings/errors or framework
overlay appeared. Camera recording was off and search indexing paused.

## Validation and scope

Five affected UI suites passed (57 tests), including persistent preference,
disconnected-primary selection and explicit-choice precedence. The stream hook
suite passed again after its final edit (6 tests). The strict app typecheck passed
with AI models stopped.
Thor bootstrap checks passed (30 tests), desktop launcher checks passed (5),
and the existing guard/NVStreamer checks passed (6/4).

The first typecheck alongside the loaded stack crossed the existing 48 GiB
diagnostic reserve: the guard recorded 47.994 GiB available and stopped the
containers without reboot. The receipt is preserved under
`artifacts/thor-main-camera-2026-10-09/reserve-trip/`. Keep compiler/test workloads
separate from loaded models when headroom is marginal. Model budgets were not
changed. Following that trip, the operator explicitly
selected a **10 GiB** reserve. `.thor/settings.json` and the active persistent
systemd guard now use 10 GiB. Thor startup, UI and NVStreamer admission read the
saved setting; rendering without an explicit override preserves it. Reinstalling
the guard writes the saved floor and restarts the unit to apply it immediately.

This camera's 5 MP / 30 FPS main stream differs from the qualified 720p / 10 FPS
mock. Registration, routing and default selection do not qualify full AI ingestion
at that higher resolution. Analysis remains paused for the user's rehearsal.
