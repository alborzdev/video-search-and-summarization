# Deterministic file-only executor cases

This isolated candidate package implements checks for 10 of the 110 Wave 3
planning requirements as bounded, runnable checks against checked-in files. The
candidate cases are genuinely executor-ready: `executor.py run` and `run-all`
evaluate their assertions now, without a network, service, container, model,
sample, or mutable host dependency.

The evidence boundary is deliberately narrow. A match proves only the named
static assertion over the hashed source files. It is not runtime evidence, does
not prove service behavior, and cannot advance a capability to `passed_current`.
The candidate materialization is scoped to this package. The live acceptance
inventory and live capability ledger remain planning-only, with all ten source
requirements still `materialized=false` and `executor_ready=false`. Promoting
those live flags requires a separately reviewed merge into the live acceptance
and oracle paths.

Current deterministic result:

- 10 candidate-materialized cases
- 10 candidate executor-ready cases
- 0 live requirements materialized or executor-ready
- 8 `observed_match`
- 2 `observed_mismatch`
- 0 runtime-evidence records
- 0 capabilities eligible for advancement

The two mismatches are useful candidate findings, not executor failures:

- `protocol.nvschema.protobuf-messages` documents Incident field 7 as
  `analytics`, while `libs/nvschema/protobuf/ext.proto` declares
  `analyticsModule = 7`.
- `configuration.alerts.prompt-vlm-warmup` documents warmup enabled by
  default, while the Thor overlay explicitly sets `VLM_WARMUP_ENABLED: "false"`.

The warmup finding is a local conformance difference already bounded by the
capability's `partial` / `not_qualified` state and gap, so it is not a new
cross-source discrepancy. The Incident field-name finding is a candidate
official-contract-versus-repository discrepancy that needs semantic review
before adding a live discrepancy record.

Run the package:

```bash
python3 deploy/docker/thor-local/qualification/executor-cases/executor.py validate
python3 deploy/docker/thor-local/qualification/executor-cases/executor.py plan
python3 deploy/docker/thor-local/qualification/executor-cases/executor.py run \
  executor-case.vios-effective-upload-limit
python3 deploy/docker/thor-local/qualification/executor-cases/executor.py run-all
python3 -m unittest discover \
  -s deploy/docker/thor-local/qualification/executor-cases/tests \
  -p 'test_executor.py' -v
```

Safety properties are schema-enforced and adversarially tested: repository-path
containment, symlink rejection, duplicate-key rejection, exact planning payload
bindings, a canonical digest over the complete assertion inventory, immutable
source hashing, a 4 MiB / 16-file / 5-second per-case bound,
and the absence of network, Docker, subprocess, or environment-mutation APIs.
The optional Warehouse sample bundle is excluded and no sample marker appears
in the inventory.
