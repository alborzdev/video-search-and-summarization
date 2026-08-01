# Advertised entry gap plan

This isolated package compiles manifest-advertised strings in families that
have no capability rows, plus uncovered strings in explicitly partial families.
The locked VSS manifest currently has 14 such families: 13 have no
`official_capability_ids`, while `vios-codecs-audio` is partial. Its CPU
multimedia entry is canonical but still runtime-unqualified; its other five
media entries remain in this plan. The plan therefore contains exactly 74 open
advertised entries.

The twelve Spatial AI and synthetic-data tooling entries now have exact
canonical capability/oracle rows. Their source contracts remain static-only and
runtime-unqualified, so this retirement from the missing-entry plan is not a
runtime promotion. AWS/GCS validation remains an external-optional capability.

This is not the global entry-specific denominator. Across all 500 advertised
strings, 289 have exact capability-title and oracle mappings: 13 canonical
`manifest-entry.*` rows and 276 pre-existing capability rows. The 74 entries
here are explicit empty/partial-family gaps; another 137 retain family-only
planning bindings. All 211 entries without exact mappings block literal
completeness.

Every output entry preserves:

- its exact `/features/<n>/advertised/<n>` JSON pointer;
- the exact manifest string plus UTF-8 and canonical-JSON SHA-256 hashes;
- its family pointer, family-object hash, category, acceptance class, and
  current family state as a snapshot only;
- a proposed entry-specific capability ID and a concrete oracle/executor class;
- the setup, evidence, literal success condition, and owned cleanup needed to
  verify the advertised behavior.

All 74 plan entries remain `open_missing_entry_capability_and_oracle`, with their
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
