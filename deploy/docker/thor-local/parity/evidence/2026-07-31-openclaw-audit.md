# Thor OpenClaw alternate-lane audit (2026-07-31)

## Result

The OpenClaw plugin, NemoClaw sandbox policy, non-Brev loopback UI path, local OpenAI-compatible provider path, orchestrator MCP registration, alert-hook configuration, and all 16 current VSS skills are present in source. The Thor-local model endpoint is live, but the lane is **not runtime-qualified** because the pinned toolchain is not persistently installed at the normal host prefix, the sandbox image is absent, and no sandbox exists yet. A temporary strict offline install was used only to verify the partial cache.

This is an alternate local control plane. It does not require the warehouse sample dataset.

## Upstream/source comparison

- The audited OpenClaw implementation matches current official upstream `main` (`7732edf8fb38ef896b20f2a0a6a701a4db10dc57`) before the Thor fixes in this branch.
- `.openclaw/package.json` stages `../skills` during `npm pack`; a dry-run package contained 241 files and all 16 current `skills/*/SKILL.md` entries.
- `.openclaw/openclaw.plugin.json` registers the packaged `./skills` directory.
- `assets/vss_nemoclaw_policy.yaml` permits the sandbox host alias on the local model port `8000`, orchestrator MCP port `9988`, dashboard/hook port `18789`, and the VSS service ports used by the skills.
- `update_openclaw_config.py` configures non-Brev origin `http://127.0.0.1:18789`, registers `vss_orchestrator` at `http://host.openshell.internal:9988/mcp`, and can enable authenticated OpenClaw hooks.

## Thor-local evidence

Normal-prefix checks on 2026-07-31:

```text
node      /home/nvidia/.local/bin/node  v22.23.1
npm       /home/nvidia/.local/bin/npm   10.9.8
openclaw  MISSING
nemoclaw  MISSING
openshell MISSING
```

The already-running local provider is bound to the Docker host bridge and is reachable without a cloud API:

```text
GET http://172.17.0.1:8000/v1/models -> HTTP 200
served model id -> datasheet-chat
```

The sandbox-side provider URL is `http://host.openshell.internal:8000/v1`; that alias and port are explicitly allowed by the VSS policy. The source installer now accepts `--provider custom`, rejects malformed endpoint URLs before onboarding, and `--help` no longer requires provider state.

The bundled plugin documentation and default workspace bootstrap were also corrected to name the 16 skills that actually ship, instead of the removed six-skill prototype (`ngc`, `vss-prerequisites`, `vss-base`, and similar aliases).

## Runtime acceptance (all required)

Do not mark this family `passed_current` until a fresh Thor run records every gate below:

1. Install the pinned NemoClaw/OpenShell/OpenClaw toolchain and record versions; do not use an unpinned global `latest` install.
2. Onboard a sandbox with `NEMOCLAW_PROVIDER=custom`, model `datasheet-chat`, and `http://host.openshell.internal:8000/v1`.
3. Confirm the active OpenShell inference provider is the local URL and a normal OpenClaw chat returns a model response with tool calling.
4. Confirm the `vss` policy is active and sandbox access to the local provider, `9988`, and required VSS ports succeeds through `host.openshell.internal`.
5. Run `openclaw plugins doctor` inside the sandbox with no VSS plugin error.
6. Parse `openclaw skills list --json` and confirm all 16 repository VSS skills are installed and the `_nemoclaw` workspace overlay is active.
7. Confirm `http://127.0.0.1:18789/health` reports healthy and open the loopback UI locally (or through an SSH tunnel) using a fresh gateway token.
8. Start the host-side VSS orchestrator MCP and prove the OpenClaw agent can list profiles and call one read-only tool through `vss_orchestrator`.
9. With hooks enabled and a generated secret, send one synthetic authenticated hook and record its accepted run id.
10. With an alerts stack running, send one synthetic VSS alert through the OpenClaw notification integration and verify it appears in the OpenClaw dashboard/chat. This is the end-to-end acceptance gate; config presence alone is insufficient.

## Remaining blocker

A verified seven-file partial cache and temporary offline prefix now cover the
pinned framework binaries, but the exact sandbox image archive is not staged.
Completing the cache requires fetching that immutable image; persistent install
and sandbox creation remain lifecycle actions. No image pull, credential use,
container start/stop, or synthetic notification was performed. Once the user
approves that install/deploy phase, the existing local `datasheet-chat`
endpoint removes the cloud-model dependency.

## Focused static verification

```bash
bash -n deploy/docker/scripts/nemoclaw/init_nemoclaw.sh
python3 -m unittest \
  deploy/docker/scripts/tests/test_init_nemoclaw.py \
  deploy/docker/scripts/tests/test_openclaw_package.py \
  deploy/docker/scripts/tests/test_update_openclaw_config.py
```
