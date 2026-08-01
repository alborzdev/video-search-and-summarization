# Prerelease denominator materialization evidence

Date: 2026-08-01

The official remote advertised these exact refs at materialization time:

```text
a34c6b0406bcadd380e4c4dac6ff7e830deb27e5 refs/heads/develop
7732edf8fb38ef896b20f2a0a6a701a4db10dc57 refs/heads/main
708dac2ff071c76971d5cc8cab24f3879e6aac63 refs/tags/nightly-20260801
7640d917047cf7b0fd3085eefb8282754b56bc94 refs/tags/v3.2.1^{}
```

The clean `--filter=blob:none` bare metadata materialization through
`nightly-20260801` measured:

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

The same-day refresh fetched the one new develop commit
`a34c6b0406bcadd380e4c4dac6ff7e830deb27e5` into the existing local Git
metadata and regenerated the denominator with `GIT_NO_LAZY_FETCH=1`. That
commit changes six paths and adds the prerelease NemoClaw Hermes runtime
workflow. No clean-pack byte measurement is claimed for this incremental
refresh.

An earlier rename-similarity probe was rejected because it caused the promisor
remote to lazily fetch blobs. Its exact temporary high-water measurements were
89,532,871 directory bytes and 83,841,024 aggregate `.pack` bytes. No result
from blob similarity detection is used in the lock. That temporary repository
was deleted after these measurements; the accepted generator forces
`GIT_NO_LAZY_FETCH=1` and uses `--no-renames`.

Locked graph and record accounting:

```text
merge base:                   7640d917047cf7b0fd3085eefb8282754b56bc94
develop tip:                  a34c6b0406bcadd380e4c4dac6ff7e830deb27e5
stable main:                  7732edf8fb38ef896b20f2a0a6a701a4db10dc57
develop-side commits:         499
main-only exceptions:         2
develop path/status records:  109,058
main-only path/status records: 2
unique paths:                 59,917
statuses:                     A=39,340 D=57,058 M=12,662
```

Core digests:

```text
develop sequence SHA-256: 609ea564effe9c1bbebdd9e538bf546d843990d499757fc54826af77efabda0a
main sequence SHA-256:    601be158b38bcb039f3fa4e09487b4541fba9c576f3d257963724448636bd889
path JSONL SHA-256:       137329738d0a2d2bcd7dc9c30ae9c6c21bfb36f38d81126491ba5bc8bbe8685e
path gzip SHA-256:        3e4010f2264396a7b86f4932b3126463bab5b66c1966d86a6f44107d275b4118
```

This is static source-denominator evidence only. No model artifact, container,
runtime service, Docker lifecycle, credential, Warehouse sample bundle, or
cloud inference endpoint was touched or qualified.
