# Request cancellation static rebase successor v1

This additive package qualifies the frozen request-cancellation source tranche without rewriting its eight immutable predecessor packages. It binds eight production files, five cancellation/cleanup tests, the refreshed expected contracts, and the current API/capability ledgers.

Run the fail-closed static compiler:

```bash
python3 deploy/docker/thor-local/qualification/request-cancellation-static-rebase-successor-v1/compiler.py --check
```

The compiler performs no network, Docker, service-lifecycle, or runtime-inference work. It validates the only two allowed static test invocations: an isolated RT-VLM invocation with `--noconftest`, and an LVS invocation using its normal test setup. To run precisely those source-locked invocations separately:

```bash
python3 deploy/docker/thor-local/qualification/request-cancellation-static-rebase-successor-v1/compiler.py --execute-tests
```

The optional executor can launch only the five listed pytest files through those two commands. Its result is not written into the static receipt and cannot promote admission, authorization, executable state, or `passed_current` state.

RT-VLM exposes 28 Thor-local operations. The NVIDIA-documented denominator remains 27; the sole local extension is exact request cancellation at `DELETE /v1/generate_captions/requests/{request_id}`.

Warehouse sample data is excluded. No Warehouse asset is read, downloaded, generated, or required.
