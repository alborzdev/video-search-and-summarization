# Candidate-only static qualification tranche

This isolated package describes the first 24 static qualification cases selected
from the live inventory and Wave 3 Calibration/Warehouse candidate. It is not
connected to the live oracle inventory, acceptance wrapper, capability ledger, or
runtime evidence directory.

The package is deliberately inert:

- every case is `candidate_only`, `executor_ready: false`, and
  `can_advance_capability: false`;
- network, Docker, subprocess lifecycle, service mutation, and the optional
  Warehouse sample bundle are forbidden;
- one inspection reads at most 64 regular non-symlink files and 8 MiB, has a
  10-second deadline, and owns only one mode-0700 temporary directory;
- only `observed_match`, `observed_mismatch`, `blocked`, and `not_applicable`
  are valid outcomes;
- stdout observations are not persisted as runtime evidence.

The runtime-evidence schema is hash-bound as a shape reference so later
integration can preserve naming and provenance conventions. This package does
not instantiate that schema and cannot advance any capability.

## Commands

Validate and print the inert plan:

```bash
python3 deploy/docker/thor-local/qualification/static-cases/static_case_executor.py validate
python3 deploy/docker/thor-local/qualification/static-cases/static_case_executor.py plan
```

Inspect one case without activation:

```bash
python3 deploy/docker/thor-local/qualification/static-cases/static_case_executor.py \
  inspect static-case.calibration-schema-vss-json
```

Run the isolated tests:

```bash
python3 -m unittest discover \
  -s deploy/docker/thor-local/qualification/static-cases/tests -v
```

## Calibration identity boundary

The checked-in implementation schema validates the tiny generated positive and
adjacent-negative fixtures, but its canonical JSON document digest is not the
exact digest of the [published VSS schema](https://docs.nvidia.com/vss/3.2.1/calibration-schema.html).
This is a real exact-document identity gap, not a whitespace, serialization, or
key-order artifact: the local document has 77 `errorMessage` members while the
official document has two.

The difference is confined to that keyword. Recursively removing only object
members named `errorMessage` produces the same canonical projection digest for
both documents (`a00f2230...e88229`). The executor's `Draft7Validator` does not
use this extension keyword to decide whether an instance is accepted, so the
validation-rule projection and generated-fixture matrix match even though exact
schema identity does not. The case honestly remains `observed_mismatch`; it does
not invent an official schema body or promote static discrimination into
capability evidence.

## Integration boundary

After the Wave 3 live merge, the merge owner must separately review bindings,
provide integration-owned executor paths and collectors, and decide whether any
case is eligible to move out of candidate-only state. No such transition is
implemented here.
