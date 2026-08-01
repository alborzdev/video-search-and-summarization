# Runtime approval-bundle evidence boundary

## Raw-locked inputs

`contract.json` locks 25 current inputs covering:

- read-only loopback runtime inventory and runtime-lane planning;
- host preflight and cgroupfs remediation;
- tiny known-speech fixture generation and the reviewed two-lane audio oracle;
- official Edge readiness/staging;
- local alternate-model and profile lifecycle contracts;
- Search scale, MV3DT, Sparse4D, and external-attestation contracts;
- Wave 7 advertised-entry identities;
- the Thor-local and developer-profile lifecycle scripts.

Any raw-byte change fails compilation and requires review. The audio runtime contract and validator are locked as a pair; native-Omni and local-ASR authorization cannot be merged.
The Search, MV3DT, Sparse4D, and external-attestation contracts and validators
are likewise locked as pairs; each validator pins its own evidence and package
schemas, so receipt semantics cannot drift invisibly between approval review
and execution.

## What the plan establishes

The plan establishes only a deterministic work denominator, separation of approval scopes, dependency precedence, known-versus-unknown transfer sizing, required inputs, blockers, and intended cleanup/rollback boundaries. It records zero approvals. It does not determine whether any bundle is currently necessary, ready, safe to run, or complete.

Read-only inspection precedes host-dependent mutation and staging. Cgroup remediation and downloads have their own acknowledgements. Profile lifecycle precedes runtime workload qualification. The 2/4/8/16 Search scale approval explicitly excludes the separate dependent 100-stream approval. Native-Omni audio semantics and local-ASR transcript qualification likewise require separate authorization IDs and acknowledgements. MV3DT and Sparse4D require operator-owned exact-four custom data; the Warehouse sample is excluded. Sparse4D additionally requires exact RT-DETR, Sparse4D v2.2 ONNX, and finite `(900,11)` anchor admission. External provider work remains independent of local lifecycle work.

## Prohibited inference

Compiler success is not host evidence, approval, lifecycle authorization, runtime evidence, download authorization, credential authorization, or capability admission. It does not replace the exact acknowledgement gates implemented by predecessor tools. It cannot be cited as proof that cgroupfs is configured, capacity is available, artifacts are present, services are healthy, a model was used, cleanup occurred, or an advertised entry passed.
