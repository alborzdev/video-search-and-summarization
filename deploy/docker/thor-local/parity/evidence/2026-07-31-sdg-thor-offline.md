# Thor synthetic-data environment qualification — 2026-07-31

This qualification closed the ARM64 Python/OpenUSD gap for
`tools/sdg-postprocessing`. No NVIDIA warehouse sample, synthetic dataset, VSS
image, stream, or deployment resource was downloaded or changed.

## Reproducible environment

The upstream file pins Python 3.10-era packages and `usd-core==26.5`. PyPI has
no Linux ARM64 wheel for that USD distribution. Conda-forge provides the
equivalent OpenUSD 26.05 build for Python 3.10 on Linux aarch64, including the
current `UsdSemantics.LabelsAPI` schema.

The Thor lane now contains:

- a 178-entry explicit conda lock whose every URL has a SHA-256 fragment;
- 21 exact pip requirements, identical to upstream except for `usd-core`, plus
  a committed exact-filename/SHA-256 wheel lock;
- a SHA-locked Miniforge 25.3.1-0 Linux aarch64 bootstrap;
- connected staging with per-artifact verification;
- an offline create path using only local `file://` conda URLs, conda
  `--offline`, and pip `--no-index`; and
- a native fixture qualifier.

Current lock digests:

- `conda-linux-aarch64.lock`:
  `9905f3f0f1ac6b82d8920429a2a6f7101d51a9df0e54dba8671d44f9f8158b6f`
- `requirements-pip.txt`:
  `95cdadc9544667440effbe18c2b4b612ec367c6f249a5d348488b00e4a27520e`
- `wheels-linux-aarch64.sha256`:
  `7a6140f5c16e7c75a09677e0c7d16be212c0ad0c707163f1e20a1f29e78532fa`
- generated cache `SHA256SUMS`:
  `cf9e31569d9acd3de5a0caaae4f8720768a4ea518c4b34eb81b59f94f81aa476`

The ignored reproducible cache is 524 MiB. The created environment reports
Python 3.10.20 and OpenUSD `(0, 26, 5)` on `aarch64`.

## Portable semantic helpers

The three semantic helpers no longer require an implicit Isaac Sim global:

- box categorization can inspect a `--stage` file and optionally author current
  `LabelsAPI` labels;
- Xform export accepts a file-backed stage and recognizes both current labels
  and the deprecated NVIDIA schema when available; and
- semantic removal accepts a file-backed stage and removes current and legacy
  label instances.

The no-`--stage` path remains available inside Isaac Sim. File-backed tests use
a temporary stage and never require a warehouse scene.

## Current results

Connected staging succeeded with 178 conda archives and 21 wheels. The current
ignored cache was reverified against both its complete generated inventory and
the committed 21-wheel lock. The same cache then created the complete
environment with network access disabled at the package-manager level. Native
qualification passed:

- exact Python package and OpenUSD imports;
- every SDG Python command's CLI import path;
- NumPy depth to 16-bit PNG conversion;
- native OpenCV/HDF5 conversion and archive inspection;
- RGB images to H.264 with zero B-frames plus ffprobe validation;
- headless OpenUSD box labeling with `UsdSemantics.LabelsAPI`;
- parent-Xform JSON export; and
- semantic label removal.

The focused regression suite reports `9 passed` in a disposable copy of the
pinned environment after adding test-only pytest; pytest is intentionally not
part of the 21-wheel runtime lock. Under the host Python that lacks OpenUSD the
same suite reports `9 passed, 1 skipped`. The three additional cases prove that
missing, substituted, and byte-tampered wheels fail the committed lock. The
pull-free native qualifier above does not depend on pytest and is the
reproducible runtime acceptance gate. This makes the alternate local SDG
tooling lane current-runtime qualified.
