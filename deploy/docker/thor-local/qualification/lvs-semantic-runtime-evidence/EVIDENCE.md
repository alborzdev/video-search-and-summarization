# Evidence boundary

This package contains a current source-bound runtime executor and receipt
schema, not a deployed receipt.

- Runtime activity performed while creating this package: **no**
- Docker or service lifecycle performed: **no**
- Network requests or downloads performed: **no**
- Host state mutated: **no**
- Warehouse sample bundle: **excluded**
- Deployed runtime receipts: **0**
- Capability admission or promotion: **0**

A passing fake-adapter test demonstrates executor control flow only. It is not
evidence that Thor LVS services, local inference artifacts, live captioning,
prompt behavior, cancellation, quiescence, or CA-RAG cleanup passed in a
deployed environment.

Only a receipt returned by `run_executor` against an operator-reviewed adapter
for the already-deployed exact local Thor profile can supply runtime evidence.
That receipt remains non-promoting until the separate qualification admission
workflow reviews it.
