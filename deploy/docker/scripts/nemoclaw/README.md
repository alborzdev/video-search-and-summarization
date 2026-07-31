# NemoClaw VSS Installer

`init_nemoclaw.sh` bootstraps a NemoClaw sandbox on a local Ubuntu host (including AGX/IGX Thor), configures its model provider, installs the repository's OpenClaw plugin and complete `skills/` bundle, applies the VSS policy, and updates OpenClaw allowed origins. Brev secure links are supported but are not required; a non-Brev host uses the loopback dashboard plus an SSH tunnel for remote browsers.

It supports two onboard providers, selected with `NEMOCLAW_PROVIDER` or `--provider`:

- `build` — NVIDIA Endpoints (`integrate.api.nvidia.com`), authenticated with `NVIDIA_API_KEY`.
- `custom` — any OpenAI-compatible endpoint (e.g. a local vLLM), configured with `NEMOCLAW_ENDPOINT_URL` and `COMPATIBLE_API_KEY`.

## What It Does

When you run `init_nemoclaw.sh`, it:

1. Runs NemoClaw onboarding if `nemoclaw` is already available, or falls back to `$HOME/NemoClaw/install.sh`.
2. Configures the OpenShell inference provider to use NVIDIA Endpoints or the selected OpenAI-compatible endpoint.
3. Applies the VSS sandbox policy from `assets/vss_nemoclaw_policy.yaml`.
4. Packs and installs the OpenClaw plugin with the repository's current `skills/`.
5. Updates OpenClaw's allowed origins and prints the final OpenClaw UI URL when available.

## Expected Environment

This script is meant to run on a NemoClaw-ready Ubuntu machine with this repository already checked out. It is not architecture-specific; the model endpoint selected for OpenClaw must support the host. On Thor, use the `custom` provider with a local OpenAI-compatible server to keep inference local.

The following repo content is expected to exist:

- `skills/`
- `assets/vss_nemoclaw_policy.yaml`
- `deploy/docker/scripts/nemoclaw/update_openclaw_config.py`

The following host tools or resources are also expected:

- `python3`
- `docker`
- `sudo`
- a working NemoClaw install source at `$HOME/NemoClaw/install.sh`, unless `nemoclaw` is already in `PATH`

## Usage

Choose a provider with `NEMOCLAW_PROVIDER` or `--provider`. The script exits before making changes if neither is set.

### `build` provider (NVIDIA Endpoints)

```bash
NEMOCLAW_PROVIDER=build \
NVIDIA_API_KEY="$NVIDIA_API_KEY" \
  bash deploy/docker/scripts/nemoclaw/init_nemoclaw.sh demo
```

Or use explicit flags:

```bash
NEMOCLAW_PROVIDER=build \
  bash deploy/docker/scripts/nemoclaw/init_nemoclaw.sh \
    --sandbox-name demo \
    --model nvidia/nemotron-3-super-120b-a12b \
    --nvidia-api-key "$NVIDIA_API_KEY"
```

### `custom` provider (OpenAI-compatible endpoint)

`NEMOCLAW_ENDPOINT_URL` and `COMPATIBLE_API_KEY` are required when `NEMOCLAW_PROVIDER=custom`:

```bash
NEMOCLAW_PROVIDER=custom \
NEMOCLAW_ENDPOINT_URL=http://host.openshell.internal:8000/v1 \
NEMOCLAW_MODEL=datasheet-chat \
COMPATIBLE_API_KEY=EMPTY \
  bash deploy/docker/scripts/nemoclaw/init_nemoclaw.sh demo
```

Equivalent with CLI flags:

```bash
NEMOCLAW_PROVIDER=custom \
  bash deploy/docker/scripts/nemoclaw/init_nemoclaw.sh \
    --sandbox-name demo \
    --model datasheet-chat \
    --endpoint-url http://host.openshell.internal:8000/v1 \
    --compatible-api-key EMPTY
```

`host.openshell.internal` is the policy-approved host alias inside the sandbox. The local server must listen on a host/bridge address reachable through that alias, not only on host loopback. Before onboarding, verify the server from the host and use the returned model id as `NEMOCLAW_MODEL`:

```bash
curl -fsS http://172.17.0.1:8000/v1/models | jq -r '.data[].id'
```

The bridge address above is the Thor reference deployment's bind address. If the server uses another local address or port, probe that address and add the selected port to the `vss-backend` policy before onboarding.

### Background run on a Brev instance

```bash
nohup env NEMOCLAW_PROVIDER=build NVIDIA_API_KEY="$NVIDIA_API_KEY" \
  bash /home/ubuntu/video-search-and-summarization/deploy/docker/scripts/nemoclaw/init_nemoclaw.sh \
  > /tmp/nemoclaw_install.log 2>&1 &
```

