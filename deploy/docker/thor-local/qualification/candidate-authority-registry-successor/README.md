# Candidate authority registry successor

This package defines the missing authority boundary in front of candidate
admission. Its checked state is deliberately empty: zero trusted roots, keys,
revocations, policies, authorization envelopes, completion receipts, accepted
receipts, consumed receipts, or spent-ledger entries. It cannot make any of the
211 candidates admitted or executable.

Run its only CLI mode from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/candidate-authority-registry-successor/compiler.py \
  --check
```

There is no default, emit, sign, verify, accept, consume, write, action, run, or
execute mode. Every nonempty authority, policy, receipt, or ledger collection
fails closed before its contents can be treated as trusted.

## Source-locked empty state

The compiler raw-locks and schema-validates the published execution-binding
registry and admission package. It locks the execution registry at
`59600e64...f544`, its 208 ordered rows at `25b6dc3b...96c`, and locator locks
at `c8311f1d...1708`. It independently asserts all admission-grade and all 13
authoritative-binding totals remain zero. It locks the 211-candidate admission
index at `6dc6345f...d7eb` and the existing receipt set at `7bfeb7e7...c805`,
which is also exactly empty.

SHA-256 locks provide byte integrity only. They do not establish an authority,
authenticate a self-declared root, prove operator consent, or make a receipt
trusted.

## Design-only future contract

`signed-receipt-envelope.schema.json` publishes a strict future format with no
algorithm negotiation:

- DSSE envelope and `DSSEv1` pre-authentication encoding;
- exactly one payload type;
- Ed25519 keys and signatures only;
- an RFC 8785 JCS payload requirement;
- distinct candidate-action authorization and successful-completion receipt
  types; and
- exact binding of authority registry ID/epoch/raw/previous/root digests,
  receipt/auth-event/run/nonce/replay IDs, scope/role/threshold policy,
  candidate/oracle/metadata/mapping/execution-registry identity, exact leaf
  bundle row and dependency DAG, action/executor/service/profile/Compose/input/
  model/fixture/cleanup/postcondition/evidence hashes, boundary, validity,
  previous receipt digest, one-time status, and Warehouse exclusion.

The authority schema includes future shapes for root-pinned registry epochs,
active and revoked Ed25519 keys, authenticated revocations, roles, scopes,
N-of-M thresholds, maximum TTLs, per-DAG-edge reviewed-not-required policy, and
atomic spent-receipt records. The checked schema caps every such collection at
zero. A future implementation must additionally enforce that each threshold is
no greater than its distinct eligible-key count. It must reject duplicate
`keyid` entries and count only distinct, eligible, non-revoked signer identities
toward N; JSON `uniqueItems` alone cannot enforce signer identity uniqueness.

These schemas are not a verifier. The envelope schema only checks the outer
base64 shape; its decoded payload definition is design documentation and is not
automatically applied to bytes inside `payload`. A future verifier must
strictly decode and canonically re-encode base64, parse with duplicate and
non-finite rejection, apply RFC 8785 JCS, construct exact DSSE PAE bytes, verify
Ed25519 signatures against independently pinned roots, enforce scope/role/
threshold and registry epoch continuity, consult authenticated revocations and
trusted time, and atomically consume the receipt/run/nonce/replay-domain tuple.

The signed `execution_boundary` must exactly equal the source-locked candidate
row; an external attestation can never promote local parity. Candidate, oracle,
model, and fixture identities must reject cross-candidate and native-audio/ASR
substitution. The physical-interface firewall-configuration dependency on
read-only inspection is non-waivable: no reviewed-not-required policy or
decision may cover that edge, and configuration requires a fresh successful
inspection completion receipt in the same bound run/replay domain.

## Explicitly unavailable

This package has no trusted root key, offline signature verifier, RFC 8785 JCS
implementation, DSSE PAE implementation, Ed25519 implementation, trusted time,
epoch rollback protection, authenticated revocation freshness, or global
durable atomic spent ledger. It does not use or download `model-signing`,
`cryptography`, models, keys, certificates, secrets, or any signing tool. A
key fingerprint, signature-shaped base64 string, self-declared registry, or
structurally valid payload cannot qualify anything.

The repository's existing skill-signing workflow uses a different
certificate-chain/ECDSA system and may fetch tooling and roots dynamically. It
is neither imported nor treated as candidate authority. The fixed
DSSE+Ed25519+JCS format here is a new, unimplemented design, not an inherited
trust path. Existing local hash-chain and in-memory cleanup helpers are also
not a central authority or replay ledger.

No runtime, network, Docker, host, firewall, service, model, or Warehouse action
is performed. Required cloud inference remains false, and the Warehouse sample
bundle remains excluded.

## Tests

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/candidate-authority-registry-successor/tests
PYTHONDONTWRITEBYTECODE=1 python3 -m ruff check \
  deploy/docker/thor-local/qualification/candidate-authority-registry-successor
PYTHONDONTWRITEBYTECODE=1 python3 -m ruff format --check \
  deploy/docker/thor-local/qualification/candidate-authority-registry-successor
```

Tests cover exact empty state and source hashes, schema strictness, authorization
versus completion separation, full binding fields, fixed outer envelope shape,
nonempty fail-closed behavior, absent trust services, Warehouse/cloud/runtime
inertness, unsafe paths, duplicate/non-finite JSON, and check-only CLI behavior.
