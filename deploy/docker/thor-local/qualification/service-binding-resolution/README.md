# Service-binding resolution audit

This isolated package asks one narrow question for the four unresolved
`runtime-lanes` capabilities: does the authoritative checked-in capability
contract select a unique executable runtime service-role set?

The answer is currently **no for all four**. This is a bounded negative result,
not a guessed mapping:

- `customization.embedding-reindex-validation` explicitly requires
  `downstream_search_or_behavior_analytics` and lists three different re-index
  triggers, but selects no one downstream or model component.
- `protocol.nvschema.format-selection` says the choice is deployment-wide and
  mutually exclusive, but contains no producer/consumer participant registry.
- `protocol.nvschema.json-frame` explicitly describes its representation as
  illustrative rather than a complete validator and names no round-trip
  producer or consumer.
- `protocol.nvschema.protobuf-messages` fixes files, messages, and field tags,
  but names no canonical runtime producer/consumer set. Multiple checked-in
  services carry generated bindings or wire consumers.

`mapping.json` contains the reasoning-free machine decisions. Each decision is
bound to an exact ledger JSON pointer, literal contract assertions, forbidden
role-selection keys, raw file SHA-256 values, and required source literals. The
compiler additionally verifies the exact official-document byte locks already
captured by the parity source lock.

Repository-observed roles are retained only as non-authoritative topology.
They cannot populate `runtime_service_roles`, cannot update `runtime-lanes`, and
are not runtime evidence. JSON and Protobuf have a `repository-tooling` static
support role because checked-in decoders/generated bindings can support static
contract work; that does not resolve their runtime service binding.

Run:

```bash
python3 deploy/docker/thor-local/qualification/service-binding-resolution/compiler.py --check
python3 -m pytest -q deploy/docker/thor-local/qualification/service-binding-resolution/tests
```

Regenerate only after reviewing an authoritative contract change:

```bash
python3 deploy/docker/thor-local/qualification/service-binding-resolution/compiler.py --write
```

The compiler performs no network, Docker, subprocess, credential, download, or
runtime action and does not modify the ledger, oracles, acceptance records, or
`runtime-lanes`.
