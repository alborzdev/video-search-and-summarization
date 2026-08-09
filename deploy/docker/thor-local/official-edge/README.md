# NVIDIA official Thor edge model lane

This directory defines an opt-in, fail-closed model lane for the exact AGX/IGX
Thor path documented by NVIDIA VSS 3.2.1. It does not replace or modify the
existing local Qwen `datasheet-chat` / `datasheet-vision` lane.

The exact contract is:

| Role | Runtime contract |
|---|---|
| LLM | Local standalone `nvidia/NVIDIA-Nemotron-3-Nano-4B-FP8` on `127.0.0.1:30081`; VSS calls it through `LLM_MODE=remote` because the service is outside NVIDIA's released Compose graph. |
| VLM | RT-VLM 3.2.1 loads `ngc:nim/nvidia/cosmos3-nano-reasoner:bf16-final` in-process with selector `cosmos-reason3` and advertises `nim_nvidia_cosmos3-nano-reasoner_bf16-final` on port `8018`. |
| Agent | The complete Thor-full feature graph remains the base config. Only the two Edge 4B planning/response prompt fields are inherited exactly from NVIDIA's `dev-profile-base/.../config_edge.yml`. |
| Memory | Edge 4B `0.25` + Cosmos3 `0.35` + required UMA reserve `0.20`; launch admission therefore requires `MemAvailable / MemTotal >= 0.80`. |

