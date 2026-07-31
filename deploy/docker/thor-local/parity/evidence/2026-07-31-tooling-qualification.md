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

Five focused Thor regression tests now cover:

- HDF5 wrapper invocation from an unrelated working directory;
- HDF5 conversion control flow, concurrency helpers, dtypes, and compression;
- multi-frame velocity math and invalid step rejection;
- canonical `_World_Cameras_Camera*` plus legacy `Camera*` depth discovery; and
- canonical plus legacy video discovery and B-frame checks.

Result: `5 passed in 0.18s`. Shell syntax and all 16 SDG Python sources also
passed parsing checks. Additional tiny synthetic fixtures exercised NPY-to-PNG,
RGB-to-MP4, ffprobe B-frame validation, calibration helpers, and sanity-check
failure detection.

The SDG family remains partial: the checked-in requirements target Python 3.10,
and this Thor does not yet cache the complete pinned h5py/USD environment for
offline native HDF5/ground-truth conversion. Isaac Sim semantic-label helpers
also require their intended Isaac Sim runtime.
