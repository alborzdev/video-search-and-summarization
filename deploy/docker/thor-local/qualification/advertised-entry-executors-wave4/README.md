# Advertised-entry executors: wave four

This isolated package checks five remaining `video-summarization-live`
advertised-entry gaps. It digest-locks the exact 87-entry gap plan, manifest,
all three predecessor inventories (8 + 21 + 23 entries), and every source it
reads. The five cases leave 30 plan entries without a candidate executor.

Unlike the fragment-only source-shape cases in wave three, this package uses
Python AST call, attribute, guard, payload, and response assertions as its
primary evidence. It also performs bounded structural parsing of the LVS YAML
and the exact Logstash stream-ID/index mapping. It never imports or executes
the product modules.

## Run

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/advertised-entry-executors-wave4/executor.py

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s \
  deploy/docker/thor-local/qualification/advertised-entry-executors-wave4/tests \
  -p 'test_*.py' -v
```

Use `--list` to print exact IDs and repeat `--case <entry-id>` to run a bounded
subset.

## Boundary

Every observation is candidate-only cross-layer source-contract evidence.
Network, Docker, subprocesses, lifecycle actions, credentials, downloads, and
filesystem writes are forbidden. Results explicitly report no runtime
execution, workflow proof, readiness proof, model proof, runtime evidence, or
official capability effect.

The optional Warehouse sample bundle is neither used nor relevant. See
[EVIDENCE.md](EVIDENCE.md) for exact selection and non-claims.