The authoritative model identity comes from NVIDIA's versioned
[VSS 3.2.1 Edge Deployment documentation](https://docs.nvidia.com/vss/3.2.1/edge-deployment.html),
last updated 2026-07-16. That page supersedes the older checked-in Edge skill,
which names `nvidia/NVIDIA-Nemotron-Edge-4B-v2.1-EA-020126_FP8`; the contract
records that older identity only as `older_fallback_unqualified` and never treats
the two repositories as equivalent.

`contract.json` also anchors checkout-derived fields to upstream main
`7732edf8fb38ef896b20f2a0a6a701a4db10dc57` and the dereferenced `v3.2.1`
tag `7640d917047cf7b0fd3085eefb8282754b56bc94`. Source blobs and SHA-256 values
are rechecked without network access. The mutable documented vLLM tag resolved
on 2026-07-31 to manifest digest `sha256:b587dd56b4cb076209ad5156a626ac75f5a976d0e8e7d1e6a9fccd56d1bd65e8`.
That exact arm64 image and the pinned RT-VLM image are both locally locked.

## Current artifact state

`artifacts.lock.json` is `complete_exact`. The exact Nemotron 3 Nano 4B
snapshot, its Hugging Face blob tree, the Cosmos3 NGC cache, and both model
runtime images are locked to their local bytes and independently reviewed
upstream provenance. The two evidence documents under `provenance/` bind the
promoted trees to the immutable Hugging Face revision and NVIDIA's signed NGC
payload. No model or image pull is required for a pull-free launch.

The remaining admission check is dynamic: the launcher requires at least 80%
of Thor's unified memory to be available before starting the official lane.
Pause other GPU or memory-heavy workloads first and restore them after VSS
qualification. The launcher remains fail-closed when that condition is not
met.

There is deliberately no "capture and trust" command here. Creating an exact
lock is a review operation, not a way to bless whatever happens to be in a
cache.

## Connected staging planner

`stage_artifacts.py` is the fail-closed connected staging boundary for the
three missing exact inputs. With no arguments (or with `plan`) it renders a
constant plan and performs no filesystem/environment reads, network access,
writes, subprocesses, credential access, or Docker operations:

```bash
python3 deploy/docker/thor-local/official-edge/stage_artifacts.py
```

The separately acknowledged `execute` mode requires all of the following as
literal inputs before it performs any host inspection:

- the exact Nemotron repository and immutable 40-hex revision;
- the exact Cosmos3 Nano BF16 NGC artifact;
- the digest-bound vLLM image (the documented mutable tag is rejected);
- an explicit absolute staging root and explicit absolute paths for `hf`,
  `ngc`, and `docker`;
- symbolic credential sources (`env:HF_TOKEN` and either
  `env:NGC_CLI_API_KEY` or `env:NGC_API_KEY`), whose values are passed only in
  child environments and are never placed in commands, receipts, or output;
- the reviewed 49,871,036,871-byte known planning floor, an operator-selected
  positive allowance for the still-unknown unpacked vLLM size, and a positive
  free-space reserve that must remain after staging.

An existing staging root is admitted only when it is a real directory owned by
the effective user with exact mode `0700`. Existing cache-directory components
must also be real directories: directory symlinks are rejected so a cache
cannot redirect writes outside the reviewed root. This does not prohibit the
standard Hugging Face snapshot's internal file symlinks; the candidate verifier
checks those separately and permits only canonical targets in the sibling blob
store.

An execution is shaped as follows. The two byte values are intentionally not
defaulted: the operator must select them after reviewing current capacity.

```bash
python3 deploy/docker/thor-local/official-edge/stage_artifacts.py execute \
  --acknowledgement I_ACCEPT_CONNECTED_STAGING_EXACT_THOR_OFFICIAL_EDGE_ARTIFACTS_ONLY \
  --staging-root /absolute/operator/reviewed/vss-official-edge \
  --hf-executable /absolute/path/to/hf \
  --ngc-executable /absolute/path/to/ngc \
  --docker-executable /absolute/path/to/docker \
  --hf-credential-source env:HF_TOKEN \
  --ngc-credential-source env:NGC_CLI_API_KEY \
  --edge-repository nvidia/NVIDIA-Nemotron-3-Nano-4B-FP8 \
  --edge-revision 3fe6dab75665a93884214ad4b1b95cf02717d081 \
  --cosmos-artifact ngc:nim/nvidia/cosmos3-nano-reasoner:bf16-final \
  --vllm-image ghcr.io/nvidia-ai-iot/vllm@sha256:b587dd56b4cb076209ad5156a626ac75f5a976d0e8e7d1e6a9fccd56d1bd65e8 \
  --additional-headroom-bytes <operator-reviewed-positive-bytes> \
  --minimum-free-after-bytes <operator-required-positive-reserve-bytes>
```

Resume behavior is deliberately artifact-specific. Docker layers can resume,
but the image is skipped only after its exact repository digest, config digest,
and platform pass inspection. An NGC partial directory is retained for the
exact `download-version` command to retry; it is never mistaken for success,
and that command must return successfully before the result is atomically
admitted to the canonical cache path.

Hugging Face completion does **not** generically provider-resume from an
exact-named snapshot. Such a snapshot can be skipped only when a prior review
candidate's complete snapshot and blob trees still match its current bytes. An
interrupted or otherwise unreviewed pre-existing snapshot fails closed and
requires explicit operator recovery or a new staging root. Artifact names,
non-empty state, and the staging journal are never identity evidence. The tool
retains partial bytes and never deletes caches or images.

Successful staging writes
`official-edge-review-candidate-v1.json` below the explicit staging root. The
candidate contains artifact trees from `lock_candidate.py`, the exact local
image/config identity, selected tool hashes and versions, redacted command
receipts, and symbolic credential-source names. It remains
`review_candidate_only_not_promoted`: neither the stager nor the candidate
generator can edit `artifacts.lock.json` or create reviewed provenance below
this source directory. Independent source/hash review and explicit lock
promotion remain separate operator actions.

An inert-by-default helper can prepare a review candidate without changing the
checked-in lock, the artifacts, Docker, credentials, or the network:

```bash
python3 deploy/docker/thor-local/official-edge/lock_candidate.py plan

python3 deploy/docker/thor-local/official-edge/lock_candidate.py generate \
  --acknowledgement I_ACCEPT_READ_ONLY_OFFICIAL_EDGE_ARTIFACT_HASHING \
  --edge4b-snapshot /exact/hf/repository/snapshots/3fe6dab75665a93884214ad4b1b95cf02717d081 \
  --cosmos3-cache /exact/ngc/model/cache
```

`generate` hashes the snapshot, the entire sibling blob store that Compose will
mount, and the Cosmos cache. It prints a `candidate_only_not_promoted` JSON
document whose proposed lock is deliberately `candidate_only_unqualified`.
It never writes `artifacts.lock.json`, and the verifier will not accept its
local-byte provenance as an independent upstream provenance review. Promotion
requires a separate review of upstream identity/hash evidence and every emitted
tree entry. A promoted entry must bind a regular, non-symlinked evidence JSON
file below `deploy/docker/thor-local/official-edge/provenance/` by its exact
SHA-256; the verifier also checks that document's identity, reviewer, HTTPS
sources, and non-empty upstream SHA-256 list. No such evidence is fabricated by
the candidate generator.

## Static verification

This is read-only and succeeds now:

```bash
python3 deploy/docker/thor-local/official-edge/official_edge.py static
```

The complete audit is also read-only. With the promoted artifact paths
supplied, it passes the source, prompt, Compose, exact-tree, provenance, and image
identity gates; it will fail only while the host does not satisfy the dynamic
80% unified-memory admission rule:

```bash
python3 deploy/docker/thor-local/official-edge/official_edge.py \
  --edge4b-snapshot /exact/hf/repository/snapshots/<revision> \
  --cosmos3-cache /exact/ngc/model/cache \
  audit
```

It checks source anchors, the Edge prompt overlay, the inert Compose contract,
exact artifact trees, both required image identities, and the combined UMA
admission rule. NGC/HF credentials are not accepted by this offline lane and
both are blank in the long-running model services.

## Pull-free command rendering

After reviewed locks exist and all gates pass, the following prints one command
and does not execute it:

```bash
python3 deploy/docker/thor-local/official-edge/official_edge.py \
  --edge4b-snapshot /exact/hf/repository/snapshots/<revision> \
  --cosmos3-cache /exact/ngc/model/cache \
  render-command
```

The command loads `official-edge.env` after the protected Thor runtime env and
adds `compose.yml` as the final override. It always contains `--no-build --pull
never`. Before printing, the tool resolves the combined Compose graph and
rejects a wrong model ID, selector, endpoint, prompt path, image, or accidental
Qwen service selection.

The overlay uses host-private endpoints. Edge 4B binds only to loopback. A
standard Hugging Face cache snapshot is a symlink forest, so the snapshot and
its sibling `blobs` directory are verified and mounted separately read-only;
mounting the snapshot alone would leave its model files broken. The
Cosmos3 NGC cache is a separate, read-only operator-provided bind path so it is not
silently conflated with the existing exact Cosmos Embed volume lock.

The inherited planning prompt mentions a warehouse only as an example query.
No warehouse video or large warehouse sample bundle is required by this lane.

## Runtime readiness

Once an operator explicitly runs the rendered command, verify identity and
readiness without mutating VSS state:

```bash
python3 deploy/docker/thor-local/official-edge/official_edge.py \
  --edge4b-snapshot /exact/hf/repository/snapshots/<revision> \
  --cosmos3-cache /exact/ngc/model/cache \
  readiness
```

This checks the exact running model-serving image, command, and environment
contracts, plus the consumer services' command and environment wiring. Consumer
application image identity remains governed by the Thor-wide image lock rather
than this lane. Each `/v1/models` endpoint must advertise only its exact model
ID. This is not a substitute for later semantic acceptance of Edge 4B tool calls
or Cosmos3 file, RTSP, dense-caption, alert, LVS and Agent workflows.

## Tests

```bash
python3 -m unittest discover \
  -s deploy/docker/thor-local/official-edge/tests -v
```

The focused suite includes source drift, exact tree mutation/extra-file,
symlink escape, model-ID alias, image identity, Compose resolution, inert
renderer and the exact `0.25 + 0.35 + 0.20` memory boundary. The repository-
reproducible full-Compose resolution test uses the tracked Thor-full environment
with sanitized `VSS_APPS_DIR`/`VSS_DATA_DIR` substitutions; it does not require
the gitignored protected `generated.env`.
