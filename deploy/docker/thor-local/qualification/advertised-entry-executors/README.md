# Advertised-entry file executors

This package is a candidate-only qualification tranche for exactly 8 of the 87
advertised-entry gaps in `../advertised-entry-gaps/plan.json`. It runs small,
deterministic fixtures through digest-locked checked-in source bodies or, for the
literal `associated skill` entry, validates the skill's semantic routing contract.

It does **not** update the live acceptance inventory, add official capability IDs,
mark anything `passed_current`, provide runtime evidence, or establish service/model
readiness. Every result is named `observed_match`, has an empty `runtime_evidence`
array, and carries `official_capability_effect: none_candidate_only`.

## Boundary

The executor permits bounded repository reads and stdout. It performs no repository
or temporary-file writes, network access, Docker calls, subprocesses, lifecycle
operations, downloads, or credential access. Source files are SHA-256 checked before
any selected function/class body is compiled. Only explicit AST-allowlisted
definitions run, with in-memory filesystem/video adapters where the original body
would otherwise write.

The fixed denominator is:

- 87 advertised gaps in the source plan
- 8 selected candidate entries in this package
- 79 entries still open

Each case's `evidence_scope` begins with `subset:`. This is intentional: a tiny
deterministic fixture verifies the named behavior it exercises, not every input,
backend, deployment path, or the containing feature family.

## Run

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/advertised-entry-executors/executor.py
```

Run one exact entry:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/advertised-entry-executors/executor.py \
  --case manifest-gap.spatial-ai-utils.01-3d-2d-geometry
```

Run tests:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s \
  deploy/docker/thor-local/qualification/advertised-entry-executors/tests -v
```

`inventory.schema.json` fixes the candidate policy and 87/8/79 denominator.
`result.schema.json` rejects runtime evidence and any official capability effect.

## Deliberately left open

The other 79 plan entries remain open in their source plan. In particular, this
tranche excludes detection mAP because the referenced external nuScenes metric
implementation is not checked in; AWS/GCS helpers because they require external
systems; semantic-label/OpenUSD tools because `pxr` is not locally available; and
the broader combined RGB/depth/video and ground-truth conversions because their
literal paths require filesystem output and/or external codecs/dependencies.

All runtime API, service, browser, audio/codec, media/model, scale, telemetry,
warehouse-workflow, and external-optional entries also remain open. A source file,
family-level lane result, or this package's candidate observation cannot close them.
