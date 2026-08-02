# Protocol-v2 candidate cancellation source rebase

Rebinds the protocol-v2 candidate projection to the repaired RT/LVS cancellation sources and the final 28-operation local RT-VLM expected manifest, including DELETE /v1/generate_captions/requests/{request_id}.

## Static contract

The predecessor candidate is frozen. The 29 non-Warehouse case and binding identities retain their original order; the Warehouse row is explicitly excluded from this successor. Warehouse sample data is excluded. This package is additive and does not edit historical qualification artifacts.

No route was called. Cancellation cleanup, rollback, runtime evidence, admission, and promotion remain unresolved or zero.

Run:

```bash
python deploy/docker/thor-local/qualification/protocol-cases-v2-cancellation-successor/compiler.py --check
python -m pytest -q deploy/docker/thor-local/qualification/protocol-cases-v2-cancellation-successor/tests
```
