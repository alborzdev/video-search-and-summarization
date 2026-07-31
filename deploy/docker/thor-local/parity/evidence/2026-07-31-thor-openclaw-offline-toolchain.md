# Thor OpenClaw pinned/offline toolchain lane (2026-07-31)

## Result

The source gap identified by the OpenClaw audit is closed: Thor now has a
checked-in immutable compatibility lock and a reproducible split-stage install
path that uses the existing local `datasheet-chat` provider. The install is
user-local, npm is forced offline, and no global package install, credential,
container lifecycle, hook, message, or sandbox action is required to prepare or
verify the binaries.

The complete cache, persistent user-local installation, exact Linux/ARM64
sandbox image, and local provider now pass `verify-host`. This removes the
artifact blocker, but it does **not** constitute runtime qualification. No
OpenShell sandbox was created and no chat, tool, orchestrator MCP, hook, or
alert workflow was invoked; those lifecycle gates remain pending.

## Locked compatibility set

The current official VSS upstream notebook pins NemoClaw `v0.0.48`. Inspection
of that immutable source yielded the complete tested set:

```text
NemoClaw tag       v0.0.48
NemoClaw commit    449f6f4e7f28cd6dbee075836c502b10f1b270ca
OpenShell          0.0.39
OpenClaw           2026.4.24
sandbox image      ghcr.io/nvidia/openshell-community/sandboxes/openclaw@sha256:b3d832b596ab6b7184a9dcb4ae93337ca32851a4f93b00765cc12de26baa3a9a
ARM64 manifest     sha256:f0975cb409beb3dd87915ca48c4935fa540dbeb55e222e108493980c1573bc8d
ARM64 config       sha256:d4f437133b8775703f67213f2ed79362bfbff31f291d3f9db68aaea4bc5a66a7
packed CLI         sha256:bd134423f87f51c72a6ab7499fe46f334a48087849f2ed2ab3b23b3c5e45bfd0
provider model     datasheet-chat
sandbox base URL   http://host.openshell.internal:8000/v1
```

The lock also records the source archive, both upstream npm lockfiles, and all
three required OpenShell Linux/ARM64 artifact hashes. Downloaded content is
verified before use. The image index was inspected read-only and includes the
locked ARM64 manifest.

## Implemented path

- `toolchain.py stage` is the only networked phase. It verifies immutable
  downloads, builds from both upstream npm lockfiles, proves a separate
  forced-offline `npm ci`, and (unless explicitly skipped) saves the exact
  sandbox image for air-gap transfer.
- `verify-cache` requires the exact committed seven-file partial-cache set
  (or eight files with the sandbox archive), rejects omissions, additions,
  duplicates, symlinks, traversal, and tampering, and repeats the offline
  install in a temporary prefix. A staged sandbox archive must contain exactly
  one Linux/ARM64 image whose config digest matches the committed identity
  before it can be passed to `docker load`.
- `install` writes only below the operator's explicit prefix, refuses to
  overwrite existing toolchain targets, verifies CLI versions and OpenShell's
  request-body/WebSocket credential rewrite features, and optionally loads the
  exact image without starting it.
- `provider-env` emits only the custom local-provider selection, model, sandbox
  URL, and non-secret `local` placeholder key.
- `verify-host` is read-only: versions/image inventory plus `GET /v1/models`.

## Fresh Thor evidence

The resilient image-only continuation path completed the earlier interrupted
connected stage without rerunning npm. It first verified the exact partial
cache, pulled the locked Linux/ARM64 image identity, saved and
cryptographically verified Docker's OCI archive layout, then atomically
promoted the cache manifest. Current identities are:

```text
complete cache       .cache/vss-openclaw-complete-v0.0.48
cache size           1.6G
cache manifest       ff42fa878957f20b153b1f4d0dfbefb8eac98fb254d1741ca8156b4d01857b84
sandbox archive      d90a4a9bda8f5d758167d610ce6c5119457355f62ed4307057ca7c20a1da6a7e
sandbox archive size 1460780544 bytes
persistent prefix    /home/nvidia/.local/share/vss/openclaw-toolchain
prefix size          110M
```

The current cache and persistent installation verify as:

```text
PASS: verified complete cache
PASS platform: linux/arm64
PASS node: v22.23.1
PASS nemoclaw: nemoclaw v0.0.48
PASS openshell: openshell 0.0.39
PASS sandbox-image: ghcr.io/nvidia/openshell-community/sandboxes/openclaw@sha256:b3d832b596ab6b7184a9dcb4ae93337ca32851a4f93b00765cc12de26baa3a9a
PASS local-provider: datasheet-chat
READY FOR RUNTIME ACCEPTANCE
```

The local model discovery endpoint returned the expected `datasheet-chat` id
without sending an inference request. No sandbox or application container was
started by these OpenClaw verification commands.

## Remaining runtime gates

1. With explicit lifecycle authorization, onboard the `vss-thor` sandbox using
   the emitted custom-provider environment.
2. Qualify normal chat plus tool calling, active VSS policy, plugin doctor, all
   16 repository skills, `_nemoclaw` overlay, and loopback UI health.
3. Start the host orchestrator MCP and prove one read-only profile/tool call.
4. Generate a hook secret and qualify one synthetic authenticated hook.
5. With the alerts stack running, qualify one end-to-end synthetic VSS alert in
   OpenClaw dashboard/chat.

No runtime gate above was inferred from source or install success.

## Focused verification

```bash
python3 -m unittest -v \
  deploy/docker/scripts/tests/test_thor_openclaw_toolchain.py

python3 deploy/docker/thor-local/openclaw/toolchain.py verify-cache \
  --cache .cache/vss-openclaw-complete-v0.0.48

python3 deploy/docker/thor-local/openclaw/toolchain.py verify-host \
  --prefix /home/nvidia/.local/share/vss/openclaw-toolchain
```

The focused suite now passes 21 tests, including adversarial empty/unlisted
cache manifests, archive traversal, exact classic and OCI Docker-save
descriptor/config/layer validation, modern image-store identity handling,
mutable `RepoTags` rejection, provider-environment shell quoting, and
committed ARM64 config identity checks.
