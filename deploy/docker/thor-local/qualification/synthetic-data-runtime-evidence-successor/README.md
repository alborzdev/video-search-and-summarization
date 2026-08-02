# Thor synthetic-data runtime evidence successor

This package is the runtime producer for the four canonical
`synthetic-data-tools` capabilities. It uses only tiny data generated inside an
executor-owned temporary directory and the existing checksum-locked ARM64
environment under `tools/sdg-postprocessing/thor/.thor-env`. It does not use
Docker, services, models, credentials, external network access, downloads, or
the NVIDIA Warehouse sample.

The default command is inert:

```bash
python3 deploy/docker/thor-local/qualification/synthetic-data-runtime-evidence-successor/executor.py
```

A development smoke run may use the current planning-only oracle rows. Its
receipt is deliberately non-promoting:

```bash
python3 deploy/docker/thor-local/qualification/synthetic-data-runtime-evidence-successor/executor.py \
  --execute \
  --allow-dirty-development \
  --acknowledge I_ACKNOWLEDGE_OFFLINE_SDG_RUNTIME_EVIDENCE \
  --output /tmp/synthetic-data-development-receipt.json
```

## Promotable two-commit sequence

The checked Metadata-500 rows are planning-only lineage and cannot authorize a
promotion receipt. First commit this producer and a reviewed oracle successor
whose four rows have all of the following exact fields:

- `execution_bounds.executor` and every collector equal this `executor.py`;
- `cleanup.executor` and every postcondition collector equal this executor;
- `fixture.materialization.generator` equals this executor;
- `fixture.materialization.path` is a non-empty executor fixture URI;
- `fixture.materialization.sha256` equals the capability's digest in
  `contract.json`;
- `acceptance_readiness.classification` is `executor_ready`; and
- `acceptance_readiness.blockers` is empty.

Then, from a fully clean checkout, produce the receipt outside the repository:

```bash
python3 deploy/docker/thor-local/qualification/synthetic-data-runtime-evidence-successor/executor.py \
  --execute \
  --oracle-document deploy/docker/thor-local/qualification/EXACT-SUCCESSOR/oracles.json \
  --acknowledge I_ACKNOWLEDGE_OFFLINE_SDG_RUNTIME_EVIDENCE \
  --output /tmp/synthetic-data-runtime-receipt.json
```

Review and add that receipt in a second commit. The producer rejects dirty
promotable runs, pre-existing output paths, repository output paths, and the
current planning-only rows.

## Coverage

Each capability is executed twice on independently generated fixtures. The
receipt compares canonical observations and every declared output byte:

- OpenUSD label add/export/remove plus missing-stage rejection;
- all ten dataset checkers, with a checker-specific adjacent negative;
- depth PNG, gzip HDF5, H.264/zero-B-frame conversion, plus malformed-input
  cases; and
- ground-truth conversion with absent and non-null Xform metadata, exact four
  JSON outputs, input immutability, and missing-calibration rejection.

The producer verifies all source hashes, selected Metadata-500 lineage hashes,
the future execution-oracle row hashes, all 21 Python pins, OpenUSD 26.05, and
the complete 178-conda/21-wheel offline cache before executing tools.
