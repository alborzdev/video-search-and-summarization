# Retained evidence

`runtime-receipt.json` is a current-Thor runtime pass for official row 326.
It is cryptographically bound to `contract.json`, the exact official ledger
row, source implementation, the active Alert/RT-VLM images, and the external
parser module.

The receipt proves:

- the configured dotted parser path loaded in the worker and FastAPI process;
- parser identity and configuration were observable;
- a real local RT-VLM response was normalized to a parser-owned structured
  verdict/reasoning response;
- the persisted response conformed to the pluggable `info.vlm_response`
  service schema without leaking the default `info.reasoning` field;
- Elasticsearch acknowledged the exact correlated document;
- an invalid parser import was rejected before health;
- the exact main runtime projection was restored and all owned artifacts were
  deleted.
