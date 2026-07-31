# Thor-local VIOS MCP image

NVIDIA VSS 3.2.1 includes `services/vios/mcp`, with 22 FastMCP tools and five
prompts, but does not include that service in the released Docker Compose
graph. This directory supplies the reproducible Thor packaging contract.

`requirements-linux-aarch64.txt` pins the complete 31-package runtime closure.
`wheels-linux-aarch64.lock.json` pins every CPython 3.12 Linux/AArch64 wheel by
filename, byte size, and SHA-256. `verify_wheelhouse.py` rejects missing,
extra, non-regular, mismatched, unsafe, or metadata-inconsistent wheels.

While connected, stage the ignored wheel cache:

```bash
deploy/docker/thor-local/vios-mcp/stage-wheelhouse.sh
```

The stager uses an exact Python base-image digest, verifies a complete existing
cache before reusing it, downloads into a private temporary directory, and
publishes only after the immutable lock verifies. It never refreshes the lock.

Build without package-network access:

```bash
docker build --network=none --pull=false \
  -f deploy/docker/thor-local/Dockerfile.vios-mcp \
  -t cti-vss-vios-mcp:thor-local .
```

The Thor Compose overlay runs the image as UID/GID 65534, read-only, with all
capabilities dropped and `no-new-privileges`, on host loopback port 8001. Its
backend is the existing VIOS REST ingress at `http://127.0.0.1:30888/vst`.
`VST_MCP_URL` is intentionally unchanged because the released Agent uses that
misleading variable name for the VIOS REST root; `VIOS_MCP_ENDPOINT` is the
actual streamable-HTTP MCP endpoint.
