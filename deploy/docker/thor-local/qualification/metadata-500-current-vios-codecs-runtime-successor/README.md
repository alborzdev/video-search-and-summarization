# Current 500-row metadata successor

This deterministic successor combines the current, runtime-evidence-bearing
289-row canonical Thor prefix with the unchanged 211 reviewed planning
candidates. It preserves candidate IDs and order, recalculates complete-source
claim hashes and 500-row family aggregates, and updates the v2 oracle schema to
accept the independently qualified CPU multimedia row.

Historical descriptors and predecessor post-state files remain immutable. The
successor registers a new 289/500 pair and selects the new 500-row view. The
500-row view remains honest about its boundary: the four non-CPU codec results
are described by the canonical runtime receipt but remain planning-only rows
until separately evidence-bound; main-VIOS AAC recording remains unqualified.

Regenerate atomically and then verify without writes:

```bash
python3 deploy/docker/thor-local/qualification/metadata-500-current-vios-codecs-runtime-successor/project.py --write
python3 deploy/docker/thor-local/qualification/metadata-500-current-vios-codecs-runtime-successor/project.py
python3 deploy/docker/thor-local/parity/verify_metadata_set.py --json
```

The projector performs no network, Docker, service, model, GPU, or product API
call. Its only write mode is the explicit `--write` operation over seven exact
repository outputs.
