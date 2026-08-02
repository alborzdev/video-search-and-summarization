# Evidence

This package was compiled and tested statically. No network, Docker, service,
host, model, download, runtime, or Warehouse sample action was performed.

## Locked identities

- v1 mapping raw SHA-256:
  `4bb8f3a5fba5e201b72e1f1a0f4218bff4b9a999a836c192fca44ca7e35d9cf9`
- 16-bundle approval contract raw SHA-256:
  `74ba837f9e87923ddd48c635a067aeca9929bbf7cd9b3cff5f26157560aa3c0e`
- Sparse4D dependency repair raw SHA-256:
  `2ed1a2bb1afc7b3e79d4a1a688d770780639f307f06f29d222e13f3d23683ffd`
- selected capability-oracle registry raw SHA-256:
  `17091a3c0e9ac4d3aba7b5c6d91f09c8832648f149ac0624f3b63cd2c5e77271`
- candidate order canonical SHA-256:
  `1c0cc33efa1aa6283e467e5fc78bbed8b4cbe8ff23fdbf6db3190144996a3ef9`
- candidate rows canonical SHA-256:
  `8cc136ea78c7395c534db0c8601b4881ac7982a70e6c43218a6d7cc20b6ef5b4`
- 209 preserved mapping rows canonical SHA-256:
  `de1907e019b0908c3acd9a0785e29e177367d16d2667e8a49d798e8940cf77d8`
- v2 mapping rows canonical SHA-256:
  `a7290d1ff2791b095789a5c2076115a54e2cdedfe14c744897d9674f3add6f94`
- checked `mapping.json` raw SHA-256:
  `751fd28d59744a709a18eaa6d347e293bb6a665502636e26aaeff65c340f9844`

The artifact contains 11 exact raw source locks. The compiler validates every
JSON artifact against its paired strict schema before using it and rejects
duplicate JSON keys, symlinked repository paths, source-hash drift, denominator
drift, candidate reordering, and candidate-row identity drift.

## Preservation and resolution proof

The compiler deep-copies the predecessor mappings and changes only the rows for:

1. `manifest-entry.warehouse-3d-and-mv3dt.00-sparse4d-3d-warehouse`
2. `manifest-entry.offline-security.05-physical-interface-firewall`

It asserts the remaining 209 rows are exactly equal and binds their canonical
payload hash. The Sparse4D resolution requires the locked repair to replace only
`runtime.warehouse.profile-mv3dt-pipeline` with
`runtime.warehouse.profile-3d-sparse4d-pipeline`. The firewall resolution
requires the exact 16-bundle contract, with configuration depending only on the
read-only inspection leaf and neither bundle publishing a command.

The repaired Sparse4D candidate-capability canonical SHA-256 is
`086e0cadd433638f890d86d9c1bf95ec0ecab037fb3c4c52323f7b0ff12afd90`.
The selected Metadata500 candidate/oracle bytes remain unchanged; this hash and
the repair provenance describe the single-field planning overlay.

The post-state is exactly 211 total: 208 mapped and 3 static non-activating,
with no remaining conflict or scope-gap rows. Closure and direct-leaf counts are
fixed in both compiler and schema.

## Nonactivation proof

The strict schema and compiler require zero receipts, approvals, admitted
candidates, executable candidates, invented commands, action vectors, service
roles, profile IDs, and Compose paths. Approval inheritance is false. Every
candidate row remains `no_receipt_not_admitted_not_executable`, with no cloud
inference requirement and no Warehouse sample bundle.

The focused adversarial suite covers exact 209-row preservation, exact two-row
resolution, source locks, count/closure integrity, zero activation, schema
forgery, predecessor drift, silent conflict/gap remapping, Sparse4D repair drift,
firewall dependency drift, denominator deletion, duplicate JSON, symlinks, and
the absence of runtime/write CLI or imports.

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider deploy/docker/thor-local/qualification/candidate-approval-mapping-successor-v2/tests
PYTHONDONTWRITEBYTECODE=1 python3 deploy/docker/thor-local/qualification/candidate-approval-mapping-successor-v2/compiler.py --check
```
