# Finite indexing live check and isolated UI packaging

Independent read-only verification at **2026-10-26 05:26:22 UTC** passed. See [the sanitized machine receipt](finite-indexing-live-cleanup.json). Verification used status, inventory, health and metrics GETs only; it did not issue search/model requests or change services.

## Finite session stopped while tracking continued

Southwest session `4576ea61-1ebe-4bce-bb3a-4b715511afc6` requested 120 seconds from `05:20:07.240958Z` through `05:22:07.240958Z`. The backend reported `completed`, `deadline-reached`, exactly that end time, and cleanup `confirmed`. Generation requested/connected/managed were all false. The embedding inventory was empty, with `active_live_streams=0` and `video_file_queries_pending=0`.

The session retained 24 indexed documents. The parent agent's actual browser test reported six results for “cars at an intersection”, restricted to the selected southwest camera and this finite interval. This verification did not repeat the search. `searchScope.applied=false` in the status response means the GET itself did not perform a search; it does not describe the separate UI search. Completed evidence correctly reports `liveFresh=false`.

Both camera analyses still reported active CV with detection true and embedding/resource false, under the on-demand policy. Both controller streams were running, both City sources were live, both processed previews were ready, and native rule revision 357 was applied and fresh. These are continuity and cleanup observations, not a sustained FPS or accuracy qualification.

Scope remains exact source aliases plus camera chunk-start timestamp bounds. It is not a persistent indexed-session tag. No global vectors were deleted.

## Public map consistency

The source map is the parent agent's new actor-free static capture with the same calibrated footprint, 1040×1120. The isolated dev public mount had an older PNG. With explicit authorization, only that mounted PNG was replaced atomically after archiving the previous file. Its previous runtime-readable mode 0664 was preserved. Both backend port 7781 and ingress port 7782 returned HTTP 200 with bytes matching source SHA-256 `b5e8efb8f7491d21da0c6fe1d1ccb80413dc604fa28f0d1586263b209b6430a1`. See [the map sync receipt](map-public-sync.json). Source map permissions remain 0600; production assembly explicitly sets readable public-file permissions.

## Isolated production target

At the pre-build inspection, the running UI was `city-polish-ui` in project `vss-city-polish`, container `vss-city-polish-ui`, on loopback port 7781 behind the existing ingress on 7782. It was a source-mounted Next dev server with a 4 GiB memory ceiling, 2 GiB Node heap and two CPUs. Its image is `sha256:3134f445308c4ccf95d4b28b01b4b9b8e0a1f120957900c17b6f1f1c27d60f8e`.

`tools/smart-city/ui_package.py` already supplies a guarded CPU-only build: frozen source/dependency hashes, explicit reuse of installed dependencies, no network during compilation, two CPUs, 4 GiB memory ceiling with no additional swap, 2 GiB Node heap, one Turbo task, one Next page worker and a total 20-minute deadline. No model/image rebuild is involved. Its cached ARM64 builder/fallback base currently resolves `vss-spark-vss-ui:source` to `sha256:0510e98cab5411523e795f23bd3f18f43564e8d574b29a1616687b0fc70ae3b5`.

The helper's generated overlay and printed cutover command target the shared `vss-ui` service. **Do not run that printed cutover for this isolated UI.** The source freeze and final focused controls tests must finish before prepare. Then:

1. Run `python3 tools/smart-city/ui_package.py prepare --reuse-installed-dependencies` and build that exact returned package with `python3 tools/smart-city/ui_package.py build --package-dir /absolute/returned/package`.
2. Keep the generated private manifest, source/dependency hashes, logs and immutable image ID. Convert only the overlay service key from `vss-ui` to `city-polish-ui` in a new private `compose-city-polish-production.json` alongside it. Do not copy private base environment into QA documentation.
3. Render/check with project `vss-city-polish`, base `.spark/city/polish-ui-compose.json`, and the new isolated overlay. The saved production base retains the required private environment, loopback port 7781, all three state mounts and existing ingress routing. At inspection, production and dev environment differed only in `NODE_ENV` and `NODE_OPTIONS`.
4. After the root agent reviews the build receipt, recreate only `city-polish-ui` using `--no-deps --force-recreate --no-build --pull never`. Do not recreate ingress, shared port 7777, Agent, CV, models or Isaac. Do not merge the dev compose file into production, since it would retain source/cache mounts.
5. Check actual browser camera previews, new map and overlays, scenario controls, finite capture status/search and retained-clip flow, then measure steady-state performance separately. Production should remove development compilation/HMR overhead; no FPS gain is claimed before measurement.

The intended cutover command, **only after review**, is:

```sh
docker compose --project-name vss-city-polish -f .spark/city/polish-ui-compose.json -f /absolute/package/compose-city-polish-production.json config --quiet
docker compose --project-name vss-city-polish -f .spark/city/polish-ui-compose.json -f /absolute/package/compose-city-polish-production.json up -d --no-deps --force-recreate --no-build --pull never city-polish-ui
```

The current dev rollback remains `.spark/city/polish-ui-dev.json`; recreating only its `city-polish-ui` restores the same source-mounted workflow. Historical production files `.spark/city/polish-ui-compose.json` and `.spark/city/polish-ui-pre-sprint-production.json` remain intact but contain earlier application snapshots. The new runtime is `/repo`, `node custom-server.js`, UID 65532/group 1000, CPU runtime, 2 GiB memory ceiling with no additional swap and 1 GiB Node heap, with no source or `.next` bind mounts. `custom-server.js` regenerates runtime `__ENV.js`; the packaging helper intentionally excludes the live generated file.

The subsequently authorized production build and isolated cutover passed at 05:37 UTC. See [the sanitized production receipt](ui-production-cutover.json). Canonical `.spark/city/polish-ui-compose.json` now pins image `sha256:840f5d98e50cc725ddc58d906b6e380843f2c38c9125c86211a95615d3f8c94b`; only its UI image field changed. The ingress container and both controller registrations were unchanged. All 127 focused tests passed, the parent agent reported actual main-app TypeScript exit 0, and all ten compilation tasks passed. The fresh canonical source hash matched the frozen package before cutover. HTTP page/map/status and both exact preview checks passed; root rendered-browser acceptance remains separate and pending.
