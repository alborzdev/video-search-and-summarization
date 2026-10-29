> Current Spark policy (operator request, October 28): saved reserve **5 GiB**, no additional startup allowance. The active memory guard and saved-reserve checks remain enabled. This supersedes older startup headroom and 20 GiB values below.

# Bounded Smart City UI packaging on Spark

## Preserved intermediate clock/proxy failure

Package `20261026T101539610628Z` / image `77c066…` was built immutably but its public proxy omitted nested native clock proof/mode. Strict browser guards correctly refused those frames; it is not the final accepted UI and its artifact is not relabelled. The new package below repairs only those public fields and adds real-metadata proxy round-trip controls. [Preserved failure/repair](../../docs/qa/smart-city-2026-10-26/native-capture-clock-proxy-repair.json).

## Current isolated UI on port 7782 — October 26

The deployed UI is **`city-polish-ui` in project `vss-city-polish`**, loopback 7781 through ingress 7782. Canonical configuration is `.spark/city/polish-ui-compose.json`. Package `20261026T102610382036Z` pins image `sha256:1d94d0350f90c2e4f120f0295553e6ed06d6b71789579378bf532a634605fc0f`, source `d4aee494f102dc2a60782060735fc22a879b5313cf5f140ea79543868ed0e25f` and artifact `41a60b1f584e4db68d67adf4c79823b8454b3e5f1efbf2f97d04552f2c909f53`. Ten tasks passed **2 m 4.333 s** using the validated installed dependencies without installs. Accepted layout/branding and the actor-free 1040×1120 map asset `c4d14670c7be4dea04b4d29f9bd3e252681c11ff00da92568456781c261e1a70` are retained. [Immutable build receipt](../../docs/qa/smart-city-2026-10-26/native-capture-clock-proxy-ui-build.json).

The final native/UI cutover preserved the scene/publisher and running CPU gateway, admitted new source sessions and left current recordings ready. Native image `4e6b73d1…`, profile `cadd8867…`, all 19 rules at revision 450, mobility revision 6 and eight pins are current. The rollback configuration immediately preceding this cutover is `.spark/city/runtime/source-native-sei-20261026/complete-install/old-ui-compose.json`; the earlier 085059/6781 pending-label package and 101539/77c066 proxy-failure artifacts remain separate history. Actual browser counters subsequently rendered 9.011/9.132 FPS over 57.82 s with exact views aligned; [final dashboard pixels](../../docs/qa/smart-city-2026-10-26/native-sei-final-dashboard.jpg) and accessibility state reported one joined person. The older shared-person screenshot showed zero and later accessibility showed one; keep that separate instant distinct. One real Ask/5.0304 s inspected clip played to completion. [Final health](../../docs/qa/smart-city-2026-10-26/native-sei-final-health.json) passed, including current HTTP map hash, 19 rules at revision 450, mobility revision 6, eight pins, current recordings, inactive indexing and five stories available/restored. The new native pedestrian success has no qualified camera completion under the original observation-gap bound; bounded booth acceptance is complete with those limits. [Browser](../../docs/qa/smart-city-2026-10-26/native-sei-final-browser-performance.json), [paired/display distinction](../../docs/qa/smart-city-2026-10-26/native-sei-qualified-shared-pair.json), [Ask](../../docs/qa/smart-city-2026-10-26/native-sei-final-ask-browser.json).

The activation transaction fails closed: it pauses the two owned sources and preserves receipts; it does **not** automatically restore old profile/UI/gateway files. The immediate pre-cutover archive includes the rejected intermediate clock/proxy version. Restoring that file is not an accepted rollback or a map pass. Routine recovery should recreate the current immutable UI above and use the normal prepared `isaac_demo.py start` path with current pins. Any engineering rollback must restore a coherent reviewed profile, gateway environment and UI, then verify new source sessions, rules, exact previews and map guards before presentation. Preserve both `install` and `complete-install` archives under `.spark/city/runtime/source-native-sei-20261026`.

The helper below prints a **`vss-ui` / `vss-spark`** command because that is its original shared-UI target. That command does not target the isolated 7782 service. For the current canonical isolated image, recreate only:

```sh
docker compose --project-name vss-city-polish -f .spark/city/polish-ui-compose.json config --quiet
docker compose --project-name vss-city-polish -f .spark/city/polish-ui-compose.json \
  up -d --no-deps --force-recreate --no-build --pull never city-polish-ui
```

