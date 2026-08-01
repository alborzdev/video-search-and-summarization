# Offline MV3DT tool qualification

This package executes the two checked-in `mv3dt-config-utils` repository tools
against a tiny, code-authored two-camera calibration fixture:

- `tool.mv3dt.cam-info-generator`
- `tool.mv3dt.pub-sub-generator`

It is deliberately candidate-only. The deterministic result is now bound into
the two matching official capability oracles as a reviewed static subset, but
it cannot advance either full oracle, create runtime evidence, or prove the
Warehouse profile. The binding covers each tool's semantic and deterministic
output assertions plus contract fields 01-04; Warehouse planning-bookkeeping
assertions 05-08 remain explicitly uncovered. The official Warehouse sample
bundle is excluded. The accepted boundary remains the alternate local
custom-data lane, and these utilities are non-Compose `repository-tooling`
rather than a `warehouse-mv3dt` service.

The executor imports the source tools directly. It cannot invoke Docker or a
subprocess, open a network connection, download artifacts, access credentials,
load a model, or mutate a service. Its only writes are two isolated runs below a
fresh private temporary root. It removes the exact owned root, checks an
adjacent sentinel, and then removes the private parent.

Run the candidate observation and focused tests from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/offline-mv3dt-tools/executor.py

PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  deploy/docker/thor-local/qualification/offline-mv3dt-tools/tests
```

`contract.json` locks the advertised entries, generator sources, dependency
declaration, fixture, execution inputs, and expected output-tree hashes. The
checked `execution-receipt.json` is the schema-validated result of the current
two-run Thor observation and is raw-SHA-bound by the live oracle compiler. The
compiler rehashes every contract source lock and derives its selected results
from this receipt rather than from schema constants.

The observed local distributions are `numpy 2.5.1`, `opencv-python 4.11.0.86`,
`PyYAML 6.0.3`, and `tqdm 4.68.4`; the imported `cv2` module reports `4.13.0`.
They do **not** match the reviewed declarations (`numpy 2.2.6`,
`opencv-python ~=4.12.0`, `PyYAML 6.0.2`, and `tqdm 4.67.1`). They are
non-normative evidence about this candidate run, not proof of the declared
dependency environment.
