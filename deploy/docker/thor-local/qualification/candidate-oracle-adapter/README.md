# Candidate oracle adapter

This package deterministically translates all 211 rows in
`remaining-advertised-entry-candidates/candidate.json` into a machine-usable,
candidate-only oracle adapter keyed by proposed capability ID. It does not
merge those rows into the live capability ledger or live oracle registry.

Each adapter preserves the exact candidate oracle plan and exposes structured
fields for a future `capability_oracles` compiler:

- stable fixture identity, namespace, and complete input contract;
- exact required-observation and adjacent-negative records;
- assertion records with stable observation references;
- explicit admission gates;
- cleanup intent and ownership boundary;
- acceptance class, execution boundary, and execution-bound seed fields;
- exact source claims and repository implementation surfaces; and
- the authoritative gap requirement for each of the 74 explicit gap rows.

Materialization, executor, collector, duration, request, and action fields are
null. Every candidate remains `planning_index_only`, unexecuted, without
evidence, not executor-ready, and unable to promote runtime state.

The artifact also carries a capability-ID-keyed projection of the current 289
oracle states and evidence arrays. Canonical hashes bind the complete current
ledger and oracle record arrays so a future merge can prove those records were
not semantically changed.

## Inputs and safety

The compiler raw-locks the candidate artifact and schema, current official
capability ledger and schema, and current capability oracle registry and
schema. Reads reject duplicate JSON keys, non-finite JSON, absolute or parent
paths, symlinks, non-regular files, source-ID drift, synthetic `Advertised `
locators, duplicate capability keys, and invalid implementation surfaces.

The compiler performs static local file reads only. It does not use the
network, Docker, services, models, subprocesses, or host inspection, and it
does not create runtime evidence.

## Check

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/candidate-oracle-adapter/compiler.py \
  --check

PYTHONDONTWRITEBYTECODE=1 pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/candidate-oracle-adapter/tests/test_compiler.py
```

`--write` regenerates only this package's `adapter.json` through a
same-directory regular temporary file and refuses to replace a symlink.
