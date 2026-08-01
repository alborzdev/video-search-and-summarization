# Wave 5 planning-requirement Smart City source executors

This isolated package starts from the exact 72 planning requirements that had
not been selected by a predecessor executor package. It selects six coherent
Smart City requirements and compares their complete declared contracts with
immutable checked-in source. It uses the authoritative official capability
ledger because these owners are outside the earlier systems-only candidate.

The package is deliberately nonadvancing: it does not edit live acceptance,
capability, oracle, manifest, runtime-lane, or API ledgers; adds no runtime
evidence; and performs no network, Docker, subprocess, credential, download,
write, or lifecycle action.

```bash
python deploy/docker/thor-local/qualification/planning-requirement-executors-wave5/executor.py --json
pytest -q deploy/docker/thor-local/qualification/planning-requirement-executors-wave5/tests
```

The deterministic result is one `observed_match` and five
`observed_mismatch` cases. Those mismatches preserve the official `bp_smc`
identity, exact Smart City behavior class list, exact verifier resolution and
lookback, operator custom-location workflow, and ROI Refiner dependency where
the checked source is divergent or incomplete. They are not remediations or
runtime failures.

The planning denominator remains 110 total: 26 integrated/materialized and 84
live-open. Prior candidate-only Waves 3/4 selected 12 of those 84; this wave
selects six of the remaining 72, leaving 66 without a candidate executor. All
84 remain live-open because this package promotes nothing.
