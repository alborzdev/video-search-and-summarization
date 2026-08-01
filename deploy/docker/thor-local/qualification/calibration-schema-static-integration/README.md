# Calibration-schema fourth static successor

This package integrates the existing provider-free calibration-schema executor
as exactly one non-advancing planning-executor binding for
`calibration.schema.vss-json`.

The predecessor is the checked-in third LVS static successor. Its integrator,
receipt, contract digest, and all four canonical output digests are locked and
replayed. The narrow compiler/schema evolution is required because
`calibration-schema-static` is owned by a `global_acceptance_vector`, not by one
capability. At the third-successor state that new branch is verified to be
output-neutral.

The fourth successor changes only:

- planning requirement `calibration-schema-static`, from open to a materialized
  static-executor binding; and
- oracle `oracle.calibration.schema.vss-json`, by adding the corresponding
  non-advancing binding and static-subset blockers.

The vector owner and all seven applicable record IDs remain unchanged. The
case targets only `calibration.schema.vss-json`; the other six IDs are carried
as the exact ordered `uncovered_applicable_record_ids` partition and receive no
binding from this requirement.

## Commands

From the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/calibration-schema-static-integration/integrate_live.py \
  plan

PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/calibration-schema-static-integration/tests
```

`plan` and `validate-predecessor` are read-only. `write` deterministically
writes only the acceptance inventory, generated capability-oracle plan, and
this package's integration receipt. It does not change the official capability
ledger or manifest.

The advertised executor invocation remains runnable after integration. Mutable
canonical documents are validated through exact normalization of only the
reviewed integration fields; the executor then reads back every final binding
identity and digest from current package files and the immutable execution
receipt.

## Boundary

This is deterministic static evidence, not runtime evidence. It does not start
containers, call a network, invoke subprocesses, use the Warehouse sample,
qualify AMC/VGGT or physical installation, advance a capability runtime state,
or mark an oracle `passed_current`.
