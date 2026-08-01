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

## Staging metadata boundaries

`staging-plan.json` records reviewed remote metadata separately from local
evidence:

- the public Hugging Face API reported immutable Nemotron revision
  `3fe6dab75665a93884214ad4b1b95cf02717d081`, 22 files, and 5,284,569,483
  total bytes;
- the exact public GHCR arm64 manifest has 103 compressed layers totalling
  14,586,393,839 bytes plus a 73,549-byte config;
- Cosmos3 metadata remains unknown because the available NGC CLI probe was not
  authorized by a valid API key.

These values estimate transfer payload only. They are not local artifact
proof, not installed/unpacked disk requirements, and cannot populate the
official artifact lock. Because the Cosmos3 byte size and the vLLM unpacked
size remain unknown, disk capacity stays unverified even when current free
space exceeds the known 19,871,036,871-byte partial payload.

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
