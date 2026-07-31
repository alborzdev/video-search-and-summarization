# Thor-local VIOS MCP packaging and isolated handshake — 2026-07-31

## Outcome

The source-shipped VST/VIOS FastMCP gateway is now a first-class Thor-local
service. Upstream includes its 22 tools, five prompts, stdio entry point, and
streamable-HTTP entry point, but omits a reproducible service from the released
VSS Compose graph. Thor supplies that missing packaging without changing its
tool implementations.

This is **not** a claim that the 22 backend workflows passed. The unified VIOS
stack remained stopped. A temporary isolated service container completed the
MCP initialize/list-tools/list-prompts handshake and was then removed; no tool
was called and no VSS resource was created, updated, or deleted.

## Immutable offline build contract

The local image uses:

```text
base image  python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c
platform    Linux/ARM64, CPython 3.12
wheel count 31 exact packages
requirements SHA-256 c5d31223fb85f9a20f47d51f456903c1c0237570c036465f83f5dfe7f3b90f44
wheel lock SHA-256   a65a8aa75b331209c996f99c05058e9301f50ddc7a5278da2c416ade06d6d70d
image ID    sha256:0a4f7d72370f2250e77b196f4955f76852c647fae666adc1b90be7d0ccba7f94
image size  74926389 bytes
image user  65534:65534
```

The verifier rejects unknown lock fields, unsafe filenames/archive members,
symlinks, non-regular files, missing or extra wheels, size/hash drift,
duplicate packages, and Name/Version metadata that differs from the exact
requirements. The connected stager reuses only a fully verified cache,
downloads into a mode-0700 temporary directory using the exact Python image,
and publishes atomically only after the committed lock passes. It never
regenerates the lock.

The production image built successfully with `--network=none --pull=false`.
Its installation uses `pip --no-index --no-deps`, followed by `pip check`; the
build context is restricted to the 31 wheels, their contracts, and the MCP
source.

## Runtime wiring and smoke evidence

The 33-service Thor graph now contains `vios-mcp`. It:

- binds FastMCP only to `127.0.0.1:${VST_MCP_PORT:-8001}`;
- targets existing VIOS REST at `http://127.0.0.1:30888/vst`;
- retains DNS-rebinding protection (`MCP_GATEWAY_ALLOW_ALL_HOSTS=false`);
- runs read-only with all capabilities dropped and `no-new-privileges`;
- uses only an 8 MiB `/tmp` tmpfs; and
- waits for healthy `vst-ingress` in the full graph.

The similarly named `VST_MCP_URL` intentionally remains the released Agent's
legacy VIOS REST root. `VIOS_MCP_ENDPOINT=http://127.0.0.1:8001/mcp` names the
actual MCP endpoint.

The isolated MCP client received:

```text
tools:   22 (exactly the checked-in source/manifest names)
prompts: 5  (picture_for_camera, picture_url_for_camera, sensors_count,
             sensors_recording_status, video_for_sensor)
```

Static qualification now derives the exact tools, prompts, and input-signature
hashes with AST-only extraction. The aggregate contract is 17 API surfaces,
326 declared REST operations (325 normalized unique), 38 MCP tools, and five
MCP prompts. The read-only runtime inventory is 22 services and 32 GET probes,
including `/mcp` with the bounded FastMCP transport status contract.

## Reproduction

```bash
deploy/docker/thor-local/vios-mcp/verify_wheelhouse.py
docker build --network=none --pull=false \
  -f deploy/docker/thor-local/Dockerfile.vios-mcp \
  -t cti-vss-vios-mcp:thor-local .
python3 deploy/docker/thor-local/qualification/qualify.py
deploy/docker/test-scripts/test-thor-runtime-infrastructure.sh
```

Current runtime acceptance still requires the operator-approved unified stack:
initialize the deployed endpoint, invoke every read-only tool, exercise each
owned mutation with exact cleanup, render all five prompts, and prove the
VIOS REST effects/results against current video data.
