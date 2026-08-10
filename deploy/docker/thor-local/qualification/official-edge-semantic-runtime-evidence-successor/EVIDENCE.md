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
| `contract.json` | `f27e25be0b245e1c46a4e5c2f118e09e5ad5eb16c6b54c70cb807161c5a0e424` |
| `contract.schema.json` | `207aab65cb37cd18fa56a98539222604d8f32287d3beceb82201a6bc70b10dc9` |
| `executor.py` | `653546a1d3943c09f24b0c6e5e2fad6506696867e9bd10a531d6e9374075825c` |
| `manifest.schema.json` | `a80b0c799b61a159c8799c6eb3eaa27c9eb24586aa7a3d070bce3a316c2c217a` |
| `receipt.schema.json` | `6bfada0a7636dd3a9902d3f9b5827db35d9b2d514fa71762f543614a7052af34` |

The fake suite covers inert planning, producer-bound readiness timestamps,
caller-time and mtime rejection, hidden positive visual oracles, per-run LLM
tool challenges, missing acknowledgement, success,
incorrect/aliased model IDs, hostname/cloud targets, missing and stale
prerequisites, source/readiness mismatch, cloud credentials, forbidden Qwen
fallback, tool and visual false positives, incomplete dual-model Agent proof,
redirects, proxy configuration, time budget exhaustion, cleanup failure, and
receipt digest/content tampering.

No live network, Docker, service lifecycle, model, download, raw credential,
raw prompt, response body, or Warehouse data was used to produce this evidence.
