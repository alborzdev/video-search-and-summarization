# Thor RT-VLM model matrix and Cosmos Reason2 lane

`model-matrix.json` is a fail-closed review of the model variants advertised by
the RT-VLM source at upstream revision
`7732edf8fb38ef896b20f2a0a6a701a4db10dc57`. It records missing exact
artifacts as unqualified, keeps the remote-compatible adapter separate from a
local checkpoint, and identifies Cosmos3 Super as a base-profile NIM route
whose exact artifact revision, size, and Thor recipe are not locally known.
The two Nemotron Omni identifiers are intentionally distinct.

Validate those source anchors without network access:

```bash
python3 deploy/docker/thor-local/rt-vlm/model_matrix.py \
  --matrix deploy/docker/thor-local/rt-vlm/model-matrix.json \
  --artifact-lock deploy/docker/thor-local/rt-vlm/artifacts.lock.json \
  --repo-root "$PWD" validate
```

`artifacts.lock.json` pins every file, resolved blob digest, SafeTensors
header, tensor membership, architecture, and immutable Hugging Face revision
for the already-present official Cosmos Reason2 8B and 2B snapshots. The 8B
upstream index contains a literal `metadata.total_size=0`; the lock preserves
that exact value but marks it non-authoritative. Full file hashes, parsed
SafeTensors headers, all 750 tensor mappings, and four-shard membership remain
mandatory. The 2B snapshot is content-locked for reference but is not in the
reviewed advertised table.

The optional 8B BF16 lane mounts the Hugging Face repository root read-only so
its canonical snapshot links continue to resolve without copying model bytes.
Only vLLM cache and initialization locks are writable, in an ephemeral tmpfs.
The tmpfs is intentionally executable because vLLM may execute compiled cache
objects; it is still `nosuid,nodev` and is not part of artifact verification.
The source patch implementing that separation is mounted read-only over both
RT-VLM Python source locations in the staged ARM64 image.

```bash
export THOR_LOCAL_CR2_REPOSITORY_ROOT=/home/nvidia/.cache/huggingface/hub/models--nvidia--Cosmos-Reason2-8B
bash deploy/docker/thor-local/rt-vlm/thor-cr2-bf16.sh audit
bash deploy/docker/thor-local/rt-vlm/thor-cr2-bf16.sh launch-command
```

Both commands are read-only. `launch-command` prints `--no-build --pull never`
Compose syntax and does not run it. The lane is mutually exclusive with the
default Qwen VLM and enforces the documented fixed 20% unified-memory reserve:
`utilization <= MemAvailable/MemTotal - 0.20`. Passing static audit or prior
standalone benchmarks does not qualify current VSS inference, API behavior, or
co-residency on Thor.
