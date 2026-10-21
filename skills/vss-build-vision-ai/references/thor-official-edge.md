# Thor official model precedence

This repository-local reference is the **mandatory model-selection entry point**
for every VSS profile on **AGX Thor or IGX Thor**. It takes precedence over the
Thor model recipe in `edge.md` and over Thor model notes in `base.md` and
`alerts.md`.

Those three older files remain byte-for-byte copies of reviewed upstream source
because the offline official-edge verifier uses them as provenance anchors. Their
Thor model commands are historical evidence, not an executable local recipe.
Operators may still use `edge.md` for its DGX Spark recipe and unified-memory
explanation, but **MUST NOT run its AGX/IGX Thor model command**. The exact
dual-model lane also overrides its periodic cache-cleaner step.

## Empirical runtime safety fuse

Two co-resident Cosmos3 + Nemotron runs on the 128 GiB Thor froze the whole host
and were reset by its 120-second hardware watchdog. Neither produced a kernel
OOM, thermal shutdown, container OOM, or orderly shutdown record. Treat this
hardware/configuration as unqualified for the full local dual-model graph.

Keep the model and GPU-capable service containers stopped, keep
`/usr/local/bin/sys-cache-cleaner.sh` stopped, and run `thor_demo.py audit`.
The audit requires a 64 GiB projected post-load reserve and intentionally blocks
this host. Use a split local-model lane or a remote OpenAI-compatible endpoint
for one model. The mounted second-model startup gate duplicates the admission
check, so a raw Compose command is not an override. Endpoint health alone does
not override this fuse.

## Canonical local contract

The machine-readable source of truth is
[`deploy/docker/thor-local/official-edge/contract.json`](../../../deploy/docker/thor-local/official-edge/contract.json),
and the operator workflow is
[`deploy/docker/thor-local/official-edge/README.md`](../../../deploy/docker/thor-local/official-edge/README.md).
The exact VSS 3.2.1 Thor identities are:

| Role | Required identity |
|---|---|
| Local LLM | `nvidia/NVIDIA-Nemotron-3-Nano-4B-FP8` |
| Local VLM artifact | `ngc:nim/nvidia/cosmos3-nano-reasoner:bf16-final` |
| RT-VLM served model | `nim_nvidia_cosmos3-nano-reasoner_bf16-final` |
| RT-VLM selector | `cosmos-reason3` |

`nvidia/NVIDIA-Nemotron-Edge-4B-v2.1-EA-020126_FP8` is an **older,
unqualified fallback identity** retained only in the anchored upstream files and
the discrepancy record. It is not equivalent to Nemotron 3 Nano 4B and **MUST
NOT** be downloaded, launched, probed, or written into `generated.env` for the
official Thor lane.

## Fail-closed operator flow

From the repository root, first run the networkless static contract check:

```bash
python3 deploy/docker/thor-local/official-edge/official_edge.py static
```

Then follow the official-edge README. Its checked-in artifact lock is
`complete_exact`, and the reviewed Nemotron and Cosmos3 trees plus both pinned
images are local on this Thor. Missing or changed artifacts remain a blocker:
do not fall back to the older Edge 4B identity, use a mutable image tag, or
silently substitute the repository's separate Qwen lane.

The official-edge renderer is pull-free and does not accept credentials.
Both `official_edge.py` and `thor_demo.py` preserve the exact identities while
applying the measured headroom fuse. The demo lane additionally enforces its
idle cache policy and expanded reboot fail-closed controls. An audit must pass
without override before any rendered command is used; neither renderer is a
bypass for this 128 GiB host.

If the user explicitly chooses an external OpenAI-compatible LLM instead, follow
the normal remote-endpoint validation flow. That is a user-selected remote lane,
not evidence that the official local Thor model contract is satisfied.
