# Candidate admission receipts rebase successor

This immutable sibling publishes a deterministic 211-row admission index and the only currently trustworthy receipt state: the exact empty set. It rebases provenance onto the finalized mapping-v2 and 16-bundle runtime successors plus the migration→activation receipt chain. It does not consume approval receipts or execute candidates.

After normalizing source hashes, all 211 admission rows retain the historical admission state, candidate order, execution boundary, leaf, complete contract-ordered dependency closure, blocker classification, receipt IDs, and Warehouse exclusion. The three static rows remain non-applicable; 204 local/alternate-local rows remain blocked; four mapped external rows remain external-attestation-only. Receipts, trusted authorities, admitted candidates, and executable candidates are all zero.

Run either safe read-only mode:

```bash
python3 deploy/docker/thor-local/qualification/candidate-admission-receipts-rebase-successor/compiler.py --check
python3 deploy/docker/thor-local/qualification/candidate-admission-receipts-rebase-successor/compiler.py --emit
```

There is no write, execute, action, approval, or receipt-ingestion mode. The receipt schema is a design-only future envelope; its root permits no receipts or authority bindings, so every non-empty set fails closed.

Tests:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/candidate-admission-receipts-rebase-successor/tests
```

The tests cover all 211 source bindings and closures, historical semantic equivalence, migration/activation provenance, exact empty receipt state, adversarial non-empty receipt threats, strict schemas, raw locks, canonical/historical preservation, unsafe paths, and the no-write/no-runtime CLI surface.
