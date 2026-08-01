# Planning Requirement Executors — Wave 7

This isolated package audits the exact 60 live-open planning requirements left after Wave 6 and records six additional, disjoint static source subsets:

- three preserved negative/known-issue contracts;
- two configuration implementation subsets;
- one NvSchema consumer/protocol subset.

It is deliberately not runtime qualification. A successful result does not materialize a fixture, make an oracle executor-ready, add runtime evidence, or advance live acceptance. All six planning requirements and their capability oracles remain open. The warehouse sample bundle is excluded.

Run the read-only checker from the repository root:

```bash
python deploy/docker/thor-local/qualification/planning-requirement-executors-wave7/executor.py --json
```

Run its tests:

```bash
pytest -q deploy/docker/thor-local/qualification/planning-requirement-executors-wave7/tests
```

The executor fail-closes on drift in its inventory and schemas, nine predecessor/live-ledger files, exact predecessor and remainder sets, requirement/capability/contract/oracle bindings, or any source digest/token assertion. It performs no network, Docker, subprocess, lifecycle, credential, download, or write action.
