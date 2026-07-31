# Thor RT-VLM model matrix and Cosmos Reason2 lane

`model-matrix.json` is a fail-closed review of the 18 exact model paths in the
[official NVIDIA VSS 3.2.1 RT-VLM Supported Models table](https://docs.nvidia.com/vss/3.2.1/real-time-vlm.html#supported-models).
`official-vss-3.2.1-models.json` is the checked-in declarative oracle for that
table. Its SHA-256, authoritative URL, release, row order, exact model paths,
selectors, and documentation notes are enforced in `model_matrix.py`.

The checkout README at upstream revision
`7732edf8fb38ef896b20f2a0a6a701a4db10dc57` remains independently byte-locked.
It contains 11 entries and omits seven documented paths: Reason2 `hf-1208`,
Cosmos3 Nano FP8 and Diffuser, and all four Cosmos3 Super variants. The matrix
records this docs-versus-repository skew explicitly; it does not silently
discard the documentation superset. Every exact unstaged artifact remains
unqualified on Thor. The remote-compatible adapter and the generic base-profile
Cosmos3 Super NIM route remain separate, and the two Nemotron Omni identifiers
are intentionally distinct.

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
official 18-entry table. The local 8B Hugging Face revision is family coverage
only; no equivalence to any versioned NGC Reason2 entry is asserted.

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
