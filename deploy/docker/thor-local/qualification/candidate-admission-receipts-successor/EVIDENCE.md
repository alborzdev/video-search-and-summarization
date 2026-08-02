# Candidate admission receipts successor evidence

## Locked inputs

The compiler checks raw bytes before interpreting them and rejects source drift,
unsafe paths, symlinks, non-regular files, read-time mutation, duplicate JSON
keys, non-finite JSON, invalid source schemas, or a changed candidate/oracle/DAG
identity.

| Source | Raw SHA-256 |
| --- | --- |
| `candidate-approval-mapping-successor-v2/mapping.json` | `751fd28d59744a709a18eaa6d347e293bb6a665502636e26aaeff65c340f9844` |
| `candidate-approval-mapping-successor-v2/mapping.schema.json` | `b07a5f35c4bbecd6e11fd2d2d0fd20046a90b03bc9747964ef17f18de3d847e0` |
| `candidate-approval-mapping-successor-v2/compiler.py` | `c2e89bf6fa07daf9607bf4f9afcac4874c6150f443f649a837b4afbb03a1ab2e` |
| `runtime-approval-bundles-successor/contract.json` | `74ba837f9e87923ddd48c635a067aeca9929bbf7cd9b3cff5f26157560aa3c0e` |
| `runtime-approval-bundles-successor/contract.schema.json` | `67e052501707a2b12c0bd43c055b5cce41367772ff5c263f8a5b3024592f126b` |
| `runtime-approval-bundles-successor/compiler.py` | `df9727bfe5bb4a67410525b0f3e8fa5f22d1b9a4bd66b22d24174bfa5f39ce31` |
| `live-metadata-500-migration/post-state-capability-oracles.json` | `17091a3c0e9ac4d3aba7b5c6d91f09c8832648f149ac0624f3b63cd2c5e77271` |
| `live-metadata-500-migration/post-state-capability-oracles.schema.json` | `b24308d9647ff7a4c7b66cc91881749eaaa84c21ab7423677fc30ab4f9c36233` |
| `live-metadata-500-migration/compiler.py` | `d1eb9d0e59f9939b63f1ff61768747297cc38e65ebdaa4675b2f378616d11f0a` |

## Checked outputs

| Output | SHA-256 |
| --- | --- |
| `admission-index.json` raw | `6dc6345f9b057c164929a1046b8ebcfb08fdfbedaa1b7a66180f344915d7d7eb` |
| `admissions` canonical rows | `4ba78a32c3fff336b8362a5afc0d78af8076e3c0afb52a87df0985e196bd3160` |
| `receipt-set.json` raw | `7bfeb7e70f9a7c3a2bbbb007c785286146dbfe70e4f63245168cf382b62ec805` |

The checked set contains exactly 211 dispositions, zero receipts, zero trusted
review authorities, zero admissions, and zero executable candidates. The
future envelope definition grants no authority and is not a secure non-empty
receipt-consumption implementation.

## Reproducible validation

The focused validation completed without network, Docker, service lifecycle,
model/download, host/firewall, credential, external-system, or Warehouse
activity:

```text
compiler.py --check: status ok
pytest: 24 passed
ruff check: all checks passed
ruff format --check: 2 files already formatted
JSON parse/schema validation: passed through compiler and tests
```

No runtime state or evidence was promoted. This evidence establishes only the
deterministic checked-empty admission boundary.
