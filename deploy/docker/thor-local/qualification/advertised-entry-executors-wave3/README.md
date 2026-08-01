# Advertised-entry executors: wave three

This isolated package deterministically checks a third, disjoint subset of 23
advertised-entry gaps. It consumes the exact 87-entry gap plan, digest-locks
both predecessor inventories (8 + 21 entries), selects 23 of the prior 58 open
entries, and leaves 35 without a candidate executor. All 87 remain unpromoted
in live official status.

Every result is candidate-only source-contract evidence. The executor parses
digest-locked Python sources with `ast`, checks exact source/configuration
fragments, and emits explicit false flags for runtime execution, workflow
proof, service readiness, and model availability. It does not mark a
capability `passed_current`, mutate live acceptance/oracle/runtime-lane files,
or qualify a service, model, API workflow, telemetry path, MCP operation, or
Compose deployment on Thor.

## Run

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/advertised-entry-executors-wave3/executor.py
```

List or run exact cases:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/advertised-entry-executors-wave3/executor.py --list

PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/advertised-entry-executors-wave3/executor.py \
  --case manifest-gap.agent-and-mcp-apis.01-health
```

Run the adversarial suite:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s \
  deploy/docker/thor-local/qualification/advertised-entry-executors-wave3/tests \
  -p 'test_*.py' -v
```

## Safety boundary

Network, Docker, subprocesses, credentials, downloads, lifecycle actions, and
filesystem writes are forbidden by policy. Source files are read only through
repository-contained, size-bounded paths. Exact plan, manifest, predecessor,
source-path, and SHA-256 identities are verified before a case adapter runs.

The MV3DT case checks only checked-in Compose service fragments and does not
use or require the optional Warehouse sample bundle. MCP and API cases check
only source/configuration contracts; they do not open a listener or make a
request. Model and tuning cases do not import vLLM, access an endpoint, inspect
artifacts, or imply Thor readiness.

See [EVIDENCE.md](EVIDENCE.md) for the selection and exclusions.
