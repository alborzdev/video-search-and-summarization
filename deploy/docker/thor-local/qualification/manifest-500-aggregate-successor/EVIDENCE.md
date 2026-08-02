# Evidence

## Scope and conclusion

The locked ledger-500 successor contains 55 feature families and 500 capability records. The corrected live aggregate algorithm produces six differences and zero after projection. The former nine-row result is retained only as a regression diagnostic: applying it would violate the live manifest's external-boundary rule in three places.

After the six-field transform:

- current live aggregate drift is zero;
- the legacy reducer reports only the three known external-policy residuals;
- eight acceptance-scenario gaps remain open;
- no runtime evidence or state promotion is asserted;
- no Warehouse sample data is included or required.

## Locked algorithms

The package raw-locks both live policy implementations:

- `parity/verify_official_capabilities.py` (`c21fd2910089c6981f0437d41d6c9ef7fff19d55c0153b04b7f7f91b00d79109`) supplies the current family reducer and preserves external-family `thor_state`.
- `parity/verify_manifest.py` (`5e9e7551853b4606a95131d1ca46da3d15fea7e307b49d1fbf06b25dacb9a5e2`) requires `external_optional` families to retain `thor_state=external_optional` and `runtime_state=not_applicable`.

The current reducer keeps the existing acceptance and runtime derivations, but returns family `thor_state=external_optional` whenever the derived family acceptance class is `external_optional`.

## Deterministic artifact identities

- Projected manifest raw SHA-256: `c71f75246fc1e4cbc388f93849d27c3b7dc7edf2d0a516fb3fa13f6d412a4a93`
- Projected manifest canonical SHA-256: `68620554a3a5f731d15283787f1e0bb3ff8e4a4e673b726412c94d592caf790c`
- Projection proof raw SHA-256: `65583c243381ab36f9804d66fa58299bf0cb3d1a3685d76d8af70c2fd5b029a3`
- Projection proof payload SHA-256: `d2f5a88ad2351bcd23ecba6916283e249460c6fe2e9bffc867e52a9aded35814`
- Projection schema raw SHA-256: `b1794e3ebeada0dfede9f96195b47c4eecda4fad6676f0080ced0036090da2cf`
- Projected manifest schema raw SHA-256: `95d981d86879a2ac6e5a69c2f0a2c154d826f54ce15d87f773c0048f39c7ed48`
- Exact legacy nine-row regression diagnostic canonical SHA-256: `f629a11b2ef6934d2bbf6b4900659fe3e0f10d531c05884b3b8fc2290bea97ce`

The proof also binds the final ledger-500 proof, schemas, manifest, capabilities, live manifest, acceptance inventory, and both verifier implementations by repository-relative path and raw SHA-256.

## Validation coverage

Tests verify deterministic compilation, exact-value schemas, rejection of feature/skill reorder and identity substitutions, capability-ID reorder, valid-enum scalar mutations, exact legacy-9/preserved-3/current-6 partitioning, current reducer precedence, six-field-only mutation, feature/skill/capability-ID preservation, zero current drift, exact eight acceptance gaps, rejection of the legacy raw-nine external-family result, duplicate/non-finite JSON rejection, repository path and symlink defenses, atomic-output defenses, and absence of network/Docker/subprocess/runtime actions.
