# Evidence

## Scope and conclusion

The locked ledger-500 successor contains 55 feature families and 500 capability records. Replaying the exact live aggregate algorithm produces nine raw differences. Applying all nine would violate the live manifest's external-boundary rule in three places, so the accepted candidate applies six fields and preserves three `external_optional` states.

After the six-field transform:

- policy-correct aggregate drift is zero;
- the uncorrected reducer reports only the three known external-policy residuals;
- eight acceptance-scenario gaps remain open;
- no runtime evidence or state promotion is asserted;
- no Warehouse sample data is included or required.

## Locked algorithms

The package raw-locks both live policy implementations:

- `parity/verify_official_capabilities.py` (`930ed6caa04eea6dc79984ceb0ee8babe39db6074ac6c74a1e43349dcbc8e8e7`) supplies the current family reducer.
- `parity/verify_manifest.py` (`5e9e7551853b4606a95131d1ca46da3d15fea7e307b49d1fbf06b25dacb9a5e2`) requires `external_optional` families to retain `thor_state=external_optional` and `runtime_state=not_applicable`.

The policy-correct reducer keeps the current acceptance and runtime derivations, but overrides derived family `thor_state` to `external_optional` when the derived family acceptance class is `external_optional`.

## Deterministic artifact identities

- Projected manifest raw SHA-256: `c71f75246fc1e4cbc388f93849d27c3b7dc7edf2d0a516fb3fa13f6d412a4a93`
- Projected manifest canonical SHA-256: `68620554a3a5f731d15283787f1e0bb3ff8e4a4e673b726412c94d592caf790c`
- Projection proof raw SHA-256: `1a4c3e75dc449b3c049e37b616f1a6a12b9989b5426912600cf5d99b84d04243`
- Projection proof payload SHA-256: `dea5eb7dc4322d3d517b9b0f196ea5f214d5349280176c17792f950e3c0bbb25`
- Projection schema raw SHA-256: `ec852a87a8cd638523301b1616ee5e72af2a32aedd5feffd8d0afceee99b382b`
- Projected manifest schema raw SHA-256: `95d981d86879a2ac6e5a69c2f0a2c154d826f54ce15d87f773c0048f39c7ed48`
- Exact raw nine-row proof diagnostic canonical SHA-256: `f629a11b2ef6934d2bbf6b4900659fe3e0f10d531c05884b3b8fc2290bea97ce`

The proof also binds the final ledger-500 proof, schemas, manifest, capabilities, live manifest, acceptance inventory, and both verifier implementations by repository-relative path and raw SHA-256.

## Validation coverage

Tests verify deterministic compilation, exact-value schemas, rejection of feature/skill reorder and identity substitutions, capability-ID reorder, valid-enum scalar mutations, exact 9/3/6 partitioning, status reducer precedence, six-field-only mutation, feature/skill/capability-ID preservation, zero corrected drift, exact eight acceptance gaps, rejection of the raw-nine external-family result, duplicate/non-finite JSON rejection, repository path and symlink defenses, atomic-output defenses, and absence of network/Docker/subprocess/runtime actions.
