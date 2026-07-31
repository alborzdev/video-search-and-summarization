# Thor VSS 3.2.1 offline staging evidence

Date: 2026-07-31  
Hardware: NVIDIA Jetson AGX Thor, Jetson Linux R38  
Acceptance target: NVIDIA VSS `v3.2.1` plus protected `main` commit
`7732edf8fb38ef896b20f2a0a6a701a4db10dc57`

This checkpoint proves that the current unified 2D Thor deployment and its
local provider dependencies are fully staged without claiming that the stopped
application stack has passed end-to-end runtime qualification.

## Reproducible checks

The following commands passed on the target Thor:

```bash
THOR_LOCAL_SOURCE_ONLY=true source deploy/docker/scripts/thor-local.sh
compose build --pull=false
deploy/docker/thor-local/provision-local-models.sh provision
deploy/docker/thor-local/provision-local-models.sh status
deploy/docker/scripts/thor-local.sh refresh-runtime
deploy/docker/scripts/thor-local.sh verify-offline
```

Results:

- All Thor-derived production images required by the unified graph and staged
  alternate lanes built successfully, including both Next.js applications,
  the checksum-locked offline Logstash derivative, both immutable VIOS codec
  derivatives, the audio-codec RT-VLM derivative, and all shared UI packages.
- All 28 unique images selected by the resolved 32-service Compose profile are
  present and recorded by content ID in the protected mode-`0600` runtime
  environment. The tegrastats exporter reuses the locked VSS Agent image and
  introduces no new image identity.
- NVIDIA's agent, behavior analytics, RT-CV, RT-Embed, VIOS ingress, VIOS
  sensor, and released LVS images are the ARM64 3.2.1 variants. The Video
  Analytics API remains at NVIDIA's intentional 3.2.0 release pin.
- Host RT-CV/Search model checksums match the versioned contract.
- All ten Cosmos-Embed shards and the Thor batch-8 video/text TensorRT engines
  pass the network-isolated cache verifier.
- The local vLLM image is pinned to
  `sha256:6402d5ac90223b9ba4434228f98aec798c5a8b942e770ee47528b4148e923105`.
- The local text snapshot is pinned to Qwen revision
  `95a723d08a9490559dae23d0cff1d9466213d989`; the local vision snapshot is
  pinned to revision `9cdc6310a8cb770ce18efaf4e9935334512aee45`.
- The private-bridge text provider and the stopped, additive
  `cti-vss-qwen3-vl` vision provider both match their exact image, model ID,
  served-name, and bind-address contracts.
- The verifier concluded that restart requires no image pull, build, NGC key,
  Hugging Face access, or model download.
- The protected runtime was refreshed again after the VIOS/audio derivative
  builds and the tegrastats port addition; the subsequent offline verifier
  passed all 28 selected image locks and all pinned host/model assets.

## Static regression checks

The following suites passed after the staging/model-lane changes:

- `test-dev-profile.sh`: 198 passed, 0 failed
- `test-thor-local-doctor.sh`: all passed
- `test-thor-local-security-models.sh`: all passed
- `test-thor-parity-manifest.sh`: all passed, including all 16 VSS skills
- Python Thor full-profile unit tests: 9 passed
- UI tests: 8 passed

## Deliberately open runtime gates

- The root-owned cache cleaner is active, and the refreshed offline verifier
  passed at capture time. The vision provider and current 32-service stack
  remain stopped because only
  about 34 GiB unified memory is available while the fail-closed vision-model
  start gate requires 50 GiB; API, UI, inference, alerts, search, and restart
  qualification are therefore not yet current.
- The physical-interface firewall has not yet been applied.
- Alternate lanes and optional integrations retain their exact current states
  in `manifest.json`; source/static closure is not promoted to a runtime pass.
  NVIDIA's optional warehouse sample bundle remains excluded from acceptance.
