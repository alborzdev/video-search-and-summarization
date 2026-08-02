# Candidate approval mapping successor v2

This package is the inert, deterministic successor to the 211-row candidate
approval classification. It preserves 209 predecessor mapping rows exactly and
resolves the two previously explicit classification gaps using separately
reviewed, source-locked packages:

- the Sparse4D contract conflict maps to `sparse4d-custom-data-models` only
  after binding the one-field Sparse4D dependency repair;
- the physical-interface firewall scope gap maps to
  `physical-interface-firewall-configuration`, whose exact closure is only
  `physical-interface-firewall-read-only-inspection` plus the configuration
  leaf.

These are classifications, not approvals. The package contains no receipt
consumer or executor and grants no approval, admission, runtime evidence, host
access, or action authority.

## Check the artifact

Run from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 deploy/docker/thor-local/qualification/candidate-approval-mapping-successor-v2/compiler.py --check
```

The compiler accepts only `--check` and `--emit`. It locks and validates the v1
mapping/schema/compiler, the 16-bundle successor contract/schema/compiler, the
Sparse4D repair/schema/compiler, and the immutable 500-oracle registry/schema.
`--check` requires the checked artifact to equal deterministic compilation and
to use exact sorted JSON bytes.

## Exact post-state

| Classification | Count |
| --- | ---: |
| `mapped` | 208 |
| `static_nonactivating` | 3 |
| `unmapped_contract_conflict` | 0 |
| `unmapped_scope_gap` | 0 |

The exact direct leaves are profile 184, MV3DT 9, external 4, native audio 3,
Sparse4D 3, ASR 2, progressive search 1, Search100 1, firewall configuration 1,
and firewall inspection 0. Candidate bindings remain exactly 60 workload, 23
protocol, and 128 unbound.

Dependency closure remains descriptive and unresolved. It does not inherit
approval. Common host/Docker/cgroup/model/profile links each occur 203 times;
Sparse4D 3, MV3DT 9, native audio 3, ASR 2, tiny fixture 5, progressive search
2, Search100 1, external 4, and both firewall inspection and configuration 1.
The Edge closure remains zero.

## Safety boundary

All 211 rows retain `no_receipt_not_admitted_not_executable`. Totals remain zero
for receipts, approvals, admissions, executable candidates, invented commands,
action/flag vectors, service roles, profile IDs, and Compose paths. Runtime
state/evidence and operator gates in the locked candidate oracles are unchanged.

The Warehouse sample bundle is excluded and required cloud inference is false.
The Sparse4D mapping is only a planning classification over the additive repair;
it does not modify the selected Metadata500 files or qualify the runtime. The
firewall mapping publishes neither a host command nor authorization to inspect
or configure the host.
