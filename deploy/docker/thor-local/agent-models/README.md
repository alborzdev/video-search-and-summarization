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
- `validate.py`: exact-value validator and optional Thor-completeness gate.
- `tests/test_agent_models.py`: focused positive and mutation tests.
- `evidence/2026-07-31-static-agent-model-contract.md`: capture and test record.

## Validate

```bash
python3 deploy/docker/thor-local/agent-models/validate.py
python3 -m unittest discover -s deploy/docker/thor-local/agent-models/tests -v
```

The first command succeeds when the static contract is honest and complete. It
prints the number of remaining runtime blockers. To make missing artifacts,
backends, and runtime evidence fatal:

```bash
python3 deploy/docker/thor-local/agent-models/validate.py --require-thor-complete
```

That gate is expected to exit `2` today. A green static validator is not a model
download, a running service, or runtime qualification.

Future `staged-and-locked` rows must reference repository-local, SHA-256-bound
JSON locks whose `lock_type` is `exact-agent-model-artifact` or
`exact-agent-model-backend`. Artifact locks require an immutable source
revision, a safe/sorted exact file manifest, per-file size and SHA-256, an
aggregate tree digest, and byte verification against the declared local root.
Backend locks require a repo-digest image reference, exact image ID, exact
command and served-model environment, and an aggregate contract digest. Both
lock types are bound to the model ID and reviewed release/main commits and
require their named pass-only checks. Runtime evidence must bind both lock paths
and digests, the same commits, the current reviewed date, and the models-
endpoint, semantic-request, and Agent-workflow checks. Exactly one state row is
allowed per model, and the aggregate state can become `qualified` only when all
eight exact documented models qualify.

## Authoritative sources

- [Configure the LLM (VSS 3.2.1)](https://docs.nvidia.com/vss/3.2.1/vss-agent/configure-llm.html)
- [Configure the VLM (VSS 3.2.1)](https://docs.nvidia.com/vss/3.2.1/vss-agent/configure-vlm.html)
- [VSS 3.2.1 release notes](https://docs.nvidia.com/vss/3.2.1/release-notes.html)
- [VSS 3.2.1 prerequisites](https://docs.nvidia.com/vss/3.2.1/prerequisites.html)
- [Pinned v3.2.1 base profile environment](https://github.com/NVIDIA-AI-Blueprints/video-search-and-summarization/blob/7640d917047cf7b0fd3085eefb8282754b56bc94/deploy/docker/developer-profiles/dev-profile-base/.env)
