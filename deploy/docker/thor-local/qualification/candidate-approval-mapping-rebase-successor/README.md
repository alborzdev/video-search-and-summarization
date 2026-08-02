# Candidate approval mapping rebase successor

This is an isolated, non-applying successor to
`candidate-approval-mapping-successor`. It preserves all 211 predecessor
classification, bundle, dependency-closure, state, and zero-approval semantics
while rebinding versioned metadata and reviewed integrity hashes.

The final activation pair is:

- `live-metadata-500-activation-rebase-successor/projected-selector.json`
- `live-metadata-500-activation-rebase-successor/projected-live-ready-descriptor.json`

The activation receipt/schema, frozen migration-rebase oracle/schema, and
reviewed protocol candidate artifact/schema/compiler/tests are also exact
source locks. All source and output hashes are pinned; no `PENDING` marker
remains.

## Exact semantic boundary

Candidate order and all 211 mapping semantics remain exact. The refreshed
protocol source changes only three integrity fields in two rows:

- `candidate_record_canonical_sha256`
- `candidate_source_payload_sha256`
- `protocol_binding_canonical_sha256`

The affected capabilities are structured file summarization output and live
SSE MCP server. No classification, bundle, closure, readiness, approval, or
execution field changes.

## Preservation and rollback

The compiler independently locks all six files in the historical mapping
package plus the currently applied canonical selector and descriptor. It never
imports or writes the predecessor. Its transactional writer accepts exactly
`mapping.json` and `mapping.schema.json`, stages both, and restores the prior
pair if commit fails.

Rollback is retention-based: the exact historical package remains under its
original path and hash. Canonical metadata activation remains outside this
package and unauthorized.

## Validation

```bash
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/candidate-approval-mapping-rebase-successor/tests

PYTHONDONTWRITEBYTECODE=1 python \
  deploy/docker/thor-local/qualification/candidate-approval-mapping-rebase-successor/compiler.py \
  --check
```

`--write` performs exact output-pin validation before its package-local
two-file transaction.
