# Current 500-row Search runtime successor

This deterministic successor combines the current 289-row canonical Thor
ledger—including the oracle-bound Search backend and complete rendered Search
UI runtime qualifications—with the unchanged 211 reviewed planning candidates
from the prior UI Global Chat-qualified 500-row view. Candidate IDs, order,
planning-only states, and evidence-empty status remain unchanged.

The two promoted current rows are deliberately narrower than their parent
features. `semantic-search` remains partial until its separate upload
Content-Type, follow-up, and wider archive-management boundaries are qualified;
`main-ui` remains partial while Alerts, Video Management, known-issue behavior,
and the alternate Smart City Map remain open.

Regenerate atomically and verify:

```bash
python3 deploy/docker/thor-local/qualification/metadata-500-current-search-runtime-successor/project.py --write
python3 deploy/docker/thor-local/qualification/metadata-500-current-search-runtime-successor/project.py
python3 deploy/docker/thor-local/parity/verify_metadata_set.py --json
```

The projector performs no Docker, network, service, GPU, model, browser, or
product API operation. Its explicit write mode changes only the four post-state
documents, two descriptors, and the selected-set pointer. It does not use the
Warehouse sample bundle.
