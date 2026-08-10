# Thor official Edge model identity runtime qualification

This package proves the two exact NVIDIA VSS 3.2.1 Edge model contracts on
Thor using the already-running local services:

- `nvidia/NVIDIA-Nemotron-3-Nano-4B-FP8` through local vLLM
- `ngc:nim/nvidia/cosmos3-nano-reasoner:bf16-final`, served as
  `nim_nvidia_cosmos3-nano-reasoner_bf16-final` through RT-VLM

The executor first runs the exact-model Thor readiness contract, then verifies
the immutable image, artifact, mount, command, environment, model endpoint,
health, restart, and OOM identities. It performs one deterministic forced LLM
tool call and one deterministic VLM interpretation of a generated four-panel
image. Finally it proves that RT-VLM asset statistics and both container
identities match pre-state exactly.

Execution is inert unless the exact acknowledgement in `contract.json` is
provided. It uses numeric loopback only and does not stage models, start or
stop services, create resources, call the VSS Agent, register RTSP, or use the
Warehouse sample bundle.

```bash
python3 deploy/docker/thor-local/qualification/official-edge-model-identities-runtime/execute.py plan

python3 deploy/docker/thor-local/qualification/official-edge-model-identities-runtime/execute.py \
  execute \
  --ack I_ACK_OFFICIAL_EDGE_MODEL_IDENTITIES_AND_NO_STATE_CHANGE \
  --retain

python3 deploy/docker/thor-local/qualification/official-edge-model-identities-runtime/verify.py
```

The retained receipt contains hashes, sizes, fixed model identities, status
codes, counts, booleans, and durations. It does not retain prompts, generated
text, image bytes, endpoint URLs, local paths, credentials, request/session
identifiers, SDP, or ICE.
