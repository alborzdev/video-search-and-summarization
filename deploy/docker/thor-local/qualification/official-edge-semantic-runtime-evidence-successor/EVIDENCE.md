# Static collector evidence

Status: collector contract implemented; no live receipt captured.

The package binds the VSS 3.2.1 release commit
`7640d917047cf7b0fd3085eefb8282754b56bc94`, reviewed main commit
`7732edf8fb38ef896b20f2a0a6a701a4db10dc57`, official-edge contract and
artifact lock, official-edge static verifier/configuration, readiness plan and
schema, Thor model requirements, and the shared bounded transport.

Approved collector hashes:

| File | SHA-256 |
| --- | --- |
| `contract.json` | `046f1a9090127f6a2ca3c9f5b355b10f8a60c3498683bba758f8509374119744` |
| `executor.py` | `8e18b9d04f9535a3f6aee40758d739f5be5767f918e7f4f38beb949390856d79` |
| `manifest.schema.json` | `626e05b3cc4671f27cd2b2d48d2033e649f39358c175018670e1fbd2c727632a` |
| `receipt.schema.json` | `9d97049e63083edab28e2a7a924c3f7e06677f32a560a9610317bde5b3fed421` |

The fake suite covers inert planning, missing acknowledgement, success,
incorrect/aliased model IDs, hostname/cloud targets, missing and stale
prerequisites, source/readiness mismatch, cloud credentials, forbidden Qwen
fallback, tool and visual false positives, incomplete dual-model Agent proof,
redirects, proxy configuration, time budget exhaustion, cleanup failure, and
receipt digest/content tampering.

No live network, Docker, service lifecycle, model, download, raw credential,
raw prompt, response body, or Warehouse data was used to produce this evidence.
