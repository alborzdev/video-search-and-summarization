# Fast UI development

## DGX Spark

Use the independent Spark helper on this GB10 checkout. Do not execute
`tools/dev/ui.py` on Spark; that command manages the Thor runtime.

```sh
python3 tools/spark/ui.py deps
python3 tools/spark/ui.py dev
```

`deps` runs lockfile-backed `npm ci --include=dev --prefer-offline` using the
current Spark UI image's Node/npm runtime. It installs dependencies under
`services/ui` as the host developer and keeps its npm cache in ignored
`.spark/ui-npm-cache`, using the saved HTTPS registry. No host Node installation,
sudo, full image build, or model restart is needed. The built image's traced
standalone dependencies lack the Next dev CLI and ARM64 SWC binary; copying that
subset cannot support Turbopack or the scoped Jest/typecheck workflow. Existing
dependencies are reused for source edits; lockfile or workspace manifest changes
require running `deps` again, after returning to built mode.

`dev` recreates only `vss-ui`, reusing its existing image and preserving the
rendered Spark backend environment, network and history/report/rule mounts. It
mounts the full `services/ui` workspace and installed dependencies. The existing
Turbopack aliases resolve shared packages to `../../packages/.../lib-src` with
explicit `/server` entries. The process runs as UID 65532 with the developer's
group (1000 on this Spark); a shared umask keeps generated files accessible to
both. Its `.next` cache is isolated in `.spark/ui-next`. A bounded root container
adjusts only that generated cache's ownership; it does not chown source,
dependencies or saved application data. This uses existing Docker access and
does not require host sudo. The generated override is private
`.spark/compose-ui-dev.json`; the base `.spark/compose.json` remains unchanged.

The app's `tsconfig.json` resolves common and VSS packages to source and Nemo to
its existing checked-in public declarations, preserving the strict app check
without requiring generated package exports. Dedicated Nemo development entry
files use the source layout; Turbopack, webpack development and Jest use those
entries. Nemo's internal `@/` imports and development locale files resolve to
its source package. Production keeps its packaged locale path and exports.

Run the app check and the affected tests using the existing dev container:

```sh
docker exec -e NODE_OPTIONS=--max-old-space-size=2048 -w /workspace/apps/nv-metropolis-bp-vss-ui vss-agent-ui node ../../node_modules/typescript/bin/tsc --noEmit --incremental false
docker exec -e NODE_OPTIONS=--max-old-space-size=2048 -w /workspace/apps/nv-metropolis-bp-vss-ui vss-agent-ui node ../../node_modules/jest/bin/jest.js --runInBand __tests__/source-resolution.test.js
```

`tsconfig.source.json` instead checks Nemo implementation source directly. That
broader check currently exposes existing strict errors in Nemo chat/markdown
code; it is a separate diagnostic, not a passing app check. Do not relax the
app's strictness or build all packages to hide those errors.

Both dependency installation and dev switching require a GB10 host, the active
Spark guard, and at least the saved reserve plus 4 GiB available. The current
user-authorized reserve is 24 GiB. The dev process has a 2 GiB JavaScript heap
and a 4 GiB container ceiling with no additional swap; it uses the CPU runtime.
Keep Sim and model budgets unchanged. First-visit compilation can take longer
than a normal API request; watch `docker logs --tail 40 vss-agent-ui` and then
check the rendered flow and HMR. Do not infer UI readiness from container health.

Return to the last built image without rebuilding, or inspect the current mode:

```sh
python3 tools/spark/ui.py built
python3 tools/spark/ui.py status
python3 tools/spark/test_ui.py
```

If dev recreation fails, the helper attempts to restore only the built UI.
A successful process start still needs browser verification. A later bootstrap
`up` may restore built mode; reapply `dev` when continuing source edits. Saved
actions affect the same Spark development data in either mode. The September 30
runtime switch, populated server-rendered configuration, source hot reload and
browser rehearsal pass; see the [tradeshow UI receipt](qa/2026-09-30-spark-tradeshow-ui.md).
No steady-state HMR benchmark is claimed. Thor's reserve and tooling remain separate.

## Thor