For a **fresh** package, freeze UI source and run the existing prepare/build workflow, preferably explicit `--reuse-installed-dependencies` with the tested local install. Copy only the generated overlay's service key from `vss-ui` to `city-polish-ui` in a new private `compose-city-polish-production.json`; retain the helper's original overlay. Render it against `.spark/city/polish-ui-compose.json` under project `vss-city-polish`. After review, archive the canonical private file and update only its UI image pin to the reviewed immutable image ID, preserving the existing environment and all three data mounts. The October 26 canonical update changed only `services.city-polish-ui.image`. Do not merge a dev override into production or recreate ingress, shared port 7777, Agent, models or CV for a UI refresh.

An engineering-only return to the preserved source-mounted workflow is shown below. It is not routine recovery or current production qualification:

```sh
docker compose --project-name vss-city-polish -f .spark/city/polish-ui-dev.json \
  up -d --no-deps --force-recreate --no-build --pull never city-polish-ui
```

The pre-cutover canonical production file, dev file, prior production file and container identities are archived privately under `.spark/city/runtime/ui-production-cutover-20261026T053626Z`. Keep that archive, old images and package logs. Production uses `/repo`, `node custom-server.js`, UID 65532/group 1000, two CPUs, a 2 GiB memory ceiling with no additional swap and a 1 GiB Node heap; it has only the three existing data mounts and no source/cache mounts. Public files are copied readable/writable by the runtime owner; the new actor-free map hash was verified inside the image and through port 7782. Runtime `__ENV.js` is regenerated, not copied from dev.

The remaining sections describe the reusable packaging helper and its original shared-UI target.

For each packaging operation, freeze its source first. The helper builds the standalone production **VSS app**, including existing workspaces. It does not change model services, guards, drivers, recordings or the running UI, and never automatically recreates a service.

The separate shared development UI uses Turbopack and its private `.spark/ui-next` cache. This is not the isolated port-7782 production runtime. Production does not compile mounted TSX source: frozen changes must be packaged into an image.

## Admission and inputs

- Use the existing ARM64 Spark deployment and its active `vss-spark-guard.service`, with fresh `.spark/guard-status.json` telemetry.
- Keep the saved reserve at **at least 20 GiB**. Each stage requires the saved reserve **plus 4 GiB** available before starting; the helper monitors the saved floor while it runs.
- Keep at least 10 GiB free disk space. If headroom is unavailable, stop or pause only separately authorized work. The helper does not stop models or change capacity.
- The existing rendered UI image must already be cached. Its actual immutable image ID is captured and used as both Node builder and runtime base; there is no latest-image lookup or pull. The current Spark image supplies Node **22.22.3** and npm. The dependency stage verifies Node before installing.
- The saved npm registry must be HTTPS and contain no credentials/query/fragment. Installation uses the frozen lockfile, `npm ci --include=dev --prefer-offline`, and the existing private npm cache. Browser downloads are disabled.

## Prepare, then build

From the repository root:

```sh
python3 tools/smart-city/ui_package.py prepare
python3 tools/smart-city/ui_package.py build --package-dir /absolute/path/printed/by/prepare
```

When the registry is unavailable, explicitly reuse the already tested local installation instead:

```sh
python3 tools/smart-city/ui_package.py prepare --reuse-installed-dependencies
python3 tools/smart-city/ui_package.py build --package-dir /absolute/path/printed/by/prepare
```

This mode performs **no npm install or registry retry**. It requires the existing `services/ui/node_modules/.package-lock.json` and frozen root lockfile to be version 3. Every installed entry must match the frozen lock's version, resolved location, integrity metadata and workspace-link flag; required entries and actual package manifests must exist, and manifest versions must agree. Absent optional entries are counted explicitly. All root and workspace `node_modules` directories are copied into the new private snapshot. Only relative dependency/workspace symlinks whose real targets remain inside the copied installation/source are preserved; external, absolute and broken links are rejected.

The receipt records the installed lock hash, actual manifest hash, dependency roots, installed/absent-optional counts and a hash of the copied dependency bytes, file permissions and symlink targets. These are checked again before the offline compiler starts. This is reuse of the existing **unpacked installation**, whose code passed the earlier UI tests and TypeScript check. It is not a fresh `npm ci`, and comparing the lockfile's tarball integrity strings does not recompute tarball integrity from unpacked files. Source hashes exclude dependency directories; dependency hashes are recorded separately. An unpacked dependency byte change is detected by that separate receipt.

