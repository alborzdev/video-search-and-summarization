# Metadata-500 current MV3DT config-utils successor

This immutable planning successor compiles the exact future receipt-authority oracle document for:

- `tool.mv3dt.cam-info-generator`
- `tool.mv3dt.pub-sub-generator`

It rebases the current 289-row root oracle prefix into the selected Synthetic Data 500-row registry and preserves the selected 211-row candidate suffix exactly. Only the two MV3DT config-utils rows change.

The projection binds a checked tiny fixture manifest per capability and one runtime executor as fixture generator, executor, observation collector, cleanup executor, and postcondition collector. Both rows have seven target requests/actions: two independent positive runs plus five named adjacent-negative cases. Cam-info is bounded at seven actions and seven requests. Pub/sub is bounded at ten actions but seven requests because it performs three supporting camInfo fixture-generation actions. The aggregate envelope is therefore 17 bounded capability actions and 14 requests. Six separately counted model-argument helper invocations make 23 literal imported source-function invocations; they do not inflate the canonical action/request bounds.

The projected `ledger_binding` is the eventual reviewed final state (`wired`, `passed_current`, no known gap). The oracle itself remains `current_state: open_unexecuted` with `evidence: []`. No runtime success is claimed by this package, and canonical ledgers, manifests, selectors, and descriptors are not changed.

The embedded historical `wave3_acceptance.materialized` and `wave3_acceptance.executor_ready` values remain `false`; their exact contract assertions are not relabelled. The earlier candidate-only observation binding is also preserved byte-semantically.

`runtime-interface.json` is the contract with `mv3dt-config-utils-runtime-evidence-successor`. It fixes the CLI acknowledgement, executor roles, fixture paths/hashes, namespaces, workload, cleanup boundary, and zero network/Docker/service/model/download/Warehouse confinement.

Run the fail-closed static check and tests:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 deploy/docker/thor-local/qualification/metadata-500-current-mv3dt-config-utils-successor/compiler.py
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s deploy/docker/thor-local/qualification/metadata-500-current-mv3dt-config-utils-successor/tests -v
```

`--write` is reserved for reviewed deterministic regeneration after an intentional source/interface lock change. A separate clean target-bound runtime receipt is mandatory before canonical promotion.
