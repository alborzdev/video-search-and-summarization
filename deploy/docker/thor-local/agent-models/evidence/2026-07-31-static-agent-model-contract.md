# Static VSS 3.2.1 Agent model contract — 2026-07-31

## Scope

This evidence covers only the declarative Agent LLM/VLM inventory under
`deploy/docker/thor-local/agent-models`. No download, network model call, image
pull, or container lifecycle operation was performed.

## Upstream anchors

- NVIDIA VSS release: `3.2.1`
- Peeled upstream tag commit:
  `7640d917047cf7b0fd3085eefb8282754b56bc94`
- Versioned official pages:
  - `https://docs.nvidia.com/vss/3.2.1/vss-agent/configure-llm.html`
  - `https://docs.nvidia.com/vss/3.2.1/vss-agent/configure-vlm.html`
  - `https://docs.nvidia.com/vss/3.2.1/release-notes.html`
  - `https://docs.nvidia.com/vss/3.2.1/prerequisites.html`
- Tag file hashes captured with `git show v3.2.1:<path> | sha256sum`:
  - base `.env`: `508e04f8d35afd6deefe2fa8c1c37e0ba5b408168b8d81763eb630d3b47f2b6b`
  - base Agent `config.yml`: `e89664e421bac7b8869b9dfa1e4149930e11b935bf6dc01351392a6557bb4c79`
- Content-locked declarative oracle SHA-256:
  `d6d44086a1a5a26fe0c02f8a6623e48282c66d50019c7ab8aa31c97d44c8ed71`

## Fail-closed findings

- Exact Agent LLM inventory: five local selector IDs; only the Nemotron Nano
  9B v2 default is documented as verified for local deployment.
- Exact explicit Agent VLM inventory: Cosmos 3 Nano default plus Cosmos Reason2
  8B and Qwen3-VL 8B; only the Cosmos 3 Nano default is documented as verified
  for local deployment.
- VSS 3.2.1 changed the Agent workflow default VLM to Cosmos Reason 3 Nano.
- AGX/IGX Thor is officially listed with remote-LLM configurations. NVIDIA says
  fully local deployment for every Agent workflow is future work.
- The Cosmos 3 Super and Cosmos Reason1 7B tag/docs discrepancies remain
  unresolved, and the validator rejects an unreviewed promotion.
- All exact advertised remote examples are separately inventoried from the
  open-ended adapter contracts.
- No exact official Agent pair is staged and runtime-qualified on this Thor.
  The Qwen artifacts are non-official alternates; the staged Cosmos Reason2 8B
  Hugging Face snapshot is only a partial RT-VLM artifact, not an Agent backend.

## Commands and results

```text
$ python3 deploy/docker/thor-local/agent-models/validate.py
[OK] Exact NVIDIA VSS 3.2.1 Agent model contract is internally consistent.
[OK] Thor state covers every exact model and makes no runtime qualification claim.
[INFO] All-advertised-selector completeness blockers: 24

$ python3 deploy/docker/thor-local/agent-models/validate.py \
    --require-all-selector-models-complete
exit 2 (expected; selector artifacts, Agent backends, and runtime evidence are absent)

$ python3 deploy/docker/thor-local/agent-models/verify_thor_requirements.py static
PASS Thor model denominator static coherence
INFO canonical official-edge blockers: 5
INFO all-advertised-selector blockers: 24

$ python3 deploy/docker/thor-local/agent-models/validate.py --require-thor-complete
exit 2 (expected; the canonical official-edge pair remains incomplete)

$ python3 -m unittest discover -s deploy/docker/thor-local/agent-models/tests -v
30 tests, OK
```

This is static evidence only. It must not be cited as proof that any model can
serve requests on Thor.

The two-denominator contract and cross-verifier were added after this original
2026-07-31 capture. They preserve its byte-locked Agent inventory while making
clear that the 24-selector gate and canonical Thor official-edge pair are not
interchangeable.
