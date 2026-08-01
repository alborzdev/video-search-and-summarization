# Deterministic file-only executor cases

This package implements checks for 10 of the 110 Wave 3
planning requirements as bounded, runnable checks against checked-in files. The
candidate cases are genuinely executor-ready: `executor.py run` and `run-all`
evaluate their assertions now, without a network, service, container, model,
sample, or mutable host dependency.

The evidence boundary is deliberately narrow. A match proves only the named
static assertion over the hashed source files. It is not runtime evidence, does
not prove service behavior, and cannot advance a capability to `passed_current`.
The exact ten cases form the immutable first successor. The current live
acceptance is a second successor with sixteen additional source-contract
bindings. The original receipt and contract remain byte-for-byte historical
provenance. All related capability oracles remain `planning_index_only`: full
fixtures, runtime executors, collectors, cleanup executors, and runtime
evidence are still absent.

Current deterministic result:

- 10 candidate-materialized cases
- 10 candidate executor-ready cases
- 10 requirements materialized and executor-ready in this historical successor
- 8 `observed_match`
- 2 `observed_mismatch`
- 0 runtime-evidence records
- 0 capabilities eligible for advancement

The two mismatches are useful candidate findings, not executor failures:

- `protocol.nvschema.protobuf-messages` documents Incident field 7 as
  `analytics`, while all three checked-in repository schema copies declare
  `analyticsModule = 7`. Generated bindings and JSON-facing code agree with
  `analyticsModule`; the field tag remains 7, so this is a reviewed
  documentation-to-repository name discrepancy, not evidence of binary wire
  incompatibility and not authority to rename the API.
- `configuration.alerts.prompt-vlm-warmup` documents warmup enabled by
  default. The service implementation also defaults to enabled when the
  variable is unset, while the Thor overlay alone explicitly sets
  `VLM_WARMUP_ENABLED: "false"`. This is an explicit, unqualified Thor
  conformance override, not an official-source discrepancy or missing service
  implementation.

Both semantic decisions are now live, exact discrepancy records applied by the
deterministic `parity/reconciliations/executor-mismatch-review` overlay. The
warmup mismatch remains open until enabled warmup runs successfully on Thor and
the override is removed, or reproducible evidence narrowly justifies it. The
Incident mismatch remains open until binary and Protobuf-JSON round trips are
qualified; the implementation field name stays unchanged.

Run the package:

```bash
python3 deploy/docker/thor-local/qualification/executor-cases/executor.py validate
python3 deploy/docker/thor-local/qualification/executor-cases/executor.py plan
python3 deploy/docker/thor-local/qualification/executor-cases/executor.py run \
  executor-case.vios-effective-upload-limit
python3 deploy/docker/thor-local/qualification/executor-cases/executor.py run-all
python3 deploy/docker/thor-local/qualification/source-contract-integration/integrate_live.py \
  validate-predecessor
python3 -m unittest discover \
  -s deploy/docker/thor-local/qualification/executor-cases/tests \
  -p 'test*.py' -v
```

Safety properties are schema-enforced and adversarially tested: repository-path
containment, symlink rejection, duplicate-key rejection, exact planning payload
bindings, a canonical digest over the complete assertion inventory, immutable
source hashing, a 4 MiB / 16-file / 5-second per-case bound,
and the absence of network, Docker, subprocess, or environment-mutation APIs.
The successor receipt replays the immutable Wave 3 merge and reviewed mismatch
overlay, binds every executor input and live output, and rejects partial or
output-plus-receipt co-tampering.
The optional Warehouse sample bundle is excluded and no sample marker appears
in the inventory.
