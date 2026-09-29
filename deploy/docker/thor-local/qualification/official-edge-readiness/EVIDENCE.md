# Read-only official-edge audit — 2026-08-09

> **Safety supersession — 2026-08-30:** Historical evidence only. Two later
> whole-host watchdog resets revoke this record as launch authorization for
> the co-resident exact LLM/VLM graph. The previously reported ~11 GiB live
> headroom is unsafe; keep the graph stopped and use a split/remote topology.

The static official-edge verifier and exact artifact/image audit pass against
the checked-in VSS 3.2.1 contract. The exact Nemotron and Cosmos3 trees and both
digest-pinned model-serving images are local. No additional staging download is
required. NVIDIA's unchanged `0.80` official-memory admission remains a
prelaunch-only gate; the exact-model Thor demo lane now has separate live
runtime evidence at its measured `0.12` LLM / `0.35` VLM settings.

At `2026-08-09T18:15:34.609074Z`, `thor_demo.py readiness` passed after the
complete Thor-full graph started pull-free. Both exact model containers, Agent,
LVS, VIOS, embedding, RT-CV, VA-MCP, Elasticsearch, Kafka, Redis, Phoenix,
Prometheus, Grafana, Kibana, and Tegrastats were running and healthy where a
healthcheck is defined. The two model containers had zero restarts and no OOM.

The exact-tree gate remains separate from the complete-lock metadata gate. A
lock-only metadata change therefore cannot pass without hashing and matching
both complete local trees.

## Qualification gates

| Gate | Observation |
|---|---|
| Artifact lock | `complete_exact`; Nemotron and Cosmos3 entries are both `locked_exact`. |
| Exact tree verification | The source-locked verifier hashes and matches both complete candidate trees and the Hugging Face blob tree. |
| Nemotron artifact | Immutable revision `3fe6dab7…` is present and bound to the reviewed Hugging Face LFS hashes. |
| Cosmos3 artifact | The 34-file, 17,545,910,496-byte tree matches NVIDIA's signed NGC sigstore payload. |
| Edge vLLM image | Exact digest `b587dd56…` is present and `locked_exact`; Thor's containerd store reports that manifest digest as the local image ID. |
| Official unified-memory lane | Historical only: NVIDIA's `0.25 + 0.35 + 0.20` fraction gate did not prevent the later whole-host stalls and is no longer sufficient launch authorization here. |
| Thor demo unified-memory lane | Historical only: the `0.12 + 0.35 + 0.23` gate passed, but the full graph retained only `11,663,872` kB available and was later disqualified by watchdog resets. |
| Elasticsearch disk admission | Thor's single-node overlay uses absolute free-space watermarks of 20/15/10 GB. Elasticsearch recovered from red to healthy without deleting data. |
| Disk | Both model trees and both exact images are local, so required additional staging bytes are zero. The live graph retained `64,963,608,576` available bytes. |

## Unverified observations

| Gate | Observation |
|---|---|
| Cosmos volume | The older existing Docker volume remains discovery metadata only; the separately staged and signed exact cache is the qualified artifact. |
| Mutable vLLM tag | The local tag resolves to a non-required digest and cannot substitute for the exact image. |
| Semantic feature workflows | Identity/readiness is complete. Per-feature ingestion, search, summarization, Q&A, alert, calibration, audio, and reporting acceptance remains tracked separately by the main capability campaign. |

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
