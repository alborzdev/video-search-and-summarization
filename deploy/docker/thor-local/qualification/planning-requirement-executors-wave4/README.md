# Wave 4 planning-requirement source executors

This isolated package starts from the exact 78 still-open planning requirements
not previously selected by a source-executor package: 26 requirements have
integrated static-subset bindings and six more were selected by the prior
nonadvancing Wave 3 package. It selects six new, non-overlapping requirements
whose bounded declared contracts can be compared with immutable checked-in
source.

The package is deliberately nonadvancing:

- it does not edit live acceptance, capability, oracle, or runtime-lane ledgers;
- it does not add runtime evidence or promote a requirement;
- it performs no network, Docker, subprocess, credential, download, write, or
  lifecycle action;
- it locks the complete five-file baseline plus every selected planning payload,
  capability, contract, and source file;
- it emits a 78-row audit with canonical planning/capability/contract identities.

Run it with:

```bash
python deploy/docker/thor-local/qualification/planning-requirement-executors-wave4/executor.py --json
pytest -q deploy/docker/thor-local/qualification/planning-requirement-executors-wave4/tests
```

The deterministic result is five `observed_match` cases and one
`observed_mismatch`. The mismatch is intentionally unreconciled: the locked
Alerts capability lists both Cosmos Reason and Qwen VL as examples, while the
locked checked-in Alerts source names Cosmos Reason but contains no Qwen example.
This is source-contract evidence only, never backend availability or runtime
qualification.

The remaining 72 requirements retain explicit classifications. Warehouse sample
data is neither required nor touched; custom-media Warehouse runtime planning
remains open.
