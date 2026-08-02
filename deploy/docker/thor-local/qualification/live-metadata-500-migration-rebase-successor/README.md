# Metadata-500 migration rebase successor

This package is an isolated, non-applying successor to
`live-metadata-500-migration`. It preserves that predecessor byte-for-byte and
projects the frozen 500-capability composition into five package members:

- `post-state-official-capabilities.json`
- `post-state-manifest.json`
- `post-state-acceptance-inventory.json`
- `post-state-capability-oracles.json`
- `post-state-capability-oracles.schema.json`

The compiler also produces an exact migration proof and const schema. All seven
generated files are final-chain SHA-256 pinned. The compiler rejects both
`--check` and `--write` before filesystem mutation when any source or expected
output pin is absent or differs from the deterministic result.

## Preservation boundary

`compiler.py` independently locks every file in the predecessor package plus
the current canonical Metadata-500 selector and descriptor. It does not import
the predecessor compiler. Its transactional writer accepts exactly the seven
successor basenames and only when their parent is this package directory. It
stages every member before commit and restores every previously committed
member if a commit fails.

This package never modifies live parity metadata, the predecessor package, the
canonical selector, or metadata-set descriptors. Canonical activation requires
a separately reviewed selector/descriptor rebase successor.

## Validation

Run the static suite without runtime, network, or Docker access:

```bash
python -m pytest -q \
  deploy/docker/thor-local/qualification/live-metadata-500-migration-rebase-successor/tests
```

Verify the checked artifacts with:

```bash
python \
  deploy/docker/thor-local/qualification/live-metadata-500-migration-rebase-successor/compiler.py \
  --check
```

`--write` is a package-local deterministic regeneration operation. It performs
the same exact-pin validation before its transactional commit.
