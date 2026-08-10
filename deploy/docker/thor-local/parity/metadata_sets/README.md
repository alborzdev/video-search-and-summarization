# Thor metadata-set selector

This directory provides the static, fail-closed metadata selector.
`selector.json` chooses one registered immutable descriptor. Each descriptor
binds a complete metadata plane: manifest, official ledger and schema,
capability-oracle registry and schema, and acceptance inventory.

The selected `thor-vss-3.2.1-current-event-transports-runtime-500` set
contains the exact current 289-row Thor prefix plus the unchanged 211-row
candidate suffix. The current prefix includes every prior runtime promotion and
the oracle-bound Kafka NvSchema, Redis event-stream, Video Analytics API, VIOS
live, and VIOS replay receipts; the
suffix remains evidence-empty and non-promoting. The registered
`thor-vss-3.2.1-current-event-transports-runtime-289` set exposes the same
canonical current prefix explicitly. Previous VIOS WebRTC, NvStreamer, VIOS
lifecycle, codec-runtime, agent-evaluation, SpatialAI, and older descriptors remain
checked in as immutable historical provenance but are deliberately not
registered as current.

The current pair also corrects `evaluation.agent.report`: its judge settings
are repository-bound `llms.eval_llm_judge` profile configuration (`4096`,
`0.0`) selected by `report_evaluator.metric_configs.llm_judge` in the exact
upstream dev-base config, not defaults declared by `ReportEvaluatorConfig`.

`resolver.py` validates the selector, descriptor, and every member before it
returns any document. Reads are bounded and file-descriptor-relative with
`O_NOFOLLOW`; duplicate keys, non-finite JSON, unsafe paths, symlinks,
non-regular files, raw-hash drift, schema drift, mixed target/count/ID sets,
oracle/ledger binding drift, policy-derived family aggregate drift, incomplete
or unknown acceptance scenarios, unknown sets, and observable read-time changes
fail closed. Returned documents are deep copies of one fully validated
in-memory snapshot.

To add a future version, add a new `validation_only` immutable descriptor and
its regular files, then add one hash-bound registry row. After its validator and
activation receipt are reviewed, change its lifecycle to `live_ready`, re-lock
the descriptor, and change `selected_set` in the same transaction. The resolver
semantics do not depend on the set ID or the count 289. Do not rewrite
historical descriptors or use symlinks as metadata members.

From the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/parity/metadata_sets/resolver.py --json

PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/parity/metadata_sets/resolver.py \
  --set thor-vss-3.2.1-current-event-transports-runtime-289 --json

PYTHONDONTWRITEBYTECODE=1 pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/parity/metadata_sets/tests/test_resolver.py

ruff check \
  deploy/docker/thor-local/parity/metadata_sets/resolver.py \
  deploy/docker/thor-local/parity/metadata_sets/tests/test_resolver.py
```

The resolver performs no network, service, Docker, host, model, GPU, runtime,
or Warehouse actions.
