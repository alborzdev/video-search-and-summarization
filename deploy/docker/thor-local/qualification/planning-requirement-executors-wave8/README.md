# Planning Requirement Executors — Wave 8

This isolated package audits the exact 54 live-open planning requirements left
after Wave 7. It records six additional, disjoint static negative-contract
subsets covering documented known limitations in LVS, base-profile recovery,
search, and RT-CV.

It is deliberately not runtime qualification. A successful result does not
prove that a limitation occurs, that recovery works, or that a runtime feature
works on Thor. It does not materialize a fixture, make an oracle executor-ready,
add runtime evidence, or advance live acceptance. All six planning requirements
and their capability oracles remain open. The Warehouse sample bundle is
excluded.

Run the read-only checker from the repository root:

```bash
python deploy/docker/thor-local/qualification/planning-requirement-executors-wave8/executor.py --json
```

Run its tests:

```bash
pytest -q deploy/docker/thor-local/qualification/planning-requirement-executors-wave8/tests
```

The executor fail-closes on drift in its inventory and schemas, ten
predecessor/live-ledger files, exact predecessor and remainder sets,
requirement/capability/contract/oracle bindings, or any source digest/token
assertion. It performs no network, Docker, subprocess, lifecycle, credential,
download, or write action.
