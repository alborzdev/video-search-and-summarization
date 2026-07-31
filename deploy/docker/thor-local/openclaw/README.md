# Thor-local OpenClaw toolchain

This lane turns the OpenClaw integration already shipped by VSS into a pinned,
reproducible Thor install. It uses the compatibility set selected by the current
VSS upstream notebook:

- NemoClaw `v0.0.48`, immutable commit
  `449f6f4e7f28cd6dbee075836c502b10f1b270ca`
- OpenShell `0.0.39`, exact Linux ARM64 release artifacts
- OpenClaw `2026.4.24` in the exact multi-architecture sandbox image digest
- local `datasheet-chat` at `http://host.openshell.internal:8000/v1`

The lock records every downloaded-file digest, the deterministic packed CLI
digest, and both the ARM64 image-manifest and image-config digests. The
networked stage and forced-offline install are separate. Installation
uses an explicit user-local prefix and does not change the npm global prefix,
shell profiles, credentials, services, containers, or sandboxes.

## Inspect the plan and current host

```bash
python3 deploy/docker/thor-local/openclaw/toolchain.py plan

python3 deploy/docker/thor-local/openclaw/toolchain.py verify-host \
  --prefix "$HOME/.local/share/vss/openclaw-toolchain"
```

`verify-host` is read-only. It checks the pinned binaries, exact sandbox image,
and the existing model server with `GET /v1/models`; it does not send a chat.

## Stage on a networked Thor or staging host

```bash
cache="$PWD/.cache/vss-openclaw-v0.0.48"
python3 deploy/docker/thor-local/openclaw/toolchain.py stage --cache "$cache"
python3 deploy/docker/thor-local/openclaw/toolchain.py verify-cache --cache "$cache"
```

The complete stage downloads and verifies source and OpenShell artifacts,
builds NemoClaw from the two committed npm lockfiles, proves a temporary npm
`ci` install with offline mode forced against the audited runtime lock, pulls the exact Linux/ARM64 sandbox image,
and saves the image into the cache. Copy the cache directory unchanged to an
offline Thor.

The default staging registry is `https://registry.npmjs.org/`. If direct npmjs
access is unavailable but an approved mirror is reachable, select it explicitly:

```bash
python3 deploy/docker/thor-local/openclaw/toolchain.py stage \
  --cache "$cache" \
  --npm-registry https://registry.npmmirror.com/
```

The registry identity is recorded in the cache manifest and reused by offline
verification/install so npm cache keys cannot silently drift. Package bytes
remain constrained by the integrity hashes in NVIDIA's committed lockfiles.
The cache verifier requires the exact committed source, OpenShell, CLI,
runtime-lock, and cached-lock membership: missing, duplicate, unlisted,
traversing, symlinked, or hash-mismatched artifacts fail closed. Before an
image archive can reach `docker load`, its single Linux/ARM64 config is checked
against the committed config digest and its layer inventory must agree with
that config.

For a source-and-binaries-only audit that deliberately omits the potentially
large image archive, pass `--skip-sandbox-image`. Such a cache is explicitly
partial and only verifies with `--allow-missing-image`.

## Install offline, user-local

Disconnect the destination from the network (or otherwise enforce an air gap),
then run:

```bash
cache=/path/to/vss-openclaw-v0.0.48
prefix="$HOME/.local/share/vss/openclaw-toolchain"

python3 deploy/docker/thor-local/openclaw/toolchain.py verify-cache --cache "$cache"
python3 deploy/docker/thor-local/openclaw/toolchain.py install \
  --cache "$cache" \
  --prefix "$prefix" \
  --load-sandbox-image
```

The install forces npm offline. `--load-sandbox-image` only imports the pinned
image; it does not create or start a container. Omit it if an operator manages
the Docker image separately.

## Configure the local provider

Review the non-secret environment before applying it:

```bash
python3 deploy/docker/thor-local/openclaw/toolchain.py provider-env \
  --prefix "$prefix" \
  --sandbox-name vss-thor
```

The output selects `NEMOCLAW_PROVIDER=custom`, model `datasheet-chat`, sandbox
URL `http://host.openshell.internal:8000/v1`, provider name
`vss-thor-local`, and the non-secret local placeholder key `local`. The sandbox
alias is needed because host loopback is not reachable from inside OpenShell.

Creating the sandbox is intentionally a separate, lifecycle-changing step. When
authorized, export the reviewed output and run:

```bash
bash deploy/docker/scripts/nemoclaw/init_nemoclaw.sh \
  --provider custom \
  --sandbox-name vss-thor \
  --model datasheet-chat \
  --endpoint-url http://host.openshell.internal:8000/v1 \
  --compatible-api-key local
```

Do not treat install or configuration presence as runtime acceptance. The VSS
parity gate still requires a fresh sandbox chat with tool calling, active policy,
plugin doctor, all 16 skills, loopback UI health, one read-only orchestrator MCP
call, an authenticated synthetic hook, and an end-to-end alert notification.
