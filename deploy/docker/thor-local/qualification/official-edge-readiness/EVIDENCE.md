# Read-only official-edge audit — 2026-08-09

The static official-edge verifier and exact artifact/image audit pass against
the checked-in VSS 3.2.1 contract. The exact Nemotron and Cosmos3 trees and both
digest-pinned model-serving images are local. No additional staging download is
required. The read-only host inspection remains
`blocked_not_runtime_qualified` only because the dynamic unified-memory gate is
below 0.80; runtime lifecycle and semantic qualification have not yet run.

The exact-tree gate remains separate from the complete-lock metadata gate. A
lock-only metadata change therefore cannot pass without hashing and matching
both complete local trees.

## Blocking gates

| Gate | Observation |
|---|---|
| Artifact lock | `complete_exact`; Nemotron and Cosmos3 entries are both `locked_exact`. |
| Exact tree verification | The source-locked verifier hashes and matches both complete candidate trees and the Hugging Face blob tree. |
| Nemotron artifact | Immutable revision `3fe6dab7…` is present and bound to the reviewed Hugging Face LFS hashes. |
| Cosmos3 artifact | The 34-file, 17,545,910,496-byte tree matches NVIDIA's signed NGC sigstore payload. |
| Edge vLLM image | Exact digest `b587dd56…` is present and `locked_exact`; Thor's containerd store reports that manifest digest as the local image ID. |
| Unified memory | At `2026-08-09T17:09:07.519439Z`, after temporarily stopping only `ctai-vision-playground-api`, `MemAvailable / MemTotal` was `0.367361`, below the exact `0.80` admission threshold. This is the sole prelaunch blocking gate. |
| Disk | Both model trees and both exact images are already local, so required additional staging bytes are zero. The audit observed `38,055,469,056` available bytes, sufficient for a pull-free launch. |

## Unverified observations

| Gate | Observation |
|---|---|
| Cosmos volume | The older existing Docker volume remains discovery metadata only; the separately staged and signed exact cache is the qualified artifact. |
| Mutable vLLM tag | The local tag resolves to a non-required digest and cannot substitute for the exact image. |
| Runtime | `vss-nemotron-edge-4b` is absent. The existing VSS consumers and RT-VLM container are stopped and reflect an older/non-official resolved lane. Runtime qualification was not performed. |

## Exact local image observations

- Required RT-VLM `5403e0c8…`: present, `linux/arm64`, exact repository digest,
  Docker inspect size `14,063,585,731` bytes.
- Required edge vLLM `b587dd56…`: present, `linux/arm64`, exact repository
  digest, local containerd image ID `b587dd56…`, Docker inspect size
  `14,586,489,321` bytes.
- Existing mutable-tag vLLM `6402d5ac…`: present but wrong digest, Docker
  inspect size `14,903,444,324` bytes.

Docker inspect `Size` is recorded only as Docker metadata; it is not equated to
compressed transfer size, additional disk required, or model artifact size.

The machine-readable command is documented in `README.md`. Its output contains
the complete blocker list, source-lock results, exact artifact/image identities,
candidate paths, memory/disk measurements, and non-mutating container metadata.
Current results also contain a producer-generated microsecond UTC capture time;
downstream freshness checks bind that field through the complete result digest
instead of trusting caller metadata or filesystem modification time.
