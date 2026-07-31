# Capability-specific acceptance-oracle review

Date: 2026-07-31

Scope: static, non-mutating review of every claim in
`parity/official-capabilities.json`. No container, service, model, network
endpoint, or external integration was started, stopped, queried, or changed.

The expanded planning index contains 131 unique capability-bound records across
all seven proposed modes: static, config, runtime, API, protocol, model, and
deploy. It uses 103 profiles, with exact contract-leaf assertions and unique
scenario, prospective fixture, namespace, and mutation-allowlist identities.
All 131 entries are `planning_index_only`; zero are `executor_ready`. Of those,
115 local lanes are `open_unexecuted` and 16 external boundaries are
`external_boundary_unexecuted`. The prose actions, expected observations, and
cleanup outlines are not executable acceptance and are not evidence that a
fixture exists, a semantic assertion ran, or cleanup completed.

The NVIDIA warehouse sample bundle is excluded from every fixture and
execution bound. Calibration and media oracles instead require bounded custom
data generated locally or supplied by the operator, so the custom-data
warehouse contract remains eligible for future acceptance.

The seven protocol records are cross-linked to the exact static protocol-case
contract at whole-file SHA-256
`28cbcabef1bf1f3ed41ebf398de3e2387548b2ec6de72b5a51d8c5f30a59a7a6`
and internal set SHA-256
`3089ca096b4f86bbe54cce37027acf1769adff8bd1b4adf8a2018983c72ddb21`.
Each record also binds its case, positive/negative vector IDs, target commit,
case hash, and exact source content/blob hashes. This remains static planning;
the protocol cases are unexecuted.

Reproduction:

```bash
python3 deploy/docker/thor-local/parity/capability_oracles.py --report
python3 -m unittest discover \
  -s deploy/docker/thor-local/parity/tests \
  -p 'test_capability_oracles.py' -v
ruff check \
  deploy/docker/thor-local/parity/capability_oracles.py \
  deploy/docker/thor-local/parity/tests/test_capability_oracles.py
```

Observed result at the review point: both validators passed; all 51 focused
oracle/official-capability tests passed; Ruff and the unified static milestone
wrapper passed. The compiler is count- and source-independent: adding an official
capability makes validation fail closed until its newly compiled oracle is
reviewed and the expanded JSON is regenerated. Counts in this note describe
the 131-claim review point and are not a permanent denominator.
