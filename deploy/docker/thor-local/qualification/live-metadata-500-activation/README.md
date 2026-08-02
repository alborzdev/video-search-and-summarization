# Metadata-500 activation projection

This isolated package proves and continuously verifies the metadata-default
activation; it never applies the transition itself.
It contains exact regular-file byte snapshots of the pre-activation selector
and staged Metadata-500 descriptor. The compiler projects exclusively from
those immutable package snapshots: descriptor `validation_only` to
`live_ready`, then selector default 289 to Metadata-500 and its new exact hash.
Re-running the package therefore does not depend on canonical files retaining
their pre-activation bytes.

The compiler validates the projected selector and descriptor with the real
metadata-set resolver in a temporary regular-file repository. It then passes
the resolved snapshot through the authoritative atomic bundle verifier. The
result is 500 capabilities, 500 ordered v2 oracles, 55 feature families, 126
sources, and 47 discrepancies, with zero candidate evidence or executor-ready
rows.

The compiler separately inspects the canonical selector/descriptor pair and
accepts exactly two states: both exact pre-activation hashes, or both exact
projected/applied hashes. Either mixed direction and every unknown hash are
rejected. The observed state appears only in CLI output, never in generated
artifacts, so descriptor, selector, receipt, and schema bytes are identical in
both accepted states.

The compiler does not edit the canonical selector, either checked descriptor,
the qualification wrapper, or the four fixed legacy metadata files. The
reviewed canonical pair is now in the exact applied state. This does not make
any runtime capability ready or passed. The optional Warehouse sample bundle
remains excluded.

From the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/live-metadata-500-activation/compiler.py \
  --check

PYTHONDONTWRITEBYTECODE=1 pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/live-metadata-500-activation/tests/test_compiler.py

ruff check \
  deploy/docker/thor-local/qualification/live-metadata-500-activation/compiler.py \
  deploy/docker/thor-local/qualification/live-metadata-500-activation/tests/test_compiler.py
```

`--write` regenerates only the projected descriptor, projected selector,
activation receipt, and exact receipt schema inside this directory. The two
pre-activation snapshots are immutable inputs and are never rewritten. No
service, host, Docker, network, model, download, runtime, or Warehouse action
occurs.

## Remaining boundary

This is an applied metadata-control transaction, not runtime qualification.
The projected descriptor and selector are installed together at their
canonical paths, and the compiler reports the exact `applied` state. The
receipt transition journal retains both canonical paths, exact pre/applied
pairs, and rollback hashes. This compiler never performs the transition;
partial activation remains forbidden.
