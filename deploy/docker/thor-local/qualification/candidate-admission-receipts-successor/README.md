# Candidate admission receipts successor

This isolated package publishes a source-locked, exact 211-row admission index
and the only currently trustworthy receipt state: an empty set. It is a
read-only validator, not an approval consumer or executor. A structurally valid
future envelope cannot admit a candidate.

Run the sole CLI mode from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/candidate-admission-receipts-successor/compiler.py \
  --check
```

There is no default, emit, write, receipt-ingestion, approval, action, or
execution mode.

## Exact current state

The index binds every candidate ID, oracle ID/index, stable order position,
mapping-row hash, candidate/oracle record hashes, exact leaf, complete
contract-ordered dependency closure, selected Metadata500 identity, mapping
artifact, 16-bundle contract, execution boundary, and Warehouse exclusion.

| State | Count |
| --- | ---: |
| `receipt_and_execution_bindings_missing_not_admitted` | 204 |
| `external_attestation_only_not_local_admissible` | 4 |
| `static_nonactivating_not_applicable` | 3 |
| Receipts | 0 |
| Admitted candidates | 0 |
| Executable candidates | 0 |

All 208 mapped candidates lack exact candidate-specific action,
service-role/profile, and cleanup/rollback bindings, as well as leaf and
dependency receipts. Their exact boundary split is local 159, alternate-local
45, and external 4. Across all 211 rows it is local 159, alternate-local 46,
and external 6. The three static exceptions have no leaf, empty closure,
receipts forbidden, and no runtime admission applicability.

## Future envelope is design-only

`receipt-set.schema.json` defines the fields a future receipt design must bind:
candidate/oracle and candidate-record identities; selected metadata set and
hashes; mapping artifact/row; bundle contract, exact bundle and closure;
execution boundary; distinct authorization/completion purpose; non-inheriting
authorization identity and signature bindings; issue/not-before/expiry times;
one-time run/replay bindings; exact action, service-role/profile,
input/model/fixture, cleanup/rollback, and evidence-destination hashes;
dependency receipt IDs or reviewed-not-required determinations; Warehouse
exclusion; and a canonical receipt hash.

That envelope is deliberately non-consumable: the root schema requires zero
receipts and zero trusted authorities. A canonical hash provides integrity, not
authenticity. No offline pinned issuer roots, signature verifier, global
spent-ID ledger, atomic consumption protocol, maximum TTL/freshness policy,
candidate action bindings, or source-locked per-DAG-edge not-required policy
exists. Until those are separately reviewed and bound, every non-empty receipt
set fails closed and every reviewed-not-required determination is unsupported.

## Fail-closed boundaries

- Unknown, duplicate, reused, expired, cross-candidate, cross-oracle,
  cross-bundle, stale-hash, missing-dependency, orphan, inherited, or replayed
  receipts are not accepted; currently all non-empty sets are rejected before
  attacker-controlled fields are interpreted.
- Firewall configuration cannot use a not-required disposition for physical
  interface inspection. It also remains blocked on a transaction-specific
  executor, exact pre-state/ownership binding, lossless rollback, and a fresh
  successful inspection receipt.
- Native audio and ASR transcript scopes are distinct. Native-audio evidence
  cannot satisfy an ASR candidate; future evidence must bind the exact model,
  fixture, and oracle.
- External attestations cannot promote a local result. All four mapped external
  candidates remain candidate-specifically unbound.
- The Warehouse sample bundle is excluded from authorization, inputs, evidence,
  cleanup, and every admission row. Operator-provided custom data is a separate
  future scope.

## Tests

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/candidate-admission-receipts-successor/tests
python3 -m ruff check \
  deploy/docker/thor-local/qualification/candidate-admission-receipts-successor
python3 -m ruff format --check \
  deploy/docker/thor-local/qualification/candidate-admission-receipts-successor
```

The adversarial tests cover the exact denominator/order/bindings, closure DAG
order, static and external boundaries, strict schemas/canonical artifacts,
duplicate JSON keys, non-finite JSON, unsafe paths/symlinks, check-only CLI,
and the empty-only rejection boundary for every listed receipt threat.
