# VSS 3.2.1 Agent model contract for Thor

This directory is a static, fail-closed oracle for the models NVIDIA names for
the VSS 3.2.1 Agent reasoning LLM and video-understanding VLM. It deliberately
does not download a model, inspect a live endpoint, or start/stop a container.

The distinction between two NVIDIA statements matters:

- The Agent customization pages name models that the general developer profile
  can select locally and say only each default is verified for local deployment.
- The 3.2.1 prerequisites list AGX/IGX Thor as **remote-LLM** configurations and
  say fully local deployment of all Agent workflows is planned for a future
  release.

Consequently, `local_models` means NVIDIA's general Agent selector contract; it
does not mean every model is officially supported on Thor. `thor-state.json`
records what is staged on this host without promoting a partial artifact, a
quantized alternate, or an endpoint adapter into an exact-model qualification.

## Two denominators

`thor-requirements.json` makes two deliberately separate questions
machine-readable:

1. `canonical_official_edge_pair` is the required Thor-local deployment lane:
   exact Nemotron 3 Nano 4B FP8 plus the Cosmos3 Nano BF16 RT-VLM artifact. Its
   identities come from `official-edge/contract.json`, not from the general
   Agent selector list. This is what `--require-thor-complete` means.
2. `all_advertised_agent_selectors` is the stronger, exhaustive compatibility
   matrix for all five explicit LLM and three explicit VLM selector IDs below.
   It is useful coverage, but it is not the canonical Thor model pair. This is
   what `--require-all-selector-models-complete` means.

Qualification in one denominator cannot satisfy the other. The static
cross-verifier locks the Agent oracle/state, official-edge contract/artifact
lock, and official-edge readiness plan and rejects identity drift between them.

## Contract summary

| Role | Official default | Other explicit local selections | Officially verified local |
| --- | --- | --- | --- |
| Agent LLM | `nvidia/nvidia-nemotron-nano-9b-v2` | `nvidia/NVIDIA-Nemotron-Nano-9B-v2-FP8`, `nvidia/nemotron-3-nano`, `nvidia/llama-3.3-nemotron-super-49b-v1.5`, `openai/gpt-oss-20b` | Default only |
| Agent VLM | `nvidia/cosmos3-nano-reasoner` | `nvidia/cosmos-reason2-8b`, `Qwen/Qwen3-VL-8B-Instruct` | Default only |

The oracle separately records every named remote example. Remote provider
compatibility is open-ended, so those names are examples rather than an
allowlist. The exact Nemotron Omni checkpoint and its documented vLLM flags are
also locked.

Two local VLM references are intentionally unresolved:

- The tag's base `.env` lists `nvidia/cosmos-reason1-7b`, while the versioned
  3.2.1 VLM page omits it from the explicit supported-alternate list.
- The tag and docs explain `nvidia/cosmos3-super-reasoner` settings, while the
  explicit supported-alternate list omits the super ID.

The validator rejects any attempt to silently resolve those discrepancies.

## Files

- `official-vss-3.2.1.json`: immutable local copy of the exact model/settings
  contract, versioned NVIDIA URLs, and commit-pinned repository anchors.
- `thor-state.json`: read-only host observation, including exact artifacts,
  partial artifacts, non-official alternates, and explicit non-qualification.
- `thor-requirements.json`: exact two-denominator contract and source locks.
- `validate.py`: exact-value validator and optional Thor-completeness gate.
- `verify_thor_requirements.py`: offline cross-contract/coherence verifier.
- `tests/test_agent_models.py`: focused positive and mutation tests.
- `evidence/2026-07-31-static-agent-model-contract.md`: capture and test record.

## Validate

```bash
python3 deploy/docker/thor-local/agent-models/validate.py
python3 deploy/docker/thor-local/agent-models/verify_thor_requirements.py static
python3 -m unittest discover -s deploy/docker/thor-local/agent-models/tests -v
```

The first two commands succeed when the static contracts are honest. They print
separate blocker counts without claiming model readiness. To make missing
canonical Thor artifacts, backend image, and semantic runtime evidence fatal:

```bash
python3 deploy/docker/thor-local/agent-models/validate.py --require-thor-complete
```

To gate the distinct eight-selector compatibility matrix instead:

```bash
python3 deploy/docker/thor-local/agent-models/validate.py \
  --require-all-selector-models-complete
```

Both gates are expected to exit `2` today. The canonical gate has five explicit
blockers: incomplete official-edge artifact lock, two absent exact artifact
trees, absent exact Edge vLLM backend image, and absent source-locked identity
plus semantic runtime receipt. The all-selector gate retains 24 blockers (eight
models times artifact/backend/runtime). A green static validator is not a model
download, a running service, or runtime qualification.

Future `staged-and-locked` rows must reference repository-local, SHA-256-bound
JSON locks whose `lock_type` is `exact-agent-model-artifact` or
`exact-agent-model-backend`. Artifact locks require an immutable source
revision, a safe/sorted exact file manifest, per-file size and SHA-256, an
aggregate tree digest, and byte verification against the declared local root.
Backend locks require a repo-digest image reference, exact image ID, exact
command and served-model environment, and an aggregate contract digest. Both
lock types are bound to the model ID and reviewed release/main commits and
require their named pass-only checks. Placeholder artifact repositories and
placeholder backend registries are rejected. Runtime evidence must bind both
lock paths and digests, the same commits, the current reviewed date, and a
separately reviewed, source-locked collector in addition to models-endpoint,
semantic-request, and Agent-workflow checks. The approved collector is
`qualification/official-edge-semantic-runtime-evidence-successor`; it is inert
by default, excludes Warehouse, and accepts only a digest-bound fresh readiness
prerequisite plus explicitly authorized numeric-loopback requests. A
hand-authored list of passing checks still fails closed. The canonical verifier
also pins `approved-runtime-receipt.json`; its current `none_approved` state
means even a schema-valid caller-supplied receipt cannot clear the gate. A
future reviewed receipt must be checked into the repository and explicitly
approved by path and SHA-256 in that authority before validation. Exactly one
state row is allowed per model, and the aggregate all-selector state can become
`qualified` only when all eight exact documented models qualify.

The remaining implementation gap is intentional and explicit: no approved live
semantic receipt has been captured. The official-edge readiness plan proves only
prelaunch identity/readiness and cannot be promoted as semantic evidence. Even
a valid semantic receipt removes only that one blocker; the exact artifact-tree
and backend-image gates remain independent.

## Authoritative sources

- [Configure the LLM (VSS 3.2.1)](https://docs.nvidia.com/vss/3.2.1/vss-agent/configure-llm.html)
- [Configure the VLM (VSS 3.2.1)](https://docs.nvidia.com/vss/3.2.1/vss-agent/configure-vlm.html)
- [VSS 3.2.1 release notes](https://docs.nvidia.com/vss/3.2.1/release-notes.html)
- [VSS 3.2.1 prerequisites](https://docs.nvidia.com/vss/3.2.1/prerequisites.html)
- [Pinned v3.2.1 base profile environment](https://github.com/NVIDIA-AI-Blueprints/video-search-and-summarization/blob/7640d917047cf7b0fd3085eefb8282754b56bc94/deploy/docker/developer-profiles/dev-profile-base/.env)
