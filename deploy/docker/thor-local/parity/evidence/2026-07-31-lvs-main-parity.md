# LVS upstream-main semantic parity on Thor — 2026-07-31

## Outcome

The official VSS GA remains 3.2.1. Current upstream `main` adds one LVS behavior
after that image release: `GET /files` now accepts the `Purpose` enum rather
than an unconstrained string, so an invalid purpose must fail validation with
HTTP 422. The Thor LVS derivative now applies that exact source change to the
3.2.1 image during build.

This is source/build evidence, not a live 422 result. The unified stack remains
stopped for the existing memory/lifecycle gate, so the new semantic runtime
probe is pending.

## Fail-closed derivative

`patch_lvs_files_purpose.py` requires exactly one copy of the reviewed old
source block, performs the exact upstream replacement, parses the result with
Python's AST, writes atomically while preserving mode, and rejects a symlink
target. Missing or duplicate source patterns fail the image build.

The focused tests cover exact replacement, missing/duplicate rejection,
atomic mode preservation, and symlink refusal. The derivative rebuilt with
networking disabled:

```text
image cti-vss-video-summarization:thor-local
ID    sha256:3ab296357e2ad5a885b56798ef62e31ac875c57d1edc77fe7bab473e8e1184bb
OS    linux
arch  arm64
size  366430743 bytes
```

`runtime_inventory.json` adds a bounded GET-only semantic probe for
`/v1/files?purpose=invalid`, expecting exactly 422. Query keys and values are
strictly bounded; report output records only query key names, never values.
Ambient proxies and redirects remain disabled.

## Reproduction

```bash
python3 -m unittest \
  deploy/docker/thor-local/qualification/tests/test_lvs_files_purpose_patch.py \
  deploy/docker/thor-local/qualification/tests/test_runtime.py
docker build --network=none --pull=false \
  -f deploy/docker/thor-local/Dockerfile.video-summarization \
  -t cti-vss-video-summarization:thor-local .
deploy/docker/scripts/thor-local.sh qualify --tier contract
```

After an operator-approved stack start, the read-only runtime tier must return
HTTP 422 for this probe before this upstream-main behavior can be promoted to
current runtime evidence.
