# Thor RT-VLM model-matrix audit and local CR2 lane

Date: 2026-07-31

The source-anchored matrix records all 11 exact variants advertised by the
RT-VLM README at upstream main `7732edf8fb38ef896b20f2a0a6a701a4db10dc57`,
plus the remote OpenAI-compatible adapter. It keeps Cosmos3 Super separate as a
base-profile NIM route and does not collapse the two distinct Nemotron Omni
repository identifiers.

Every missing exact advertised artifact remains
`missing_exact_artifact_unqualified`. In particular, the existing Qwen3.6
language model is not represented as a Qwen3.5 RT-VLM lane.

Two already-present official Hugging Face snapshots are newly content-locked:

- `nvidia/Cosmos-Reason2-8B` revision
  `a9fae2cf89dc64db96b12860417f0eb403013bb9`, 17,545,907,076 logical bytes;
- `nvidia/Cosmos-Reason2-2B` revision
  `3dafcf35a57ce708a32241e06d6533c9c3ee0ab8`, 4,888,970,298 logical bytes.

The 8B snapshot is a family lane only: equivalence to NVIDIA's advertised NGC
`hf-0303` artifact is unproven. The 2B snapshot is not in the advertised table.
Both locks verify every file and resolved blob, SafeTensors header, tensor
membership, architecture, and immutable revision. The 8B source index literally
contains `metadata.total_size=0`; that advisory value is locked but not used as
the tensor-byte oracle.

An inactive, pull-free CR2 8B BF16 Compose overlay mounts the model read-only and
places vLLM cache/lock state in writable tmpfs. The same separation fixes the
Omni read-only model contract. A shared admission check now requires
`MemAvailable >= (vLLM utilization + 0.20) * MemTotal`; Omni's default utilization
is 0.45 and retains its 80 GiB floor.

Evidence collected:

- exact verification of both real local CR2 snapshots passed;
- 7 matrix/runtime-state/memory tests passed;
- 23 artifact-verifier tests passed;
- 13 audio/Omni tests and the resolved Compose contract passed.

At audit time Thor had about 33 GiB available. CR2 at utilization 0.35 required
about 67.6 GiB, so admission correctly blocked. No RT-VLM runtime qualification
is claimed and no model was downloaded.
