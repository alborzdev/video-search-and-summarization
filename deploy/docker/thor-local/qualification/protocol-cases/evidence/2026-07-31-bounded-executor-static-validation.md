# Bounded protocol executor — static validation

Date: 2026-07-31

Scope: executor code, admission, schemas, and unit tests only. No service,
container, broker, socket, data plane, lifecycle action, artifact download, or
runtime protocol case was executed.

The default command is plan-only. Activation requires the `execute` subcommand,
an operator-reviewed request, the exact lifecycle/mutation acknowledgement,
admitted targets and resources, and vector/global bounds. Direct clients do not
use proxies or redirects. Protocol-discovered Kafka/ICE endpoints are also
subject to admission. Runtime evidence is content-hash bound and written with
exclusive creation after LIFO cleanup.

Static plan classification:

- activation-ready product protocol: 4;
- activation-ready transport fixture only: 1 (Redis,
  `can_advance_capability=false`);
- blocked: 2 (Agent external server contract; Kafka reversible VSS-triggered
  publication contract).

Kafka deliberately has no self-produce path. A broker roundtrip cannot qualify
VSS NvSchema publication, and a record written to a pre-existing topic cannot
be exactly removed. Redis's self-generated fixture remains a bounded transport
diagnostic only and cannot advance the product capability.

Validation commands:

```text
python3 deploy/docker/thor-local/qualification/protocol-cases/validate_protocol_cases.py
python3 -m unittest discover -s deploy/docker/thor-local/qualification/protocol-cases/tests -v
ruff check deploy/docker/thor-local/qualification/protocol-cases
ruff format --check deploy/docker/thor-local/qualification/protocol-cases/protocol_case_executor.py deploy/docker/thor-local/qualification/protocol-cases/tests/test_protocol_case_executor.py
```

Runtime result: unexecuted.
