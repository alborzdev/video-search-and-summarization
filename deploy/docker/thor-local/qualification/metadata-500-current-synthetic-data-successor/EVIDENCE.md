# Evidence boundary

Checked derivation:

- Input oracle registry: `metadata-500-current-cancellation-search-successor/post-state-capability-oracles.json` (`355679322116451972cb2366a61bfba23a72762863796aea84c93a7bb412db14`), 500 rows.
- Current root oracle registry: `parity/capability-oracles.json` (`d782a8cc4456018d45fcb824f30f08e7d9195d01d97639e44b7524b2ba32d6c0`), 289 rows.
- Runtime contract: `synthetic-data-runtime-evidence-successor/contract.json` (`a985966163e9bc726abcadf4564b9274657d426ebcd6629e2c8387b79c3ab99c`).
- Oracle schema: `b24308d9647ff7a4c7b66cc91881749eaaa84c21ab7423677fc30ab4f9c36233`.
- Checked future oracle output: `c50c762e94ceb68e05c0e4a49c8d8f5405f462bd030f81bf982cd2593cf5d5b6`.
- The current root policy and all 289 current rows replace the stale selected prefix; the 211 selected candidate rows are preserved exactly.
- Exactly four Synthetic Data rows are changed relative to that rebased baseline; 496 rows and the rebased policy are preserved.
- Exactly four rows have materialized fixture manifests, runtime executor/collector bindings, cleanup executor/collector bindings, and `executor_ready` readiness.
- All 500 rows remain `evidence: []`; this package creates no receipt and performs no runtime-state mutation.

Fixture-manifest raw digests:

- semantic label helpers: `0a079066c4ad506e8589206c8b51e21a0ecacdecb16fc9785c52033b0d279d27`
- dataset checks: `0cc773dd0ec64aa4a45c379b298dc7580eddf89ab7702172fe101807d52c1ff2`
- RGB/depth/video conversion: `171aef78bdd4738fa78f7114b27b9ca9cd0ec528ed52ae2f8be051c5b14dfd25`
- ground-truth conversion: `0a1f7d857d582aa47cd54aa1a956175a67976719443c8a9ed946962d8ef77939`

These raw hashes are deliberately distinct from the semantic generated-input digests recorded inside the manifests. The clean runtime receipt is a separate, subsequent artifact and remains required before actual parity promotion.
