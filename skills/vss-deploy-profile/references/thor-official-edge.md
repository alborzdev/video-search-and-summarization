# Thor official model precedence

This repository-local reference is the **mandatory model-selection entry point**
for every VSS profile on **AGX Thor or IGX Thor**. It takes precedence over the
Thor model recipe in `edge.md` and over Thor model notes in `base.md` and
`alerts.md`.

Those three older files remain byte-for-byte copies of reviewed upstream source
because the offline official-edge verifier uses them as provenance anchors. Their
Thor model commands are historical evidence, not an executable local recipe.
Operators may still use `edge.md` for its DGX Spark recipe, cache-cleaner steps,
and unified-memory explanation, but **MUST NOT run its AGX/IGX Thor model command**.

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

Then follow the official-edge README. Its checked-in artifact lock is currently
intentionally incomplete, so audit and command rendering stop until an operator
has separately staged and reviewed the exact licensed artifacts. Missing
artifacts are a blocker: do not fall back to the older Edge 4B identity, use a
mutable image tag, or silently substitute the repository's separate Qwen lane.

The official-edge renderer is pull-free and does not accept credentials. A later
connected staging operation may require credentials, but it must record exact
artifact revisions and tree hashes before this lane can render a launch command.

If the user explicitly chooses an external OpenAI-compatible LLM instead, follow
the normal remote-endpoint validation flow. That is a user-selected remote lane,
not evidence that the official local Thor model contract is satisfied.
