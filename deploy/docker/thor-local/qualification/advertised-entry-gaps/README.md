# Advertised entry gap plan

This isolated package compiles the complete set of manifest-advertised strings
whose feature family has no `official_capability_ids` binding. The locked VSS
manifest currently contains 16 such families and exactly 87 advertised entries.

Every output entry preserves:

- its exact `/features/<n>/advertised/<n>` JSON pointer;
- the exact manifest string plus UTF-8 and canonical-JSON SHA-256 hashes;
- its family pointer, family-object hash, category, acceptance class, and
  current family state as a snapshot only;
- a proposed entry-specific capability ID and a concrete oracle/executor class;
- the setup, evidence, literal success condition, and owned cleanup needed to
  verify the advertised behavior.

All 87 entries remain `open_missing_entry_capability_and_oracle`, with their
oracles `open_unexecuted` and `runtime_evidence: []`. A family lane, static
source presence, or even a family-level `passed_current` state is explicitly
not semantic coverage of its individual advertised strings.

## Warehouse scope

The optional NVIDIA Warehouse sample bundle is excluded. The eight Sparse4D
and MV3DT entries remain in scope through bounded, operator-supplied custom-data
and calibration workflows.

## Commands

```bash
python3 deploy/docker/thor-local/qualification/advertised-entry-gaps/compiler.py check
python3 deploy/docker/thor-local/qualification/advertised-entry-gaps/compiler.py validate
python3 deploy/docker/thor-local/qualification/advertised-entry-gaps/compiler.py compile
python3 -m unittest discover -s deploy/docker/thor-local/qualification/advertised-entry-gaps/tests -v
```

`compile` writes only when passed an explicit `--output`. `check` and `validate`
recompile in memory, validate both schemas, verify every source/output digest,
and require byte-for-byte semantic equality with checked-in `plan.json`.
