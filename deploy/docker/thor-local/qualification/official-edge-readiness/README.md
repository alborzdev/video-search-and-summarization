# Official-edge readiness inventory

This package turns the current NVIDIA VSS 3.2.1 Thor official-edge staging
gates into a deterministic, read-only report. It imports no credentials, uses
no network, and cannot start, stop, pull, build, or remove anything. The only
Docker operations admitted by code are exact local `image inspect`, `container
inspect`, and `volume inspect` calls against the local Unix socket.

The identities are fixed to:

- LLM: `nvidia/NVIDIA-Nemotron-3-Nano-4B-FP8`
- VLM artifact: `ngc:nim/nvidia/cosmos3-nano-reasoner:bf16-final`
- VLM served ID: `nim_nvidia_cosmos3-nano-reasoner_bf16-final`
- VLM selector: `cosmos-reason3`

The old Nemotron Edge 4B repository and the local Qwen lane are explicit
forbidden substitutions. They remain useful alternate/provenance lanes, but
they cannot satisfy this official contract.

## Inert plan

This performs no host or Docker inspection:

```bash
python3 deploy/docker/thor-local/qualification/official-edge-readiness/readiness.py plan
```

## Read-only host inspection

```bash
python3 deploy/docker/thor-local/qualification/official-edge-readiness/readiness.py \
  inspect --acknowledgement I_ACCEPT_READ_ONLY_HOST_INSPECTION
```

If an operator has already identified an exact Cosmos3 cache candidate, pass
it explicitly with `--cosmos3-cache /absolute/path`. Merely finding the
existing `mdx_rtvi-ngc-model-cache` volume never proves its contents or model
identity. An explicit path is still only a candidate until the reviewed
`official-edge/artifacts.lock.json` has a complete, exact tree and the existing
official verifier accepts it. The read-only inspector delegates this final gate
to that source-locked verifier, which compares every directory, file size,
SHA-256, and permitted Hugging Face symlink target. A matching snapshot revision
name without an exact tree match remains blocked.

The report is intentionally not runtime evidence. It always emits
`runtime_qualification_performed: false`; even a fully staged report can claim
only `prelaunch_ready_not_runtime_qualified`.

Every plan and host result generates its own microsecond UTC
`captured_at_utc`. The field is inside the schema-validated result and therefore
inside any downstream receipt digest. Callers cannot supply or replace it, and
filesystem modification time is not readiness freshness evidence.

Image readiness requires all three identities to agree: the immutable
repository digest, Docker's exact image/config ID, and a `locked_exact`
graduation in the source-locked official contract. A caller-supplied plan cannot
replace either image identity or lower the 0.80 unified-memory admission gate.
The plan must be byte-semantically identical to the checked-in plan, and host
readiness accepts only canonical `/proc/meminfo`; alternate files cannot produce
a prelaunch-ready host claim.

## Staging metadata boundaries

`staging-plan.json` records reviewed remote metadata separately from local
evidence:

- the public Hugging Face API reported immutable Nemotron revision
  `3fe6dab75665a93884214ad4b1b95cf02717d081`, 22 files, and 5,284,569,483
  total bytes;
- the exact public GHCR arm64 manifest has 103 compressed layers totalling
  14,586,393,839 bytes plus a 73,549-byte config;
- NVIDIA's Cosmos3 Nano BF16 support matrix documents 30 GB of disk space,
  which is recorded as a planning floor rather than exact NGC cache bytes;
- Cosmos3 metadata remains unknown because the available NGC CLI probe was not
  authorized by a valid API key.

These values estimate transfer payload or documented installed-model space only. They are not local artifact
proof, not installed/unpacked disk requirements, and cannot populate the
official artifact lock. Because the Cosmos3 byte size and the vLLM unpacked
size remain unknown, disk capacity stays unverified while anything is missing,
even when current free space exceeds the 49,871,036,871-byte planning floor.
Once both exact artifact trees and both exact images are already local, the
staging-capacity gate records that zero additional staging bytes are required.

## Tests

```bash
python3 -m unittest discover \
  -s deploy/docker/thor-local/qualification/official-edge-readiness/tests -v
```

The tests cover source locks, inert default behavior, acknowledgement gating,
forbidden Docker operations, immutable-cache discovery, exact image digest and
architecture checks, remote/local evidence separation, and the prohibition on
runtime qualification claims. Adversarial coverage includes a source-lock
symlink escape and a same-revision snapshot whose bytes were modified after its
lock was created; neither can pass.
