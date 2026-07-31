# Thor tooling qualification — 2026-07-31

This evidence covers the two source-tooling families in the VSS 3.2.1 parity
ledger. No NVIDIA warehouse sample or other dataset was downloaded, and no VSS
container, stream, index, or deployment resource was changed.

## SpatialAI data utilities

The complete `libs/analytics/spatialai-data-utils/tests` suite ran on this
ARM64 Thor in a clean Python 3.12 virtual environment with every declared
`eval` and `viz` dependency, CPU PyTorch 2.13.0, and PyTorch3D built from the
repository-pinned commit `33824be`.

- PyTorch wheel: `torch-2.13.0+cpu-cp312-cp312-manylinux_2_28_aarch64`
- PyTorch3D wheel: `pytorch3d-0.7.9-cp312-cp312-linux_aarch64`
- Built wheel SHA-256: `237fa34c751f83e5d39fdb94b03978f25003a9c79e679fcf925269a86a998ad2`
- Result: `1902 passed in 39.98s`

`deploy/docker/thor-local/qualification/qualify-spatialai.sh` reproduces the
isolated connected qualification without downloading any dataset or touching
the VSS stack. It pins the exact Python tooling, CPU Torch wheel, and upstream
PyTorch3D commit used here. The package itself pins its remaining dependencies
in `release/pyproject.toml`.

## Synthetic-data post-processing tools

The final Thor source suite contains nine passing tests (one host-only case is
skipped in the isolated source run) covering:

- HDF5 wrapper invocation from an unrelated working directory;
- HDF5 conversion control flow, concurrency helpers, dtypes, and compression;
- multi-frame velocity math and invalid step rejection;
- canonical `_World_Cameras_Camera*` plus legacy `Camera*` depth discovery; and
- canonical plus legacy video discovery and B-frame checks.

The exact offline cache contains 178 locked Linux/AArch64 conda packages and 21
filename/hash-locked wheels. It created a Python 3.10.20/OpenUSD 26.05/ffmpeg
8.1.2 environment without network access. The native qualifier passed depth to
PNG, HDF5, RGB to zero-B-frame H.264, semantic add/export/remove, and OpenUSD
fixture gates. The authoritative final result and commands are recorded in
`2026-07-31-sdg-thor-offline.md`; the manifest therefore records this alternate
tooling family as `wired/passed_current`.
