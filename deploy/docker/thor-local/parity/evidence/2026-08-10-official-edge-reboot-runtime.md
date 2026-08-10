# Thor exact-model official-edge reboot qualification — 2026-08-10

## Result

After Thor rebooted at `2026-08-09 21:43:55` local time, the active VSS 3.2.1
Compose graph recovered with the exact official-edge inference lane and all
required consumers still wired to it. The active graph was resolved from:

- `deploy/docker/compose.yml`;
- `deploy/docker/thor-local/compose.yml`;
- `deploy/docker/thor-local/official-edge/compose.yml`; and
- `deploy/docker/thor-local/official-edge/compose.thor-demo-memory.yml`.

The live model services were healthy with these content-addressed images and
identities:

- `nvidia/NVIDIA-Nemotron-3-Nano-4B-FP8` on loopback port 30081, served by
  `ghcr.io/nvidia-ai-iot/vllm@sha256:b587dd56b4cb076209ad5156a626ac75f5a976d0e8e7d1e6a9fccd56d1bd65e8`;
- `nim_nvidia_cosmos3-nano-reasoner_bf16-final` on loopback port 8018, served
  by `nvcr.io/nvidia/vss-core/vss-rt-vlm@sha256:5403e0c8fa8b149e7ad15ab1b063b78d610e7a50297dba6ca550ac5cc5ef9504`.

`thor-local.sh model-check` exercised OpenAI-compatible chat completions on
the LLM and a four-ordered-image chat completion on the VLM. The complete Thor
preflight then passed, including the exact model identities, kernel settings,
cache-cleaner gate, model provider contracts, and the planned service-port
contract. This validation called the model providers directly; it did not call
the separately approval-gated VSS Agent `/generate` route.

## Operator recovery behavior

The Thor operator wrapper now detects the deployed official-edge overlays from
the `vss-agent` Compose labels. Its `status`, `doctor`, `model-check`, and
`preflight` commands therefore inspect the active Nemotron 3 Nano and Cosmos3
services instead of the inactive legacy datasheet model containers. Generic
`up` and `restart` fail closed while this graph is deployed, preventing an
operator command from silently replacing the exact-model consumer wiring.

Port ownership also accepts either an exact container name or the active
`mdx` Compose project/service labels. Compose-generated names such as
`mdx-node-exporter-1` no longer produce false port-collision failures, while an
unrelated container cannot claim the service's port identity.

The post-reboot doctor reported 40 passing runtime checks. Its remaining
non-runtime items were intentionally visible: the physical-interface firewall
was still awaiting its separately approved `sudo` transaction, and the data
disk had only 25 GiB free. Clearing the already approved Docker build cache
removed all 20.92 GB of rebuildable cache and left 26 GiB filesystem headroom;
no images, model caches, volumes, stopped containers, or user data were
deleted.

## Regression evidence

- `python3 deploy/docker/thor-local/official-edge/official_edge.py static`:
  passed.
- Complete official-edge unit suite: 48 passed.
- Thor demo wrapper-focused pytest suite: 7 passed.
- `deploy/docker/test-scripts/test-dev-profile.sh`: 199 passed, 0 failed.
- `bash -n deploy/docker/scripts/thor-local.sh`: passed.
- `git diff --check`: passed.

This receipt qualifies exact-model identity, direct LLM/VLM inference,
post-reboot discovery, and safe operator recovery. Higher-level VSS workflows
remain covered by their individual runtime receipts and approval boundaries.
