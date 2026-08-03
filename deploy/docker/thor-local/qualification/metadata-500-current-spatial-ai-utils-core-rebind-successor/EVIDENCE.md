# Evidence boundary

This is an immutable metadata rebind, not runtime evidence and not a runtime or
ledger promotion.

## Locked inputs

- Canonical base commit: `548f7fdda9148b3ee521c09dcdb298309f25fe2b`.
- Runtime contract: `7fa1c4070cc3089c3e7f30511cf89bbc0e50fe773ab408e702c6d5717e6470a8`.
- Runtime contract schema: `beda5705dad3b6cdff0c9aa11ae3ecd716df1508e0f7042d503f3a87fde80553`.
- Runtime executor: `e736ff075c3494ab0a6a11208fa564a863588ee14608ba6d1016286a807f78e6`.
- Runtime result schema: `469e3ee85e34481c6d55ca2d544a80bfdefc092f83b55fde28eea0ac6bff4571`.
- Runtime interface: `37a3d29e7a83f2bfa6c09c2a41508eb6c785f8b8267117e82f6ebfdcd1edd305`.
- Current 289-row oracle registry: `b8f03c0d949ae7c9bb6dd14f37142e4f723849125ec944eb9244bd0ad9b79a1a`.
- Selected 500-row oracle registry: `c2b8d584b4bb00f42d6337bbad31038d016fe02a7cfbf92ac747f42075bdc6c0`.
- Current 289-row official ledger: `834bb40b576d9e9e546cecb3bdb866993b7be7fd3bf9d5e9e19a0d852d4e4e39`.
- Selected 500-row official ledger: `315fd11b4e40773cc711a43eb9c27edcaee752649cd71b3d6494fa3eb4d89229`.

## Checked outputs

- Oracle projection: `c2b8d584b4bb00f42d6337bbad31038d016fe02a7cfbf92ac747f42075bdc6c0`.
- Ledger projection: `315fd11b4e40773cc711a43eb9c27edcaee752649cd71b3d6494fa3eb4d89229`.
- Oracle rows: 500 total, 500 preserved, zero changed.
- Ledger rows: 500 total, 500 preserved, zero promoted.
- Retained executor-ready rows: exactly 01, 04, and 05.
- Selected suffix: 211 rows preserved exactly.
- Runtime evidence records: zero; every selected oracle remains
  `open_unexecuted` with empty evidence.
- Entry 07 and all family runtime/ledger state remain unchanged.

The compiler is static and local: it performs no runtime producer execution,
network, Docker, service lifecycle, model, download, credential, cloud-provider,
or Warehouse-sample activity.
