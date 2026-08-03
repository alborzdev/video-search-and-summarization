# Evidence boundary

This package contains a future oracle projection plus a separately captured, clean,
target-bound runtime-evidence aggregate. Canonical metadata is still only projected,
not mutated by this package.

Stage-2 aggregate:

- Raw SHA-256: `7fb004dd62139c3d738e5c2b4bfcf7430ec0c1e3000efa664f4cfb12b1406cf2`.
- Clean checkout: `537b3e1fd0b5104de5a09515a53bade8ef5e9a79`.
- Exactly two promotion-eligible capability results; zero network, Docker, download,
  model, service-lifecycle, and Warehouse-sample accesses.
- The compiler deep-validates outer result bindings and both nested canonical official
  receipts, proves a 289-row promoted prefix and preserved 211-row suffix, and permits
  exactly two capability-row changes plus one family change.
- Aggregate-selector-compatible official schema copy SHA-256:
  `71f1e0f1d820c3809ea3b55abb504071321f61c6e36978226dd10108c7b2384b`.

Locked baseline:

- Current root oracle registry: `c45bc270163b2369b1650d638f5fa0e3f53aa327e4b0375e6773246ca35fbbf5`, 289 rows.
- Current selected Synthetic Data oracle registry: `c50c762e94ceb68e05c0e4a49c8d8f5405f462bd030f81bf982cd2593cf5d5b6`, 500 rows.
- Selected oracle schema: `b24308d9647ff7a4c7b66cc91881749eaaa84c21ab7423677fc30ab4f9c36233`.
- The current root policy/289-row prefix is rebased and the selected 211-row suffix remains exact.
- Checked future oracle projection: `53fe977aa208cdc78604e214817dac7d3683edea4402b160b9d3cf46571b49e3`, 500 rows.

Runtime interface:

- Cam-info fixture manifest: `8dd769695b2f9ce48081f79c6f1e9c6f54423411f738fb23e58abc791869d2a5`.
- Pub/sub fixture manifest: `0cb77ffe349809e1a8fe9349ecb1859a63ac564077b3326aadac6af264cd57ab`.
- Shared two-camera source payload: `055c9cf201030130d9a449721492a495534815b81425cd98477ad25cdb7712b4`.
- Runtime executor: `650894ecc69baa518a92d8315c2d11c356b815a299ee50dc1e7b21737a87d567`.
- Runtime contract: `1509df349f8ff9086bf6ade52f552f3b5338f0261111ab9b70ff7cc6d575b5f2`.
- Target requests/actions: two positive plus five adjacent-negative, exactly seven per capability.
- Supporting actions: pub/sub performs three additional camInfo fixture generations; aggregate totals are 17 bounded capability actions and 14 requests.
- Imported-source accounting: six model-argument helper invocations are separate from the bounded actions, for 23 literal imported source-function invocations.
- Cleanup targets and allowlists remain the exact canonical oracle namespaces.
- The one reviewed runtime executor occupies generator, executor, collector, cleanup, and postcondition-collector roles.

The checked output contains no evidence and leaves both `current_state` values open. It does not qualify the historical candidate observation, mutate canonical metadata, or access the network, Docker, services, models, downloads, credentials, or the Warehouse sample bundle.
