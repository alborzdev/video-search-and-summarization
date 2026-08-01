# Evidence boundary

## Current static result

The networkless executor passes against the current worktree and verifies:

- exact contract SHA-256
  `c60fde74c8d06a9c471c817434ab85cf865941e7f665c375751b995e155ca359`;
- four ordered manifest literals and their exact entry, capability, and
  full-slug oracle IDs;
- canonical `tooling / alternate_local_lane / wired / not_qualified` states;
- four `open_unexecuted` oracles with no runtime evidence;
- 18 unique entry source controls and eight ARM64 lane source controls;
- the current ground-truth converter SHA-256
  `4d81551c3a143f52f3fa4bfdc52f1af6aa01fac864d250a9a3f2547dfdaeef9f`;
- `--skip-visualization`, required `--output`, conditional calibration, a
  temporary alias workspace that does not mutate the input tree, early
  conversion-only return, deterministic ordering controls, and the four exact
  output names;
- conda/pip/wheel lock SHA-256 identities, 178/21/21 denominators, Python
  3.10.20, OpenUSD 26.05, Linux aarch64, and the Miniforge installer identity;
  and
- explicit Warehouse sample exclusion.

Focused adversarial tests cover repeatability and result-schema validation,
contract promotion/extra-field rejection, exact contract digest rejection,
duplicate JSON keys, source-byte tampering, missing AST symbols, missing CLI
flags, ARM64 identity substitution, symlinked inputs, absence of external/write
APIs in the executor, and unchanged input mtimes.

## Evidence classification

This document records a static qualification result, not runtime or semantic
evidence. The executor reports:

```json
{
  "scope": "static_wiring_only",
  "runtime_evidence_created": false,
  "runtime_state_promoted": false,
  "official_capability_effect": "none_static_contract_only",
  "result": "static_source_wiring_verified_runtime_open"
}
```

No Docker command, network call, download, host inspection, product import,
service lifecycle action, or filesystem write is permitted by the contract.
The Warehouse sample bundle was neither used nor required.

## Remaining evidence

Closing an entry oracle still requires two clean executions of the real tool
path in the pinned ARM64 environment using digest-bound tiny custom inputs.
The future receipt must bind the target revision, command, input and output
digests, semantic assertions, negative cases, and cleanup of only
executor-owned outputs. Native OpenUSD, image/depth, HDF5, FFmpeg/ffprobe, and
ground-truth semantics remain outside this static package.
