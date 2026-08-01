# Executor mismatch semantic reconciliation

This immutable overlay records the semantic review of the two mismatches found
by the deterministic file-only executor tranche. It appends exactly two live
ledger discrepancy records to the byte-pinned 45-record Wave 3 baseline and
produces the byte-pinned 47-record successor. It does not modify or reinterpret
the historical Wave 3 merge receipt.

The decisions are deliberately narrow:

- Incident field tag 7 is a documentation-to-repository **name** discrepancy.
  The checked-in schemas, generated bindings, and JSON-facing code consistently
  use `analyticsModule`; the tag remains 7. No API rename or binary wire-failure
  claim follows from the rendered table's `analytics` spelling.
- Alert warmup support defaults to enabled in official documentation and service
  source. The Thor Compose overlay alone forces false, making this an explicit,
  unqualified Thor override. It remains a local parity gap until enabled warmup
  is qualified and the override is removed, or reproducible evidence narrowly
  justifies it.

The reconciler pins the descriptor, all nine reviewed repository sources, the
input and output ledger bytes, the record order, and both exact record payloads.
It removes its records to reconstruct the byte-identical Wave 3 baseline before
rebuilding the successor, so partial application and output/record co-tampering
fail closed.

```bash
python3 reconcile.py plan
python3 reconcile.py validate
python3 -m unittest discover -s tests -p 'test_reconcile.py' -v
```

`apply` is idempotent and accepts only the exact pinned baseline or exact pinned
successor. The successor integration receipt owns the later multi-output handoff
for live executor materialization.
