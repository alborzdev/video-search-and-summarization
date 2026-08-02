# Metadata 500 composition evidence boundary

Status: **static metadata composition passes; live and runtime migration remain
pending**.

Final deterministic identities:

- composition raw SHA-256:
  `600f2ee62b19862c81c23f2a7f2e95ff40f8a5c6e400ce5129f661f5f1a8538c`;
- composition payload SHA-256:
  `37f8b32b77e849d4328d8dfdc24428fc97f998f0eb70f473e87cc3ffeace3570`;
- exact composition schema raw SHA-256:
  `fcb09884ecc345cedafdbb63997783bbb87c6f8336d9e9813a8ba9869887c12e`.

The deterministic proof establishes:

- every source artifact and strict schema from all four successor packages is
  raw-hash locked and validates;
- successor proof-to-artifact bindings are exact;
- the authoritative official-capability validator returns 126 sources, 500
  capabilities, 55 feature families, and 47 discrepancies for the composed
  projected ledger, policy-valid manifest, and acceptance inventory;
- independent policy aggregation and acceptance coverage reducers both return
  empty drift lists;
- the 500 oracle capability IDs exactly match ledger ID set and order, with
  exact per-row ledger bindings;
- the live predecessor ledger and oracle registry remain exact ordered 289-row
  files, with 55 manifest and acceptance feature records;
- all 211 candidate oracles remain non-executable, unevidenced,
  non-materialized, and non-promotable; and
- no runtime, network, Docker, host, model, cloud, or Warehouse sample action is
  performed or authorized.

Adversarial coverage includes cross-swapped manifests, ledger and oracle order
changes, family status drift, removed scenario coverage, mutated oracle
bindings, invented evidence or activation, duplicate and non-finite JSON,
unsafe paths, symlink traversal, unsafe output targets, source lock changes,
and exact-schema mutations.

This is a composition proof, not permission to overwrite live files or execute
candidate oracles.
