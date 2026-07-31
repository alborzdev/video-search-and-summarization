# Wave-3 official-documentation coverage denominator

This isolated candidate package records the complete set of 152 distinct HTML
targets linked by the NVIDIA VSS 3.2.1 documentation index on 2026-07-31. It
does not modify the live capability ledger, parity manifest, capability
oracles, acceptance inventory, static wrapper, or source lock.

The package has two machine-readable layers:

- `docs-index-targets.json` is the exact, sorted 152-URL denominator. The
  canonical SHA-256 of its compact sorted URL array is
  `b70c4d6979c3ea2b60e41a5352704aba8e14c39773bde8159e1c725242265f28`.
- `coverage.json` classifies every denominator URL exactly once and records its
  reason, current direct live source/capability links, source-lock state,
  required action, and candidate wave.

The audited page classification is exact:

| Category | Count | Meaning |
| --- | ---: | --- |
| `covered_live` | 51 | Direct live source and capability links exist. This is claim linkage, not proof that every page semantic was extracted. |
| `semantic_omission` | 59 | The page contains advertised workflow, operation, configuration, model, benchmark, calibration, profile, or limitation semantics requiring precise Wave-3 extraction. |
| `navigation_duplicate_reference` | 34 | Navigation hub, prior-version reference, placeholder, JavaScript search page, or empty generated reference shell. |
| `external_license_sample_dependency` | 8 | Legal terms or a workflow that depends on hosted, training, simulation, or sample systems outside the core Thor-local runtime. External workflows still require explicit boundaries. |

The exact 59-, 34-, and 8-page lists are the page objects in `coverage.json`;
the validator independently pins the same three path sets and rejects any page
moving between them. The remaining 51 URLs are derived as the exact set
difference against the independently bound 152-URL denominator.

## Source-lock transition

At audit start, the byte lock had 52 records: 51 index-linked pages plus
`index.html`. `release-notes.html` was a live ledger source but its distinct
`release_notes` kind was excluded by the source-lock collector. The current
lock has 53 records: 52 index-linked pages plus `index.html`, and now includes
the release notes.

That transition closes a raw-page-byte provenance gap only. Release notes
remain a `semantic_omission`: the live ledger represents one of the three VSS
3.2.1 feature bullets and does not completely transcribe the conservatively
counted 201 top-level VSS 3.2.0 bullets.

## Semantic boundaries

This package deliberately rejects both of these implications:

- A raw HTML byte hash proves that all page semantics were extracted.
- A route, operation, or OpenAPI schema hash proves runtime behavior.

The API audit binds the current 17-surface inventory and all 17 expected
manifests. It records 326 declared REST operations, 325 normalized REST
operations, 75 operations with static schema hashes, 251 with null schema
hashes, 38 MCP tools, and 5 MCP prompts. The live OpenAPI comparison checks
method/path sets. All 161 capability oracles remain planning-only and zero are
executor-ready.

## Validation

Run from the repository root:

```bash
python3 deploy/docker/thor-local/parity/candidates/wave3/coverage/validate_coverage.py --report
python3 -m unittest discover \
  -s deploy/docker/thor-local/parity/candidates/wave3/coverage/tests -v
ruff check deploy/docker/thor-local/parity/candidates/wave3/coverage
```

Validation is offline. It checks strict schemas and duplicate keys, the exact
URL denominator and canonical hash, exact category sets/counts, current
source/capability linkages, all input file hashes, source-lock state, release
arithmetic, API/MCP counts, operation-manifest membership, and the mandatory
false semantic-proof flags.

The approximately 100 GB NVIDIA Warehouse sample bundle remains excluded. Its
absence cannot remove custom-data Warehouse capabilities from the semantic
denominator or turn that optional reference fixture into a local parity gate.
