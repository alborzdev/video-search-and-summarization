# Wave 3 planning-requirement source executors

This isolated package audits all 84 planning requirements that remained open after
the first 26 static bindings. It selects six new, non-overlapping requirements whose
complete declared contract can be compared directly with immutable checked-in source.

The package is deliberately nonadvancing:

- it does not edit `acceptance_inventory.json` or capability oracles;
- it does not add runtime evidence;
- it performs no network, Docker, subprocess, credential, download, or lifecycle work;
- all inputs are exact requirement, capability, contract, and source SHA-256 locks;
- its output is candidate evidence only.

Run it with:

```bash
python deploy/docker/thor-local/qualification/planning-requirement-executors-wave3/executor.py --json
pytest -q deploy/docker/thor-local/qualification/planning-requirement-executors-wave3/tests
```

The expected deterministic result is six cases: five `observed_match` and one
`observed_mismatch`. The mismatch is intentional and unreconciled: the planning
contract says both missing and unsupported search-upload Content-Type failures use
HTTP 400, while the locked implementation uses HTTP 400 for missing and HTTP 415 for
unsupported media types.

The result also emits a machine-checkable 84-row audit. The other 78 requirements stay
open because they require unmaterialized fixtures, custom media, runtime/external
state, an existing static lane rather than a new case, or complete independent source
semantics that are not available in a bounded checked-in artifact.