## Options

| Option | Description | Default |
|---|---|---|
| `--provider NAME` | `build` or `custom`; equivalent to `NEMOCLAW_PROVIDER` | required |
| `--sandbox-name NAME` | Target sandbox name | `demo` |
| `--model NAME` | NemoClaw inference model | `nvidia/nemotron-3-super-120b-a12b` |
| `--nvidia-base-url URL` | NVIDIA API base URL for the `build` provider | `https://integrate.api.nvidia.com/v1` |
| `--nvidia-api-key KEY` | API key for the `build` provider | `NVIDIA_API_KEY` env fallback |
| `--endpoint-url URL` | OpenAI-compatible endpoint URL (required when `NEMOCLAW_PROVIDER=custom`) | — |
| `--compatible-api-key KEY` | API key for the OpenAI-compatible endpoint (required when `NEMOCLAW_PROVIDER=custom`) | — |
| `--openclaw-config-script PATH` | Path to `update_openclaw_config.py` | `deploy/docker/scripts/nemoclaw/update_openclaw_config.py` |
| `--policy-file PATH` | Custom sandbox policy file | `assets/vss_nemoclaw_policy.yaml` |
| `--help` | Show usage help | n/a |

## Environment Variables

The script also honors these environment variables:

- `VSS_REPO_DIR`: repo root used to resolve plugin assets and the default policy file
- `NEMOCLAW_SANDBOX_NAME`
- `NEMOCLAW_PROVIDER` (**required**) — `build` or `custom`
- `NEMOCLAW_ENDPOINT_URL` — OpenAI-compatible endpoint URL; required when `NEMOCLAW_PROVIDER=custom`
- `COMPATIBLE_API_KEY` — API key for the OpenAI-compatible endpoint; required when `NEMOCLAW_PROVIDER=custom`
- `OPENSHELL_PROVIDER_NAME`
- `NEMOCLAW_MODEL`
- `NVIDIA_BASE_URL`
- `NVIDIA_API_KEY`
- `OPENCLAW_CONFIG_UPDATE_SCRIPT`
- `NEMOCLAW_POLICY_FILE`
- `VSS_CONTAINER_NAME`: explicit OpenShell gateway container name, if autodetection is not sufficient
- `VSS_NAMESPACE`: Kubernetes namespace for the sandbox pod, default `openshell`
- `BREV_LINK_DOMAIN`: optional secure-link domain override; Netbird selects `apps.run.brev.nvidia.com`, otherwise `brevlab.com`

## Expected Output

Successful runs usually include log lines like:

```text
[init_nemoclaw] Start installing/onboarding NemoClaw
[init_nemoclaw] Finished installing/onboarding NemoClaw
[init_nemoclaw] Applying custom policy file /home/ubuntu/video-search-and-summarization/assets/vss_nemoclaw_policy.yaml to sandbox demo
[init_nemoclaw] VSS skills installed
[init_nemoclaw] Updating OpenClaw config for sandbox demo using script /home/ubuntu/video-search-and-summarization/deploy/docker/scripts/nemoclaw/update_openclaw_config.py
OpenClaw UI at https://18789-<brev-id>.<brev-link-domain>/#token=<token>
```

If the config update succeeds, the helper also prints:

- `Updated /sandbox/.openclaw/openclaw.json` or `No JSON change needed ...`
- `Brev instance ID: ...`
- `Origin allowed in OpenClaw: https://18789-<brev-id>.<brev-link-domain>`
- `Dashboard token: ...`

## Troubleshooting

- Verify `NEMOCLAW_PROVIDER` is set (`build` or `custom`) — the script exits immediately if it is unset.
- For `NEMOCLAW_PROVIDER=custom`, verify both `NEMOCLAW_ENDPOINT_URL` and `COMPATIBLE_API_KEY` are set (or pass `--endpoint-url` / `--compatible-api-key`).
- For the `build` provider, verify `NVIDIA_API_KEY` is set before running the installer; the `custom` provider does not use it.
- If NemoClaw onboarding fails, verify `nemoclaw` is resolvable or that `$HOME/NemoClaw/install.sh` exists and is executable.
- If the custom policy is skipped, confirm `assets/vss_nemoclaw_policy.yaml` exists or pass `--policy-file`.
- If the skills upload is skipped, verify the repo checkout includes `skills/`.
- If the skills upload cannot determine a gateway container, set `VSS_CONTAINER_NAME` explicitly.
- If the OpenClaw origin update fails, run `python3 deploy/docker/scripts/nemoclaw/update_openclaw_config.py demo` directly to inspect the underlying error.
