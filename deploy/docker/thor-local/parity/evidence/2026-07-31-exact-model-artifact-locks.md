# Exact Thor model artifact locks — 2026-07-31

## Outcome

The default Thor inference artifacts now have one reviewed, fail-closed lock
covering every visible Qwen snapshot link and the exact Cosmos-Embed model and
Triton subtrees. A full real `thor-local.sh verify-offline` passed after the
protected runtime was refreshed to 29 image identities.

This is artifact integrity and semantic evidence, not live inference evidence.
No model/cache file or persistent service-container state was changed. Exact
subtrees were streamed from the named volumes through disposable, networkless,
read-only helpers with volume copy-up disabled; each helper was removed
automatically. Verification therefore remains valid after `compose down`.

## Locked scope

```text
lock SHA-256     5b0030ba13fb1ccee5950e3c4b78d334d8dd0c30a2a45ce90e6166a57fe31d09
entries          149 files/snapshot links plus 7 directories
resolved bytes   62553263321
indexed tensors  66018
```

| Artifact | Immutable source | Locked tree |
| --- | --- | --- |
| Qwen LLM | `Qwen/Qwen3.6-35B-A3B-FP8` at `95a723d08a9490559dae23d0cff1d9466213d989` | 52 snapshot links, 42 shards, 37,492,937,842 resolved bytes, 64,196 tensors |
| Qwen VLM | `Qwen/Qwen3-VL-8B-Instruct-FP8` at `9cdc6310a8cb770ce18efaf4e9935334512aee45` | 11 snapshot links, 2 shards, 10,605,560,594 resolved bytes, 1,002 tensors |
| Cosmos model | `nvidia/Cosmos-Embed1-448p-anomaly-detection` at `3b1455ed97c7b1d5419c0c3129b7199ca4cd9382` | 76 files/3 directories, 10 shards, 4,793,036,482 bytes, 820 tensors |
| Cosmos Triton | TensorRT FP16 repository derived from that Cosmos revision for NVIDIA Thor | 10 files/4 directories, 9,661,728,403 bytes |

Qwen scope is only the two exact snapshot trees and their referenced blob
identities, never unrelated Hugging Face cache blobs. Cosmos scope is only the
selected model and Triton subtrees, never unrelated volume content.

## Semantic verification

The verifier goes beyond path and SHA-256 checks. It rejects traversal,
absolute/escaping symlinks, non-regular nodes, duplicate JSON/tar members,
membership or mode drift, truncation, unsafe archive entries, and changed
provenance. It then validates:

- Qwen architecture/model type, FP8 e4m3/block/dynamic settings, expert/layer
  structure, exact shard/index membership, and SafeTensors ranges;
- Cosmos architecture, 768-dimensional embedding contract, 8 video frames at
  448 resolution, exact ten-shard index, and Hugging Face revision metadata;
- agreement among all 66,018 index entries and SafeTensors headers, including
  non-overlapping bounded payload ranges; and
- Triton model names, TensorRT platform, batch-8 Thor FP16 default filenames,
  input/output types and dimensions, GPU instance contract, and derivation from
  the locked Cosmos revision.

The Triton tree contains both batch-8 and batch-64 engine files, and both are
integrity-locked. Only the current batch-8 pbtxt/default selection and
qualification passed; batch 64 is **not** a runtime claim.

## Runtime/container provenance

The current selected Compose/service contract is the protected 3.2.1
RT-Embed image and passed the 29-image lock. The original lock capture used a
stopped 3.2.0 volume-view container; its exact image identity is recorded as
capture provenance rather than misrepresented as the current service image.
Current verification depends only on the exact named volumes and selected
3.2.1 image, not on that service container's continued existence.

## Reproduction

```bash
python3 -m pytest -q \
  deploy/docker/thor-local/models/tests/test_verify_artifacts.py
deploy/docker/test-scripts/test-thor-local-security-models.sh
deploy/docker/thor-local/provision-local-models.sh status
deploy/docker/scripts/thor-local.sh verify-offline
```

Results: 21/21 adversarial model-verifier tests, 17/17 security/model checks,
198/198 developer-profile tests, and the complete offline gate passed. Live
Qwen generation, Cosmos embeddings, batch performance, and VSS workflows
remain part of the operator-approved runtime acceptance phase.
