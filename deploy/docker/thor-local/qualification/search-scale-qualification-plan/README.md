# Thor search-scale qualification plan

This isolated package compiles the future, Warehouse-free qualification work
for the two still-open advertised Search scale gaps:

- `configuration up to 100 streams`;
- `16 concurrent 1080p streams tested by NVIDIA`.

It does not execute either claim. The default command reads raw-digest-locked
repository contracts and prints an inert plan. It has no network, Docker,
subprocess, credential, media-generation, service-lifecycle, or file-write
surface and adds no runtime evidence.

## Workload denominator

The progressive lane is exactly `2 -> 4 -> 8 -> 16`. Each phase must pass and
complete exact-owned cleanup before the next phase may begin. The 100-stream
workload is deliberately separate, requires a new explicit operator approval,
and cannot inherit a pass from the progressive lane. Any attempted 100-stream
receipt, including a failed attempt, is admissible only after the complete
2/4/8/16 lane passed and cleaned up.

All 130 planned stream instances refer to one future operator-supplied H.264
loop source. Before any future run, that source must be admitted as an absolute
regular non-symlink file outside the repository, probed as H.264, and locked by
SHA-256. No video is included or generated here, and the NVIDIA Warehouse
sample is forbidden. Each planned stream, sensor, publisher, and document scope
has a distinct run-bound identity—520 unique owned resource names in total.

The 16-stream claim is eligible only when the future input is H.264 at exactly
1920x1080 and all sixteen per-stream correctness, latency, resource, abort, and
cleanup records pass. A NVIDIA reference row, `NUM_STREAMS=16`, or a lower
phase does not prove it. The separate 100-stream claim likewise requires all
100 future runtime records and cleanup proofs; `WDM_WL_THRESHOLD: 100` or
configuration rendering alone is insufficient.

Every passing stream must sustain at least `1.0` average FPS. Maximum accepted
latencies are 120 seconds for agent add, 40 seconds for DeepStream activation,
120 seconds for first embedding, and 5 seconds for the search query. These
finite gates are contract fields and are repeated in each compiled workload.

## Safety and cleanup gates

The plan carries forward the existing bounded check's 3 GiB
`MemAvailable` floor (`3145728` KiB) and nine-service health set. Every future
phase also requires all planned publishers and DeepStream sources to remain
active and permits zero failed streams or degraded services. A floor breach
must abort immediately and can never advance to the next phase.

Cleanup is restricted to the exact phase-owned names. A future receipt must
prove successful agent deletion, VIOS and DeepStream absence, zero matching
embedding documents, and stopped publishers for every stream. Broad index,
stack, or pre-existing resource cleanup is forbidden.

## Commands

From the repository root, print the complete inert plan:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/search-scale-qualification-plan/plan.py
```

Run the short static check:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/search-scale-qualification-plan/plan.py \
  --check
```

Run the package tests without cache or bytecode writes:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/search-scale-qualification-plan/tests
```

There is intentionally no `execute`, `deploy`, `generate`, or `cleanup`
subcommand.

## Locked predecessors and evidence contract

`contract.json` raw-locks the existing `thor-capacity-check.sh` and its static
test as behavioral predecessors; the Search profile environment, Compose,
perception, SDRC threshold, and resource-identity contracts; and both open gap
oracles plus their nonadvancing Wave 7 source audit. The older live checker
proved only a bounded 1-to-2 stream run. This package reuses its admission,
measurement, and owned-cleanup semantics but never treats that result as scale
proof for these new workloads.

`evidence.schema.json` is a strict schema for a future collector's one input
record, a contiguous 2/4/8/16 receipt prefix, and an optional separate
100-stream receipt.
A failed progressive phase must be the final recorded phase, and the 16-stream
claim requires all four successful phases. The 100-stream receipt carries its
own distinct run ID and explicit authorization ID and may not overlap any
progressive phase. It is eligible only after all four progressive phases pass,
and its start timestamp may not precede phase 16's completion. The schema also
covers per-stream correctness, thresholded FPS and four latencies, resource
samples, abort state, cleanup, and claim decisions. Every phase has a stable
run-bound evidence ID; qualified claim ID lists must exactly equal the phases
that support the claim rather than merely being nonempty.
`plan.py` additionally checks run-bound unique identities, input-digest
equality, progression, floor arithmetic, claim-decision coupling, and the
1920x1080 gate in memory. It does not collect or write such evidence.

Both official gaps therefore remain `open_unexecuted`.
