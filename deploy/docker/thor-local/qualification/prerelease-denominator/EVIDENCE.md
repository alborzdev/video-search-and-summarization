# Prerelease denominator materialization evidence

Date: 2026-08-01

The official remote advertised these exact refs at materialization time:

```text
708dac2ff071c76971d5cc8cab24f3879e6aac63 refs/heads/develop
7732edf8fb38ef896b20f2a0a6a701a4db10dc57 refs/heads/main
708dac2ff071c76971d5cc8cab24f3879e6aac63 refs/tags/nightly-20260801
7640d917047cf7b0fd3085eefb8282754b56bc94 refs/tags/v3.2.1^{}
```

The clean `--filter=blob:none` bare metadata materialization measured:

```text
directory before fetch:       26,372 bytes
directory after fetch:     6,047,219 bytes
directory growth:          6,020,847 bytes
received .pack payload:    5,206,966 bytes
post no-lazy diff probe:    6,047,219 bytes
```

The pack payload is the exact received Git pack-file size on disk; transport
framing overhead is not observable as payload and is not claimed. The checked-
in package measured 1,215,578 bytes before tests and temporary bytecode cleanup.

An earlier rename-similarity probe was rejected because it caused the promisor
remote to lazily fetch blobs. Its exact temporary high-water measurements were
89,532,871 directory bytes and 83,841,024 aggregate `.pack` bytes. No result
from blob similarity detection is used in the lock. That temporary repository
was deleted after these measurements; the accepted generator forces
`GIT_NO_LAZY_FETCH=1` and uses `--no-renames`.

Locked graph and record accounting:

```text
merge base:                   7640d917047cf7b0fd3085eefb8282754b56bc94
develop tip:                  708dac2ff071c76971d5cc8cab24f3879e6aac63
stable main:                  7732edf8fb38ef896b20f2a0a6a701a4db10dc57
develop-side commits:         498
main-only exceptions:         2
develop path/status records:  109,052
main-only path/status records: 2
unique paths:                 59,914
statuses:                     A=39,339 D=57,058 M=12,657
```

Core digests:

```text
develop sequence SHA-256: 71392342507ca18fc086b5c629c39f1f33c8c215e888a2af51516df6779c0344
main sequence SHA-256:    601be158b38bcb039f3fa4e09487b4541fba9c576f3d257963724448636bd889
path JSONL SHA-256:       afd9f9717184526031c7ae4dc820eb78d260b6525f56c0f2a7dc6e344051d262
path gzip SHA-256:        f8fbc47104c0192727226d32b19180c27f839c83fda8ecc01028425605487ef7
```

This is static source-denominator evidence only. No model artifact, container,
runtime service, Docker lifecycle, credential, Warehouse sample bundle, or
cloud inference endpoint was touched or qualified.
