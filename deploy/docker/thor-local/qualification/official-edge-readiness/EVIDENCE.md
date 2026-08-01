# Read-only official-edge audit — 2026-07-31

The static official-edge verifier passed against the checked-in VSS 3.2.1
contract. A read-only host inspection then returned
`blocked_not_runtime_qualified`. No containers, images, volumes, credentials,
or files outside the repository were changed.

The current report has six blocking gate records. The exact-tree gate is
separate from the incomplete-lock gate so a future `complete_exact` metadata
change cannot pass until the source-locked verifier has hashed and matched both
candidate trees.

## Blocking gates

| Gate | Observation |
|---|---|
| Artifact lock | The checked-in lock is incomplete, so neither official model tree has a complete exact identity. |
| Exact tree verification | Prerequisites are missing; the source-locked verifier has not produced an `exact_match` for both candidate trees. |
| Nemotron artifact | Standard Hugging Face cache path is absent. The official lock has no revision or tree and remains `missing_exact_artifact_unqualified`. |
| Cosmos3 artifact | The official lock has no tree. Docker volume `mdx_rtvi-ngc-model-cache` exists, but its host path is permission-protected and volume metadata is not artifact identity evidence. NGC metadata lookup failed with `Invalid apikey`; no credential value was recorded. |
| Edge vLLM image | Exact digest `b587dd56…` is absent locally. The mutable tag currently resolves locally to different digest/image ID `6402d5ac…`, so it is not usable as the official image. |
| Unified memory | `MemAvailable / MemTotal` was approximately `0.257`, below the exact `0.80` admission threshold. |

## Unverified observations

| Gate | Observation |
|---|---|
| Disk | Approximately 64.9 GB was available. The known remote Nemotron plus compressed vLLM payload is 19,871,036,871 bytes, but Cosmos3 and installed/unpacked image requirements are unknown; capacity is therefore unverified. |
| Cosmos volume | The existing volume is discovery metadata only and is not model identity evidence. |
| Mutable vLLM tag | The local tag resolves to a non-required digest and cannot substitute for the exact image. |
| Runtime | `vss-nemotron-edge-4b` is absent. The existing VSS consumers and RT-VLM container are stopped and reflect an older/non-official resolved lane. Runtime qualification was not performed. |

## Exact local image observations

- Required RT-VLM `5403e0c8…`: present, `linux/arm64`, exact repository digest,
  Docker inspect size `14,063,585,731` bytes.
- Required edge vLLM `b587dd56…`: absent.
- Existing mutable-tag vLLM `6402d5ac…`: present but wrong digest, Docker
  inspect size `14,903,444,324` bytes.

Docker inspect `Size` is recorded only as Docker metadata; it is not equated to
compressed transfer size, additional disk required, or model artifact size.

The machine-readable command is documented in `README.md`. Its output contains
the complete blocker list, source-lock results, exact artifact/image identities,
candidate paths, memory/disk measurements, and non-mutating container metadata.
