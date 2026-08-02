# Candidate approval mapping rebase successor v2

This immutable sibling rebases the historical v2 mapping onto the finalized candidate mapping, 16-bundle runtime contract, and Sparse4D dependency-repair rebase.

The compiler pins the finalized mapping rebase (`dd5be5e9…6722a`, schema `41271a97…bc3d5`), runtime-bundle rebase (`415931c4…af194`, schema `2f277445…2eabe`), and the Sparse4D artifact (`099b89d6…247d7`) and schema (`162e203b…22e87`), including each upstream compiler and test identity.

Generation preserves exactly 209 rows from the rebased predecessor mapping and changes only the Sparse4D dependency-conflict row and firewall scope-gap row. Every candidate remains `no_receipt_not_admitted_not_executable`; all approval, receipt, admission, and execution counts stay zero. The Warehouse sample remains excluded.

Check or emit the deterministic artifact, or use the bounded writer which creates only an absent package-local `mapping.json`, is idempotent for identical bytes, and refuses overwrite:

```bash
python3 deploy/docker/thor-local/qualification/candidate-approval-mapping-rebase-successor-v2/compiler.py --check
python3 deploy/docker/thor-local/qualification/candidate-approval-mapping-rebase-successor-v2/compiler.py --emit
python3 deploy/docker/thor-local/qualification/candidate-approval-mapping-rebase-successor-v2/compiler.py --write
```

Tests:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/candidate-approval-mapping-rebase-successor-v2/tests
```

This package performs no runtime, host, network, or Docker action. Its sole write surface is the bounded package artifact writer described above.
