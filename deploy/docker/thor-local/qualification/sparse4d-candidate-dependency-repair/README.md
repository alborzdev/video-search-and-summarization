# Sparse4D candidate dependency repair

This isolated package records one fail-closed planning correction for
`manifest-entry.warehouse-3d-and-mv3dt.00-sparse4d-3d-warehouse` without
rewriting the selected Metadata-500 files.

The selected candidate advertises `Sparse4D 3D warehouse`, points to the
official `warehouse-3d-app.yml`, and explicitly rejects successful MV3DT
behavior as proof. Its checked dependency nevertheless names
`runtime.warehouse.profile-mv3dt-pipeline`, whose exact ledger contract is the
RT-DETR + MV3DT + MQTT lane. The same selected ledger contains the authoritative
`runtime.warehouse.profile-3d-sparse4d-pipeline` contract at index 267 with
`perception=Sparse4D`, synchronized camera timestamps, and `mdx-bev` output.

`repair.json` therefore replaces only this planning dependency:

```text
runtime.warehouse.profile-mv3dt-pipeline
  -> runtime.warehouse.profile-3d-sparse4d-pipeline
```

The before and after candidate records are canonical-hash-bound, and the
compiler proves they differ only at
`contract.dependency_capability_ids`. The checked source and Thor lane also bind
the static service identity: Compose service `perception-3d`, base service
`perception`, container `vss-rtvi-cv`, Thor profile `bp_wh_redis_3d`,
`MODE=3d`, and model family `sparse4d-warehouse`.

## Boundary

This is an additive planning overlay. It does not mutate the selected metadata
set, change the candidate's `not_qualified` runtime state, add evidence, make a
fixture or executor ready, satisfy the unmet operator gate, create a receipt,
grant approval, or run a service. The static service identity is not an
executable service-role binding.

The predecessor approval mapping remains raw-locked as an explicit contract
conflict. This repair selects `sparse4d-custom-data-models` only as the correct
approval-classification leaf. That bundle and all of its dependencies remain
unresolved until separate exact receipts exist. The Warehouse sample bundle is
excluded; operator-owned four-camera data remains only a future gated input.

## Check

From the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/sparse4d-candidate-dependency-repair/compiler.py \
  --check

PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/sparse4d-candidate-dependency-repair/tests

ruff check \
  deploy/docker/thor-local/qualification/sparse4d-candidate-dependency-repair/compiler.py \
  deploy/docker/thor-local/qualification/sparse4d-candidate-dependency-repair/tests/test_compiler.py
```

`--emit` prints the deterministic artifact to standard output. There is no
write, apply, receipt-consumption, or execution mode.
