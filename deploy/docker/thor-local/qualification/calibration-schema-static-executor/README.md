# Calibration schema static executor

This package executes one isolated, non-advancing candidate for the canonical
planning requirement `calibration-schema-static`. That requirement is owned by
the exact `global_acceptance_vector` of the same name; it is not a synthetic or
ownerless row. The executor narrows its capability claim to the real official
capability `calibration.schema.vss-json` and its oracle
`oracle.calibration.schema.vss-json`.

The global vector names seven applicable ledger records. This executor
evaluates only the exact schema capability. Its machine contract explicitly
lists the other six as `not_evaluated_record_ids`; shared planning ownership is
not treated as evidence for AMC/VGGT, physical installation, alignment, or
known-limitation behavior.

It uses the checked-in provider-free backend to generate, solve, export, and
strictly read back four tiny operator-style projects:

- one `geo` project with an eight-point ROI and road link;
- one `cartesian` project;
- one `image` project; and
- one two-camera `mtmc` workflow that deliberately exports the legal
  `cartesian` calibration type. `mtmc` is a workflow identity, not a legal VSS
  `calibrationType`.

Every positive output is checked against the strict SpatialAI calibration
schema, its byte-identical Video Analytics API copy, the Behavior Analytics
calibration schema, and the strict road-network schema. These four repository
files represent three schema identities: strict calibration, behavior
calibration, and road network. The documented canonical schema digest
`0ad428...` remains a ledger contract digest; it is not falsely relabeled as a
raw file digest. Exact raw SHA-256 values for every checked-in schema are
preserved separately.

## Run

From the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/calibration-schema-static-executor/executor.py \
  --json

PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/calibration-schema-static-executor/tests
```

The executor performs two independent runs under one private temporary root,
creates exactly sixteen regular output files in total, checks byte-level
determinism, and verifies removal of the exact executor-owned root. Generated
inputs stay in memory. It rejects seven adjacent invalid cases covering the
eight-point floor, external-provider identity, path traversal, illegal MTMC
output identity, duplicate camera IDs, a missing required calibration field,
and an unknown road-network field.

## Boundary

This is deterministic static candidate evidence, not runtime evidence. It does
not run AutoMagicCalib or VGGT, validate physical camera installation, operate
the interactive legacy UI, call a service, or advance the canonical planning
requirement, capability, oracle, acceptance inventory, or parity ledger. It
uses no Warehouse sample, network, Docker, subprocess, model, credential,
download, or service lifecycle.