For a fresh October candidate with `.thor/settings.json`, use
`python3 tools/thor/ui.py deps` followed by `python3 tools/thor/ui.py dev`.
`tools/dev/ui.py` automatically routes to that helper. It mounts source in a
bounded CPU Node container and preserves the 48 GiB guard. Direct port 3001
works while the backend gateway on 7777 is still being staged. See
[fresh Thor setup](../tools/thor/README.md). The historical workflow below
applies when that independent candidate has not been rendered.

The default workflow is source-mounted Next.js Turbopack development at http://10.88.9.12:7777 (current Thor LAN address). Run from the repository root:

```sh
python3 tools/dev/ui.py dev
```

This recreates only `vss-agent-ui`, reuses its existing image for Node, and mounts `services/ui` including its installed dependencies. It uses the built runtime UID (65532) with the host developer group so existing private data remains readable and new records retain the same owner. The helper adjusts only generated `.next` cache permissions for shared access. It preserves Compose networking, backend environment and the existing history, investigation and rule data mounts. Saved actions affect the same development data as the built site.

Edit UI source or CSS and watch the browser hot reload. Shared UI packages also resolve to source through the Next Turbopack aliases. Initial compilation is slower than subsequent edits. Configuration/dependency changes may require restarting this command. If dependencies are missing, run `npm ci` in `services/ui` first.

The dev process has a 2 GiB JavaScript heap and a 4 GiB container memory ceiling, with no swap allowance. Keep the current 48 GiB diagnostic memory guard enabled (see tools/runtime/README.md). Check compiler output with `docker logs --tail 40 vss-agent-ui`. If compilation is killed or runs out of heap, investigate the affected imports/workload before increasing its budget.

Return to the last built UI without rebuilding:

```sh
python3 tools/dev/ui.py built
```

Both commands use the existing Thor Compose configuration captured in `artifacts/thor-memory-2026-09-09/`; this is a local Thor workflow, not a general installer. The generated dev override is stored there. Normal source edits need neither a Docker image build nor a restart of inference services. A later whole-stack Compose recreation may restore the built UI; rerun the dev command afterward.

For verification, run the affected app's typecheck and relevant tests from `services/ui`, then inspect changed flows in the browser. Reserve the full monorepo Docker build for packaging changes or an intentional refresh of the built fallback. This project prioritizes development speed; production packaging is not the routine edit/test loop.

Measured on September 9: Turbopack initial page compilation about 8 seconds; CSS hot reload 227–236 ms. The prior webpack dev compiler used substantially more memory and tripped the runtime guard during the audit; Turbopack is selected explicitly by the helper.

The final smoke test ran all 33 service roles alongside this dev server. A real
17-result search passed with 38.05 GiB host memory available and a 1.76 GiB dev
container. Keep the reserve guard active: concurrent heavy workloads still need
admission control. The helper switches generated cache ownership to the runtime
for dev and back to the host user for built mode; it stops only the UI before
changing cache ownership.

September28 cold-start check: the Thor manager now allows15seconds for the UI
root request, since its first on-demand compilation took8.3–8.5seconds in two
observed recoveries. Backend/model probes retain their5-second deadlines. This
avoids reporting the whole startup as failed solely because a healthy dev UI is
compiling; an actual timeout or non200response still fails readiness. The scoped
regression checks are `python3 artifacts/thor-memory-2026-09-09/test_manage.py`.

Post-reboot audit correction: Turbopack aliases must use `../../packages/.../lib-src/index.ts` relative to the app, with explicit `/server` entries. The earlier `./packages/.../lib-src` entries silently fell back to compiled package exports. Confirm served chunks contain `video-management_lib-src` when testing shared components. The full 33-role stack crossed 48 GiB during UI use; the current audit leaves the unused warehouse detector stopped for development headroom. Historical 36 GiB screenshots and smoke tests above are not current runtime qualification.

For screenshots, enable **Presentation Mode**. The shell uses neutral device
branding and quiet presentation controls. System and the readiness popover still
expose actual service checks; exiting presentation restores the regular shell.
This display choice does not start services or change memory budgets.

September 28 recovery: the host LAN address changed. Updating ingress alone is insufficient: regenerate the UI public URLs, Kafka advertised address, and dependent services from the current generated environment. The recovery receipt is in `artifacts/thor-recovery-2026-09-28/`.
