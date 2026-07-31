# Thor offline SDG environment

The upstream synthetic-data post-processing requirements pin Python 3.10 and
`usd-core==26.5`, but PyPI does not publish that USD wheel for Linux ARM64.
Thor uses the equivalent conda-forge OpenUSD 26.05 ARM64 build and keeps every
other Python dependency at the exact upstream version.

Stage the cache once while connected:

```bash
tools/sdg-postprocessing/thor/stage-offline-cache.sh
```

That downloads only dependency artifacts: the SHA-locked Miniforge installer,
178 SHA-locked conda packages, and 21 exact ARM64 Python wheels. The committed
`wheels-linux-aarch64.sha256` file pins both the exact wheel filenames and their
bytes; the generated cache sidecar cannot authorize a substituted wheel. The
stager rejects missing, extra, renamed, or modified wheels before accepting the
cache. It downloads no warehouse or synthetic dataset. The generated
`offline-cache/` is ignored by Git because it is a large reproducible artifact
set.

Create and qualify the environment with networking unavailable:

```bash
tools/sdg-postprocessing/thor/create-offline-env.sh
```

The create path verifies every cached byte, materializes only local `file://`
conda URLs, invokes conda with `--offline`, and invokes pip with `--no-index`.
The qualifier exercises native depth-to-PNG, HDF5, RGB-to-H.264, B-frame
validation, OpenUSD semantic labels, Xform export, and semantic-label removal.

Override locations without editing source:

```bash
SDG_OFFLINE_CACHE=/data/vss-sdg-cache \
SDG_ENV_DIR=/data/vss-sdg-env \
  tools/sdg-postprocessing/thor/create-offline-env.sh
```

The semantic helpers now accept `--stage` for headless Thor use while retaining
their no-`--stage` Isaac Sim Script Editor mode. They author the current
`UsdSemantics.LabelsAPI` schema; the removal and export helpers also recognize
the deprecated NVIDIA `SemanticsAPI` when that schema is available in Isaac
Sim.
