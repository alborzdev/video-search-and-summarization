# Spatial AI advertised-entry static contract

This package machine-locks the exact eight `spatial-ai-utils` advertised
entries, their proposed canonical capability and oracle identities, their
conservative Thor states, and the checked-in source files that implement each
surface.

Each oracle identity is exactly `oracle.{full capability id}`; the numeric
entry prefix is never used as a shortened alias.

It proves only source wiring:

- entries `00` through `06` are represented by local checked-in implementations
  and may be described as `wired/not_qualified` in an
  `alternate_local_lane`;
- entry `07`, AWS/GCS validation, is an `external_optional/not_applicable`
  provider boundary;
- all seven offline-tool oracles remain `open_unexecuted`, the provider oracle
  remains `external_boundary_unexecuted`, and runtime evidence is empty.

The executor validates the live manifest literals by exact JSON pointer, checks
34 regular non-symlink repository files by SHA-256, parses Python sources for
the required top-level functions/classes, and checks reviewed text fragments.
It never imports or executes product code.

## Run

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/spatial-ai-entry-static-contract/executor.py \
  --check

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -v \
  -s deploy/docker/thor-local/qualification/spatial-ai-entry-static-contract/tests
```

## Safety and non-claims

The package performs bounded repository reads and writes only its JSON result to
stdout. It has no network, Docker, subprocess, credential, download, service
lifecycle, model, dataset, or Warehouse-sample path. It does not edit the
manifest, capability ledger, oracle registry, advertised-gap plan, runtime-lane
plan, acceptance inventory, or unified wrapper.

Source presence does not establish that the production evaluators, OpenCV
codecs, file-producing CLIs, optional dependencies, or external object stores
worked. Separate capability-bound execution evidence is required before any
oracle or `runtime_state` can advance.
