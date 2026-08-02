# Static evidence

The compiler SHA-256 locks the current 289-row ledger/oracles and the frozen
post-rebase 500-row ledger/oracles, manifest, acceptance inventory, and v2
schema. It deterministically reconstructs the checked current 500-row pair and
requires exact checked bytes.

Validation proves exact ledger/oracle order and binding equality, exact
preservation of the 211-row candidate suffix, 464 `open_unexecuted` plus 36
`external_boundary_unexecuted` rows, and zero runtime evidence, executors,
collectors, or promotion. It also locks both current descriptors and the atomic
selector that selects the post-cancellation/post-Search 500-row set.

The compiler additionally raw-locks the five historical-selector artifacts
omitted from direct replay: mapping v1 `dd5be5...`, Sparse4D repair `099b89...`,
mapping v2 `cb9bea...`, admission `74398a...`, and authority `954aa4...`. Their
ordered candidate/oracle identities are checked against the unchanged current
211-row suffix. Mapping/admission/repair/authority policy and row state must
remain at zero admission, receipt, runtime evidence, execution, authority, and
promotion; the empty authority registry binds the exact admission artifact.

The authoritative resolver/verifier tests separately exercise both registered
current sets and invoke the official capability and v1/v2 oracle validators.
No runtime receipt is created by this static evidence.
