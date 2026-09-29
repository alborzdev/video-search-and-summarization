# Fast UI development on Thor

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

For screenshots, enable **Presentation Mode**. The shell then shows neutral NVIDIA Thor branding instead of the aggregate readiness warning. System and the readiness popover still expose actual service checks; exiting presentation restores the warning. This display choice does not start services or change memory budgets.

September 28 recovery: the host LAN address changed. Updating ingress alone is insufficient: regenerate the UI public URLs, Kafka advertised address, and dependent services from the current generated environment. The recovery receipt is in `artifacts/thor-recovery-2026-09-28/`.
