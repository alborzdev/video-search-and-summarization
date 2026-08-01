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
on 2026-07-31 to manifest digest `sha256:b587dd56b4cb076209ad5156a626ac75f5a976d0e8e7d1e6a9fccd56d1bd65e8`,
but that exact image is not present locally and therefore has no trusted local
image ID. RT-VLM is the only locally locked runtime image in this lane.

## Current intentional blocker

The exact Nemotron 3 Nano 4B snapshot and Cosmos3 NGC cache were absent during
this milestone, as was the exact vLLM image described above.
Consequently, `artifacts.lock.json` is intentionally marked
`incomplete_fail_closed`. The public immutable Nemotron revision is pinned, but
the lock contains no invented local content hashes.
The launcher will not print a command, much less execute one, until a later
connected staging step:

1. obtains the exact licensed/gated artifacts;
2. confirms the staged snapshot matches the already reviewed immutable Edge 4B revision;
3. records every snapshot/cache directory, file, symlink target, size and
   SHA-256 in the two exact tree locks;
4. changes both entries to `locked_exact` and the top-level state to
   `complete_exact`.

There is deliberately no "capture and trust" command here. Creating an exact
lock is a review operation, not a way to bless whatever happens to be in a
cache.

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

The complete audit is also read-only and currently fails with explicit artifact,
vLLM image, and memory blockers:

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
