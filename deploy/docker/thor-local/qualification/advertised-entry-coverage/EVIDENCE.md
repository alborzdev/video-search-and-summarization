# Static compilation evidence

This record describes static semantic inventory evidence only. It is not Thor
runtime evidence and does not qualify or promote any VSS capability.

## Locked source identities

| Source | Raw SHA-256 | Canonical JSON SHA-256 |
| --- | --- | --- |
| `parity/manifest.json` | `1f56d63437bd7742cf7488b9bd85b25fc886cdaf39a3c2b46aabecbc6b7201ce` | `cbf65ddc55b3518763bf8ee57f58f24619956473035aeca98a274a7b1bc959f2` |
| `parity/official-capabilities.json` | `cde0dc3981aaf699a017c7108089aac72070101edc47a06489f3940e44fe52a0` | `30142a6716d48597f2daee6a5e776629393526bc7185ca7f70b89fefe2b13eec` |
| `parity/capability-oracles.json` | `c4e7a5ecfedfa2ddf18e68fc2bc110bea48d9ff7ce63d0dd4fdc169711beda90` | `6d2b3991e6e31a74ba42c3271d7cc0dce8748468617d18772078db6abfd1e336` |
| `advertised-entry-gaps/plan.json` | `2fc3a8fbcbfd8afa62e657cf0d4b3f34d568294b089bd71f0f87354e9196745c` | `e3e3a81401795983a33f7f2584cc004eac3c363719cd29b83af15aaa62a4f85b` |
| `runtime-lanes/runtime-lane-plan.json` | `bf863fac268d1247eda71b9edbfd497580453c52cd3ced7fcdb333386efa25c9` | `6645431c98b86cd615b8b06b45f72ea71b2f53b408610c5da43ede06a316da55` |

## Checked output

- Schema: Draft 2020-12, raw SHA-256
  `dd1e29e3c6cae82a1b28af5f5630a7e88d70dedb7570084c74c3e95ef578460b`.
- `coverage.json` payload SHA-256:
  `cc9dbbc4ccf0aec704c30ad013097eec1e2b36a506e1615a9006ca684d780a90`.
- `coverage.json` raw SHA-256:
  `2ea517799c03bcc432856a805b8e35ae1d97c8c3dd2f7b928d99004bbb7b6af5`.
- 55 feature families and 500 unique manifest entry pointers.
- 276 exact existing mappings, 13 canonical entry mappings, 74 explicit
  missing-entry gaps, and 137 family-only unreviewed rows.
- 289 exact semantic mappings and 211 literal semantic blockers.
- 305 required, 159 alternate-local, and 36 external-excluded obligations.
- Zero runtime evidence records and zero Warehouse sample bundle entries.

The adversarial tests reject duplicate pointers, ambiguous title mappings,
title or feature drift, missing source claims or oracles, oracle ledger drift,
gap overlap, runtime-lane disagreement, fabricated runtime evidence, Warehouse
sample fixtures, external-to-local reclassification, unsafe source files, and
mapping-class overlap. They also reject an external row whose default or lane
set is not exactly `external-optional`, and any required or alternate row that
defaults to the external lane.
