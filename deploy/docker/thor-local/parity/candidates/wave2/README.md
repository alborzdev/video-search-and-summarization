# VSS 3.2.1 Wave-2 Candidate Package

This directory preserves the machine-readable extraction package for the
second official-documentation coverage wave. The reviewed package has now been
merged into the live capability ledger, parity manifest, acceptance inventory,
and compiler-generated capability oracles. `merge_live.py` is the idempotent
translation used for that merge; the candidate payload remains immutable
provenance.

The payload is pinned to:

- VSS `3.2.1`
- peeled GA commit `7640d917047cf7b0fd3085eefb8282754b56bc94`
- reviewed main commit `7732edf8fb38ef896b20f2a0a6a701a4db10dc57`
- capture date `2026-07-31`

Exact package contents:

- 26 precise official/tagged source records
- 30 proposed new capabilities
- 9 enrichments of existing capability IDs
- 14 discrepancies, scoped defaults, support boundaries, or known limitations

The approximately 100 GB Warehouse sample bundle is explicitly excluded.
Operator-provided custom Warehouse data remains in scope.

## Fail-closed boundaries

The validator specifically prevents these claims:

- Auto Calibration is officially supported on Thor. Official 3.2.1
  prerequisites are x86_64, Ubuntu 24.04, and driver 590; the Thor lane is a
  custom unsupported alternate lane.
- Loopback binding, firewalling, or an external proxy remediates missing VSS
  inter-component TLS, signatures/MACs, consistent authentication, or complete
  rate limiting/timeouts.
- The RT-Embed service default and search-workflow default are the same scoped
  default.
- An API operation manifest proves model, workflow, report, evaluation,
  configuration, UI, or security semantics.

## Validation

From the repository root:

```bash
python deploy/docker/thor-local/parity/candidates/wave2/validate_candidate.py --report
python -m unittest discover \
  -s deploy/docker/thor-local/parity/candidates/wave2 \
  -p 'test_candidate.py' -v
ruff check deploy/docker/thor-local/parity/candidates/wave2
```

`claim_set_sha256` is computed from the canonical set of every new capability,
enrichment, and discrepancy/boundary claim associated with that source. The
canonicalization is implemented by `source_claim_hashes()` in the validator.
Any locator or contract change therefore requires intentional source-hash
review.

See [MERGE_PLAN.md](MERGE_PLAN.md) for the ordered procedure that was applied.
