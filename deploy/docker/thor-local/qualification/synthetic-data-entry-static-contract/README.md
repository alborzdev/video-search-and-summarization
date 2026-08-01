# Synthetic-data advertised-entry static contract

This package provides a strict, networkless source-wiring qualification for all
four `synthetic-data-tools` advertised entries:

1. `semantic label helpers`
2. `dataset checks`
3. `RGB/depth/video conversion`
4. `ground-truth conversion`

It binds the exact canonical capability and full-slug oracle IDs already
checked into the parity ledgers. Every entry remains `kind=tooling`,
`acceptance_class=alternate_local_lane`, `thor_state=wired`, and
`runtime_state=not_qualified`; every oracle remains `open_unexecuted` with an
empty evidence list.

## What this package proves

The executor reads and hashes checked-in files, parses Python source with the
standard-library AST, checks required source fragments and CLI surfaces, and
verifies the canonical manifest/capability/oracle cross-maps. The exact direct
entry denominator is 18 unique source controls: 3 semantic-helper files, 10
dataset-check files, 3 conversion files, and 2 ground-truth files.

The ARM64 boundary is also locked and parsed:

- Linux aarch64, Python 3.10.20, and OpenUSD 26.05;
- 178 checksum-fragmented conda artifacts;
- 21 exact pip requirements derived from upstream by replacing
  `usd-core==26.5` with the equivalent conda OpenUSD package;
- 21 exact wheel filenames and byte digests; and
- the SHA-256-locked Linux aarch64 Miniforge bootstrap.

The ground-truth entry specifically locks the current converter digest
`4d81551c3a143f52f3fa4bfdc52f1af6aa01fac864d250a9a3f2547dfdaeef9f`,
the `--skip-visualization` conversion-only CLI, its calibration boundary, and
its temporary alias workspace, which leaves the input tree unmodified. The
contract also locks these four deterministic output names:

- `ground_truth.json`
- `bounding_boxes.json`
- `rotation_keys_with_rot.json`
- `corners_comparison_dict.json`

## What this package does not prove

This is source wiring only. It does not import product modules, build the ARM64
environment, run an SDG tool, invoke native codecs, create a fixture, inspect a
host service, or establish semantic output correctness. It cannot create
runtime evidence, promote an oracle, mutate a canonical ledger, or mark an
entry `passed_current`.

The family-level historical `passed_current` observation in `manifest.json`
is not inherited by these new entry-level contracts. Each entry still needs a
target-bound execution of the real tool path on digest-bound tiny custom data,
including output digests, semantic assertions, and adjacent-negative cases.

The optional NVIDIA Warehouse sample bundle is excluded. No sample asset,
download, or path is part of this contract or a prerequisite for a future
custom-data oracle.

## Run

From the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/synthetic-data-entry-static-contract/executor.py \
  --check

PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  deploy/docker/thor-local/qualification/synthetic-data-entry-static-contract/tests
```

The executor performs two independent read-only observations, requires
byte-identical canonical results, validates its result against the strict
Draft 2020-12 schema, and writes canonical JSON only to stdout.
