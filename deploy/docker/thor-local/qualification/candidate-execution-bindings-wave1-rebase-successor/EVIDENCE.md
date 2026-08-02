# Candidate execution bindings Wave 1 rebase evidence

## Final provenance

- Execution-binding registry: `af3927c15f9e5c1efb67690ee7ca3f3e6ee9fb77e720767db2264d68a935b6b5`
- Admission index: `74398a4239cfd13f753924aaf65b5ce16e6f96b44dc9eae8067eddb8a03456ff`
- Empty admission receipts: `e3d3d918bb392d903c00d82687efbf24d7c834019761929304019bbd4930132f`
- Wave1 contract: `fae464894d7d565a1078f852776bb005e0426c4280473d551bbec3e727e2d53c`
- Wave1 receipt: `ab07eac3e5c240f55d2480fe34aa5128be0cd62b3a64027e3ae689cb27bd0396`
- Wave1 successor: `1a066029a04bc67bcefd4571f24fce1cda1df275ab48aed48f99ea7e274f10b5`
- Empty authority registry: `954aa42541f715bdbb25148a322e2e3b3380f27fc4f958e8ba0e7378945acdd4`
- Empty signed receipts: `84ce0c682a49dc930f33fa2bb698e9a7f66a14902cf123e0cba060a8c0f8ed24`

All 34 active sources, their applicable schemas/producers, all six historical
package files, and the canonical selector/descriptor are raw-hash locked.

## Deterministic output

- Binding rows: 2
- Binding-row canonical SHA-256: `f088de43966cb2f1e7a5451f6912be3d6736690eb2c4dc413e38a78e63acba1a`
- Overlay raw SHA-256: `d0052aaaac394b93d9e13a560411982d1d81690fcd9a2c0ebabdee15a1cbb0c1`
- Historical overlay raw SHA-256: `aeb8eec139138f45a12a7673abe6f65cca455dbc1717e145e626fc58e70add24`

A normalized row-by-row comparison proves exact preservation of the historical
binding, action, executor, service/profile, cleanup, postcondition,
authorization, and runtime semantics. Candidate/source integrity hashes and
source-level blocker text are rebased to the finalized sources; they do not add
authority, executability, evidence, or admission.

Validation is deterministic and read-only. It performs no subprocess action
except tests invoking the validator CLI, and no runtime, network, socket,
Docker, signing, service, model, download, credential, or Warehouse operation.

Final validation: 15 tests passed with zero skips; `--check` passed; `--emit`
was byte-identical to the checked artifact; Ruff lint and format checks passed;
strict Draft 2020-12 schema validation passed; and `git diff --check` passed.
