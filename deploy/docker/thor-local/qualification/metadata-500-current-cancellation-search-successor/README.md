# Current post-cancellation/post-Search Metadata-500 successor

This package restores one atomic, authoritatively verifiable Metadata-500
snapshot after the checked 289-row ledger and oracle registry evolved for exact
RT-VLM/LVS request cancellation and the later Search semantic qualification.

The successor replaces only the first 289 rows of the frozen 500-row rebase
with the exact current checked rows, refreshes source claim-set hashes, and
preserves all 211 candidate capability and oracle rows byte-for-byte by object
equality. It does not import any Wave 3 advertised-candidate binding overlay.

The canonical selector now exposes a current 289 set and selects the current
500 set. The earlier `thor-vss-3.2.1-live-289` and
`thor-vss-3.2.1-metadata-500-staged` descriptor files remain untouched as
historical artifacts, but are intentionally no longer registered because their
member hashes describe mutable canonical files before cancellation landed.

Run the static check with:

```bash
python compiler.py --check
```

There is no write, execute, network, Docker, service, model, credential, or
runtime mode. Warehouse sample content remains excluded. All 500 oracles remain
unexecuted, with zero evidence, executors, collectors, or promotable rows.

## Historical selector-lock boundary

Changing the canonical selector is necessary for atomic activation. Any frozen
package that directly locks the historical selector hash
`8021efc4684b106539a627b3ddfd82937c7ecf1d6111a3c87538fc5ea7360bec`
is historical and must not be replayed against this selector. The complete set
of compiler packages containing that direct historical-selector lock is:

- `live-metadata-500-migration-rebase-successor`
- `live-metadata-500-activation`
- `live-metadata-500-activation-rebase-successor`
- `candidate-approval-mapping-successor`
- `candidate-approval-mapping-rebase-successor`
- `candidate-approval-mapping-rebase-successor-v2`
- `candidate-admission-receipts-rebase-successor`
- `candidate-authority-registry-rebase-successor`
- `candidate-execution-bindings-wave1-rebase-successor`
- `runtime-approval-bundles-rebase-successor`
- `sparse4d-candidate-dependency-repair`
- `sparse4d-candidate-dependency-repair-rebase-successor`

Their checked artifacts are not modified or deleted. The unified wrapper
retains later exact-identity successors where available, but no longer replays
the five formerly invoked direct-selector compilers after atomic activation.
