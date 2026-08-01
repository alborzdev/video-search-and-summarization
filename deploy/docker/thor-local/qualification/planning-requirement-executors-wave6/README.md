# Wave 6 planning-requirement Smart City source contracts

This isolated candidate package starts from the exact 66 live-open planning
requirements left unselected after Wave 5. It selects six high-value Smart
City requirements whose useful evidence is genuinely static:

- artifact/version identity and the documented version skew;
- the x86 reference-platform prerequisite and explicit lack of official Thor
  support;
- the reference stream envelope, which is never a Thor pass criterion;
- the external-optional CARLA/Cosmos Transfer configuration contract;
- the TrafficCamNet training/export recipe and its distinction from the local
  five-class runtime surface; and
- the active Smart City limitations and recovery boundary.

The executor checks immutable local bytes only. It does not advance live
acceptance, add runtime evidence, edit any shared ledger, or perform network,
Docker, subprocess, lifecycle, credential, download, or write actions. The
Warehouse sample bundle is excluded.

```bash
python deploy/docker/thor-local/qualification/planning-requirement-executors-wave6/executor.py --json
pytest -q deploy/docker/thor-local/qualification/planning-requirement-executors-wave6/tests
```

All six source observations match their locked assertions. That does not erase
the underlying boundaries: five documented mismatches remain explicit and the
SDG lane remains external-optional. In particular, the package does not infer
official Thor support, a Thor performance envelope, a unified Smart City
version, delivered VLM fine-tuning, or remediation of known limitations.

The planning denominator remains 110 total, 26 materialized, and 84 live-open.
The five predecessor inventory packages contain 44 distinct package selections:
26 are now materialized static bindings and 18 remain live-open candidate-only
selections. Wave 6 audits the exact remaining 66 live-open requirements, selects
six, and leaves 60 without a candidate executor. All 84 requirements remain
live-open; the package does not materialize its six selections.
