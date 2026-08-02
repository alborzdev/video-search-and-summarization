# Evidence state

No checked promotion receipt is committed in this package yet. A checked
receipt would be invalid until the producer and four executor-ready oracle rows
exist in a clean committed checkout.

On 2026-08-02, the explicit non-promoting development path passed on Jetson
Thor after the HDF5 converter was made byte deterministic:

- four capabilities passed two independent runs each;
- all ten dataset checkers and their adjacent negatives passed;
- 75 bounded local commands ran;
- all output digests were identical between clean runs;
- the executor-owned temporary parent was empty and removed;
- no repository file was mutated and no network, Docker, service, model,
  download, credential, or Warehouse sample was accessed by the workload; and
- `receipt_is_runtime_evidence` remained `false` because the checkout was dirty
  and the current selected rows are planning-only.

This development observation proves producer feasibility. It is not a
`passed_current` receipt and must not be used to mutate the parity ledger.
