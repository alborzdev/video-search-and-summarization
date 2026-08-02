# Evidence

This evidence is static only. No Docker, network, host mutation, model download,
service start, runtime qualification, or Warehouse sample action was performed
to build or verify this package.

## Locked denominator

- Selected set: `thor-vss-3.2.1-metadata-500-staged`
- Total selected oracles: 500
- Candidate suffix: indices 289 through 499, exactly 211 rows
- Candidate origin: `candidate_successor_planning_only`
- Candidate order canonical SHA-256:
  `1c0cc33efa1aa6283e467e5fc78bbed8b4cbe8ff23fdbf6db3190144996a3ef9`
- Candidate rows canonical SHA-256:
  `8cc136ea78c7395c534db0c8601b4881ac7982a70e6c43218a6d7cc20b6ef5b4`
- Workload payload SHA-256:
  `0e8512e64399af7d8acc0c7136efbd52da4ebf9119ad0826859e6fce6906d847`
- Protocol-v2 payload SHA-256:
  `65715e2ebfbe164ae38a6b20ca7dc23b6f3a65aaa9dd1632bdda746c4c929f24`
- Compiled mapping-records canonical SHA-256:
  `93791e8b9d7b8ec3368ba78c1f55217498260bdb1c3f9777f0d3f6e5ab11c60c`

`mapping.json` records raw SHA-256 locks for all 12 inputs: the Metadata500
selector and schema, selected descriptor and schema, post-state oracle registry
and schema, generic approval-bundle contract and schema, workload registry and
schema, and protocol-v2 candidate registry and schema. The compiler rejects any
source-lock, selected-set, denominator, order, row, binding, or policy drift.

## Classification evidence

The compiled state counts are exactly 206 mapped, 3 static non-activating, 1
unmapped contract conflict, and 1 unmapped scope gap. Direct-leaf counts sum to
206 and are fixed at profile 184, MV3DT 9, external 4, native audio 3, ASR 2,
Sparse4D 2, Search100 1, and progressive search 1.

The compiler recognizes only reviewed deterministic exception IDs. All other
runtime candidates default to `profile-lifecycle`. It asserts the exact
Warehouse/Sparse4D conflicting title, surface, and dependency before producing
the conflict row, and it records the Sparse4D bundle only as a suggestion. It
does not convert that row to mapped status.

Dependency closure is descriptive and unresolved. The compiler calculates it
only from the existing generic approval contract and fails closed when an
unknown bundle or dependency appears. Native-audio and ASR-transcript leaves are
separate, and external rows preserve their non-local qualification state.

## Non-activation evidence

The strict schema and compiler require all of the following totals to remain
zero:

- receipts present
- approvals granted
- admitted candidates
- executable candidates
- invented commands
- invented action/flag vectors
- invented service roles
- invented profile IDs
- invented Compose paths

Per-candidate evidence arrays are empty, readiness booleans are false, operator
approval remains unmet, fixture materialization is absent, and executor and
collector fields remain absent. The policy excludes the Warehouse sample and
sets required cloud inference to false.

## Verification

The focused suite covers exact counts and hashes, deterministic reproduction,
schema strictness, source drift, candidate reordering/deletion/promotion,
binding drift, approval inheritance, silent conflict remapping, forbidden
action fields, forged approval/readiness/evidence, Warehouse activation, native
audio transcript overclaim, and external-to-local qualification overclaim.

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider deploy/docker/thor-local/qualification/candidate-approval-mapping-successor/tests
PYTHONDONTWRITEBYTECODE=1 python3 deploy/docker/thor-local/qualification/candidate-approval-mapping-successor/compiler.py --check
```
