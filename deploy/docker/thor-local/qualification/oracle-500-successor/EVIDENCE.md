# Oracle 500 successor evidence boundary

Status: **500-row isolated successor compiled; planning-only and
non-advancing**.

## Raw source locks

- candidate oracle adapter: `6e77635625a1f6b4b27dfcdc9aa5a0e695d6656adad041604f2b96fa2ac17235`;
- candidate adapter schema: `959727de4d57884d67202847cd968e73fd792d1811356755c197a2e34403cbbb`;
- candidate source: `a3c1b793f976fa384fb4ea588602f225e21c9d2d1fd563f12c0aadfa9d1a56fd`;
- candidate source schema: `e3f09d7c86c46e236b9786f5eb3aa60868e67363224922ce04cfab3d60cd12a8`;
- official capability ledger: `cde0dc3981aaf699a017c7108089aac72070101edc47a06489f3940e44fe52a0`;
- official capability schema: `fb817586b9a37ad7975ca820f69a7f2c6e575bca9f8d8686701d5fa0bf505896`;
- live capability oracles: `c4e7a5ecfedfa2ddf18e68fc2bc110bea48d9ff7ce63d0dd4fdc169711beda90`;
- live capability-oracle schema: `55de87c13e78b4f349e7095232f31c1135155e0bc13ed6bcb8e4abb906f26cf1`;
- candidate protocol-v2 artifact: `886151fee9ce27b24601499011151e827c4742b32d400c609c8c0b149851db62`;
- candidate protocol-v2 schema: `831d982f6912358b8dfae049cd10ed709af299d91cb7196031d28b29a092877d`;
- API/deployment workloads: `ca4170118a94a659acca600d9ab00dca6504544f062edabd5cef0ed3311e8312`;
- workload schema: `736f9295e4f89afbb1aaed7c086155e30a09b6dc2c583433b9cb98ad2c005c14`.

## Semantic locks

- candidate adapter payload: `e7b67f4e4c3f25641eeb95fd665b2dc0b0d9224c1fec81007b4b7cdc4a40b541`;
- protocol-v2 payload: `65715e2ebfbe164ae38a6b20ca7dc23b6f3a65aaa9dd1632bdda746c4c929f24`;
- workload payload: `0e8512e64399af7d8acc0c7136efbd52da4ebf9119ad0826859e6fce6906d847`;
- preserved live oracle records: `370f93028b6fe5638680b568198ad99c13d2554b5d6ab0c27dc546c15624feb2`;
- projected 500 oracle records: `649458c5d354b7012bd5c719bc9e4711d263b0ba9951e244a2bc1cb5331273b5`;
- live capability-ID order: `bcff14e8d0122fbd1da6c5075a6d2b4c3abfd03823834f33b60c69531708d728`;
- candidate capability-ID order: `1c0cc33efa1aa6283e467e5fc78bbed8b4cbe8ff23fdbf6db3190144996a3ef9`;
- projected capability-ID order: `31ad7e72b405a52c6cb9e7f6f77a7f9a61b73c05a87c87678f089c265c306555`;
- successor payload: `4d4875014874bcad3fa9f90024207097a1304090759a90fc1f760beef97d33dc`.

The successor schema raw hash is
`fcbe27337accc57c5a57a3ce7bf26d1e532c9001f7841134ec22db8663d41024`.
The encoded successor artifact raw hash is
`75a7c6b6ecc5bcfee0eece99a10ca29c0258717887c59847252629ac4d21e364`.

## Checked invariants

- exactly 289 original rows followed by exactly 211 candidate successor rows,
  with a disjoint 500-capability partition;
- the 289-row prefix follows exact official-ledger order and the 211-row suffix
  follows strict parsed manifest-pointer order, never lexical ID order;
- the original prefix equals the live source semantically and canonically, with
  289 capability-keyed original-record hashes;
- all adapter fields survive exact projection and each candidate row has a
  payload hash;
- all 74 authoritative gap requirements remain exact adapter contracts;
- exactly 23 protocol-v2 bindings, 41 API workloads, and 19 deployment
  workloads are consumed without defaults or cross-kind binding;
- 159 local, 46 alternate-local, and 6 external candidate boundaries retain
  their exact state, runtime-state, and network-scope mapping;
- all candidate materialization and execution fields remain null, with zero
  evidence, executor-ready rows, or promotions;
- required cloud inference is false and the Warehouse sample bundle is
  excluded; and
- no runtime, network, Docker, service, model, or host operation is present.

The test suite contains 38 checks covering deterministic compilation, exact
289/211 preservation, adapter fidelity, protocol and workload set equality,
null/non-promoting state, boundary mapping, schema strictness, semantic hashes,
protocol drift, workload key swaps, lexical reordering, wrong-class gaps,
wrong-kind or loose bindings, nested additional properties, scalar type drift,
source-lock identity drift, arbitrary live/candidate integrity-map keys, mutated
order hashes, duplicate JSON keys, unsafe paths, symlink inputs and outputs,
atomic replacement, raw source locks, and absence of activation imports.

This artifact is a reviewed planning successor only. It is not runtime evidence
and cannot advance any capability state.
