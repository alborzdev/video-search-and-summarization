# Thor-local model artifact lock

`artifacts.lock.json` is the reviewed, fail-closed identity for every large
inference artifact used by the default Thor profile. Runtime commands read this
file; they never create, refresh, or relax it.

| Artifact | Upstream identity | Exact locked tree |
| --- | --- | --- |
| `qwen_llm` | `Qwen/Qwen3.6-35B-A3B-FP8` at `95a723d08a9490559dae23d0cff1d9466213d989` | 52 snapshot links, 37,492,937,842 resolved bytes |
| `qwen_vlm` | `Qwen/Qwen3-VL-8B-Instruct-FP8` at `9cdc6310a8cb770ce18efaf4e9935334512aee45` | 11 snapshot links, 10,605,560,594 resolved bytes |
| `cosmos_embed_model` | `nvidia/Cosmos-Embed1-448p-anomaly-detection` at `3b1455ed97c7b1d5419c0c3129b7199ca4cd9382` | 76 files, 3 directories, 4,793,036,482 bytes |
| `cosmos_embed_triton` | TensorRT FP16 repository derived from that Cosmos revision for NVIDIA Thor | 10 files, 4 directories, 9,661,728,403 bytes |

The lock records every relative name, node type, byte count, mode, SHA-256,
source/revision, service-image contract, container path, architecture, and
target hardware. For Hugging Face snapshots it additionally records the exact
visible symlink target and resolved blob identity. The verifier rejects an
extra or missing member, path traversal, an absolute or escaping link, a
non-regular node, duplicate archive member, changed mode, truncation, content
substitution, or provenance mismatch.

Hashes are necessary but not sufficient. `verify_artifacts.py` also validates:

- model architecture, model type, FP8 settings, embedding dimensions, and
  other role-specific `config.json` fields;
- duplicate-free JSON, exact index shape, tensor/shard counts, and exact
  agreement between every SafeTensors header and `weight_map`;
- SafeTensors bounds and non-overlapping data ranges, including agreement with
  Cosmos `metadata.total_size`;
- the revision in every Cosmos Hugging Face download metadata record;
- Triton model name, TensorRT platform, batch 8 default engine, NVIDIA Thor
  filename, input/output types and dimensions, and GPU instance contract; and
- the Triton repository's cross-artifact derivation from the locked Cosmos
  revision.

## Operator verification

The normal entry points perform the checks automatically:

```bash
deploy/docker/thor-local/provision-local-models.sh status
deploy/docker/scripts/thor-local.sh verify-offline
```

The first command hashes the two staged Hugging Face snapshot trees before it
accepts their stopped container contracts. The second asks Docker for the
exact Compose volume identities and streams each tree through a disposable,
network-isolated, read-only helper with volume copy-up disabled. This remains
valid after `compose down`, when no service container exists, and leaves no
helper behind.

The lock itself currently has SHA-256
`5b0030ba13fb1ccee5950e3c4b78d334d8dd0c30a2a45ce90e6166a57fe31d09`.
That digest is informational; the version-controlled lock and reviewer trust
boundary are authoritative.

## Updating the reviewed lock

Lock changes are maintainer operations, not deployment recovery steps. Confirm
the upstream repository and immutable revision, stage into a disposable cache,
inspect `config.json`, the SafeTensors index/headers, download metadata, Triton
configs, target, batch, and precision, then use the read-only `capture-hf` or
`capture-tar` command to produce a candidate tree. Put that tree into a copy of
the lock through a reviewed source patch and run the adversarial tests. Never
make `status`, `provision`, `up`, or `verify-offline` regenerate the accepted
identity from whatever happens to be staged.

The capture subcommands emit JSON to stdout and do not write the snapshots or
volumes. They deliberately validate SafeTensors structure while hashing. A
candidate lock does not qualify a new model: current API, quality, latency,
memory, and end-to-end VSS acceptance evidence is still required.
