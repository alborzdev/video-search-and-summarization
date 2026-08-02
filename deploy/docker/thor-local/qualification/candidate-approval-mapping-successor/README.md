# Candidate approval mapping successor

This package is an inert, deterministic classification of the 211 candidate
oracles in the selected 500-oracle Metadata500 set. It maps candidate plans to
the existing generic approval-bundle vocabulary without granting approval,
creating a receipt, admitting a candidate, or making a candidate executable.

The package deliberately contains no runtime executor or receipt consumer. It
does not invent commands, action/flag vectors, service roles, profile IDs, or
Compose paths. Approval never inherits through a dependency link. Every linked
dependency remains unresolved until a separate receipt or a reviewed
`not-required` determination exists.

## Check the artifact

Run from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 deploy/docker/thor-local/qualification/candidate-approval-mapping-successor/compiler.py --check
```

`--check` compiles from the locked inputs, validates the result against
`mapping.schema.json`, and requires byte-for-byte semantic equality with the
checked `mapping.json`. `--emit` prints the deterministic artifact to standard
output; the compiler has no artifact write mode.

## Exact result

| Classification | Count |
| --- | ---: |
| `mapped` | 206 |
| `static_nonactivating` | 3 |
| `unmapped_contract_conflict` | 1 |
| `unmapped_scope_gap` | 1 |

The 206 mapped rows have these direct leaves:

| Direct approval-bundle leaf | Count |
| --- | ---: |
| `profile-lifecycle` | 184 |
| `mv3dt-custom-data` | 9 |
| `external-attestations` | 4 |
| `audio-native-runtime` | 3 |
| `audio-asr-transcript-runtime` | 2 |
| `sparse4d-custom-data-models` | 2 |
| `search-scale-100` | 1 |
| `search-scale-progressive-2-4-8-16` | 1 |

Candidate bindings are exact: 60 workload bindings, 23 protocol-v2 bindings,
and 128 candidates with neither binding. Binding objects and their integrity
hashes are preserved from the locked source rows.

Three documentation/skill-only rows are static and non-activating. The two
unmapped rows are intentionally explicit:

- `manifest-entry.warehouse-3d-and-mv3dt.00-sparse4d-3d-warehouse` is a
  contract conflict: its advertised Sparse4D surface contradicts its MV3DT
  dependency. `sparse4d-custom-data-models` is recorded only as a suggested
  bundle pending contract repair and review.
- `manifest-entry.offline-security.05-physical-interface-firewall` is a
  physical-host scope gap and has no approval-bundle leaf.

Native audio observation is not treated as proof of an ASR transcript. External
attestation cannot qualify a local runtime capability. All candidate service
bindings remain `unresolved_not_declared_by_candidate`.

## Safety boundary

The Warehouse sample bundle is excluded and required cloud inference is false.
The package has zero receipts, zero approvals, zero admitted candidates, and
zero executable candidates. Adding a fabricated receipt elsewhere still cannot
make this package execute because it has no receipt consumer or runtime action
surface.

Future activation requires a separately reviewed service-role registry, exact
action and receipt schemas, and an explicitly authorized executor outside this
package. Those are intentionally not inferred here.
