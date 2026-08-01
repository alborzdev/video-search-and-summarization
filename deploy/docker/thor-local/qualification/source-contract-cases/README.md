# Source-contract static executor tranche

This package supplies sixteen bounded executors for live planning requirements
that remain unmaterialized. It reads only checked-in repository files. It does
not use Docker, the network, credentials, subprocesses, environment mutation,
downloads, or the optional Warehouse sample bundle.

The tranche is deliberately isolated. `materialized: true` and
`executor_ready: true` describe these candidate executors only. The live
acceptance inventory and official capability ledger remain false/false, every
`runtime_evidence` list remains empty, and no result can advance a capability
or mark it `passed_current`.

## Scope

- Seven reference-performance contracts verify their transcription fixture,
  its `reference_only: true` boundary, and `thor_results: false`. They do not
  claim a Thor benchmark run.
- Alert parser, behavior dynamic configuration, RT-CV Compose, Video Analytics
  bootstrap, ELK ILM, monitoring, mixed release tags, and VIOS module surfaces
  are checked against digest-locked implementation/configuration files.
- The nvStreamer case compares selected official defaults to the checked-in
  local VIOS config and intentionally reports the four current Thor override
  differences as `observed_mismatch`.

## Commands

```bash
python3 deploy/docker/thor-local/qualification/source-contract-cases/executor.py validate
python3 deploy/docker/thor-local/qualification/source-contract-cases/executor.py plan
python3 deploy/docker/thor-local/qualification/source-contract-cases/executor.py run-all
python3 -m unittest discover -s deploy/docker/thor-local/qualification/source-contract-cases/tests -v
```

The executor fails closed on planning-payload drift, source-digest drift,
partial source-lock coverage, duplicate JSON keys, symlinks, path escape,
source changes during execution, or any file/byte/deadline bound violation.
