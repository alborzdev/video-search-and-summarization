# Systems Search/LVS boundary static executor

This isolated package executes the strongest provider-free subset of exactly three open `systems` planning requirements:

- `systems-search-content-type` → `behavior.search-upload.content-type`
- `systems-lvs-queue` → `runtime.lvs.single-request-queue`
- `systems-lvs-formats` → `runtime.lvs.supported-formats`

The executor imports the checked-in deprecated Search upload route with a deterministic in-memory HTTP-client fake, compiles the exact checked-in `ViaStreamHandler._trigger_query` AST with a deterministic fake RTVI pipeline, and reads the exact default upload-validator expression from the checked-in UI. Canonical planning rows, capability rows, oracles, product sources, and relevant product tests are all digest-locked.

The result deliberately exposes current gaps:

- missing Search `Content-Type` returns the advertised `400`, but an unsupported type returns `415` while the canonical contract says `400` for both;
- two bounded concurrent calls enter the LVS handler's fake downstream in `processing` state, so this source-level layer does not itself demonstrate the advertised one-active/one-queued behavior;
- the default UI admits MP4/MKV, while AVI/MOV/WebM from the five-format advertised denominator remain outside that entry surface and require live decode/summarization evidence.

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 deploy/docker/thor-local/qualification/systems-search-lvs-boundary-static-executor/executor.py --json
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider deploy/docker/thor-local/qualification/systems-search-lvs-boundary-static-executor/tests
```

The only success result is `candidate_executable_mismatch_non_advancing`. It is not runtime service evidence and cannot change any canonical state. The executor performs no network access, subprocesses, Docker operations, downloads, service lifecycle actions, model calls, filesystem writes, or Warehouse sample use.