`prepare` makes a new private `.spark/smart-city-ui/<timestamp>/` snapshot. It excludes environment files, npm credentials, generated runtime environment scripts, dependencies, caches, package `lib` outputs, Next builds, logs and test output. Source symlinks require explicit review rather than being followed into unrelated files. The canonical VIOS DASH source is copied to the same `external/vios-dash` path used by the main Docker build.

The receipt records source/lockfile/Dockerfile hashes, the inspected base-image ID, the saved registry and a distinct fallback tag. The `vss-spark-vss-ui:source` tag is not overwritten. A changed prepared source or Dockerfile is rejected. Failed/completed packages cannot be silently reused; prepare a fresh one.

`build` runs dependencies and compilation sequentially in separate CPU containers with:

- `runtime=runc`, no GPU devices, `NVIDIA_VISIBLE_DEVICES=void`;
- **4 GiB memory and memory-plus-swap**, two CPUs, 512 PIDs, two-GiB Node heap;
- one Turbo task at a time and `CIRCLE_NODE_TOTAL=2`, which the installed Next 15.5.18 translates to one page worker;
- a **20-minute total deadline** for the build operation, guard monitoring and explicit compiler-container removal on failure/timeout;
- host networking for npm installation; compilation runs with `network=none`.

The first dependency attempt on Docker bridge networking and the second on host networking both failed with registry `ECONNRESET` errors before compilation. A host HTTPS probe also failed with unexpected TLS EOF. Keep both failed snapshots/logs for diagnosis; do not continue network retries for this candidate. Use the explicit offline reuse mode with a fresh snapshot. The lockfile, npm version, registry HTTPS checks and TLS verification remain unchanged; failed snapshots are not repaired in place.

With offline reuse, the dependency-install container is skipped entirely. Only the existing bounded `network=none` compile container runs before artifact assembly. The normal install mode remains available for a future separately chosen fresh candidate after registry access is restored.

The Turbo filter is `nv-metropolis-bp-vss-ui...`: seven SWC/TypeScript libraries, the Nemo **library** Next/CSS build, then the VSS Next build and bundle. The separate Nemo application is not rebuilt. Shared production exports are rebuilt; dev-only source aliases are not relied upon. Strict main-app checks are not disabled by this helper.

An artifact-only image build then replaces the VSS standalone in a derivative of the preserved base. It copies traced dependencies, static assets, public assets and current runtime-environment helpers, while retaining the base's other app and licenses. No Node compilation or npm installation runs in BuildKit. Compiler limits apply to the explicit builder containers; the short artifact-assembly operation remains supervised by the same guard/deadline. Public files remain writable by UID 65532 so `custom-server.js` can populate runtime public environment configuration.

Outputs include private logs, source/image identity receipts, and `compose-ui-production.json`. The override contains **no copied private base environment**, tokens or saved data; Compose inherits those from `.spark/compose.json`. It selects only the new UI image, production startup, CPU runtime, a one-GiB Node heap/two-GiB container ceiling, and the loopback city gateway. It does not mount `/workspace` or the dev `.next` cache.

## Explicit cutover and rollback

Review the receipt and image ID first. The helper prints the exact cutover command but does not execute it:

```sh
docker compose --project-name vss-spark \
  -f .spark/compose.json -f /absolute/package/path/compose-ui-production.json \
  up -d --no-deps --force-recreate --no-build --pull never vss-ui
```

Do **not** include `compose-ui-dev.json` in this command. Only the UI is recreated; base backend environment, host networking and history/investigation/rule mounts remain inherited. The generated override keeps the developer's group for access to existing saved data.

Qualify the root and `?workspace=smart-city` route, actual JS/CSS/font/logo assets, runtime public configuration, city JSON/SSE/range proxy, saved reports and memory. Model calls still need separate capacity admission. Browser transport/clock qualification remains unverified until actual browser evidence exists; packaging success does not enable `browserClockVerified` or make synthetic fixtures real inference.

Rollback to the unchanged built fallback:

```sh
docker compose --project-name vss-spark -f .spark/compose.json \
  up -d --no-deps --force-recreate --no-build --pull never vss-ui
```

Its original immutable identity and a separate `pre-city-*` tag are in the package receipt. To return to the frozen source UI, use `python3 tools/spark/ui.py dev` after satisfying its guard/headroom check. Keep old images, private logs and receipts until the candidate is qualified; no pruning is part of this workflow.

CPU-only helper checks (no build or Docker runtime changes):

```sh
python3 -m unittest discover -s tools/smart-city/tests -p test_ui_package.py
```
