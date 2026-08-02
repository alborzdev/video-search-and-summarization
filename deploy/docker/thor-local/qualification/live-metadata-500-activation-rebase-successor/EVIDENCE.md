# Activation-rebase successor evidence

Review date: 2026-08-02.

## Exact artifacts

- Projected descriptor raw SHA-256:
  `4c343433c56daa87e418752de37e51d733037183d8296e1d7692a3dcaccd82ca`
- Projected selector raw SHA-256:
  `d44bb521d56f87e32396b619b70ee0b2c645e79bc6d78ebd8c6a380575f25112`
- Activation receipt raw SHA-256:
  `93baf20b5bdb0e46d61595613dac778ffe8a3eb4e1a76a31dc943d2b46e4037e`
- Exact receipt schema raw SHA-256:
  `5a4d3c481577540b21531ca08fbfe3e814b310a5e428b9fd7af8b02f9c9bb85f`
- Receipt payload SHA-256:
  `93d6817c811fb66d581a7d2285bfdf4738317871c21513e1e6d0bacbf0161000`

All source and output locks are final lowercase SHA-256 values.

## Validation

The compiler validates the migration-rebase proof against its exact schema and
cross-binds all five post-state artifacts. It then validates the projected
descriptor and selector against the canonical schemas, resolves them in a
temporary isolated repository, and runs the authoritative bundle verifier.

The exact report is:

- 500 capabilities;
- 500 ordered v2 oracles;
- 55 feature families;
- 126 official sources;
- 47 recorded discrepancies;
- 211 candidate oracles;
- zero candidate runtime evidence;
- zero candidate executor-ready rows.

## Strict deltas and preservation

The descriptor changes seven actual JSON leaves: the four migration-owned
document paths, the ledger and oracle raw hashes, and the v2 oracle-schema path.
Its set ID, lifecycle, target, mode, counts, and official-schema binding remain
unchanged.

The selector changes exactly two leaves in its selected Metadata-500 row:
descriptor path and raw hash. `selected_set`, set IDs/order, and the 289 row are
unchanged.

Twenty-four byte locks protect every file in the historical migration and
activation packages plus the canonical selector, canonical Metadata-500
descriptor, and 289 descriptor. Compilation rechecks these locks before any
projection.

The rollback journal restores the exact predecessor selector, preserves the
old descriptor, and permits removal only of the new descriptor at its exact
path/hash. It rejects partial and unknown states.

Adversarial tests cover source lock drift, migration proof/schema and artifact
cross-binding drift, promotion/evidence drift, selector ownership drift,
descriptor identity/lifecycle/count/order drift, selector selected-set/set-row
drift, receipt tampering, artifact tampering, exact pointer deltas, rollback,
and absence of any workspace writer.

No canonical selector, canonical descriptor, historical package, runtime,
service, network, Docker, model, Warehouse, or production file was modified.
