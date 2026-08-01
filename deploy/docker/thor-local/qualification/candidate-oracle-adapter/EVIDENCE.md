# Evidence boundary

Status: **211 candidate oracle plans translated; planning-only and
non-advancing**.

The deterministic adapter binds these raw inputs:

- candidate artifact: `a3c1b793f976fa384fb4ea588602f225e21c9d2d1fd563f12c0aadfa9d1a56fd`;
- candidate schema: `e3f09d7c86c46e236b9786f5eb3aa60868e67363224922ce04cfab3d60cd12a8`;
- current official capability ledger: `cde0dc3981aaf699a017c7108089aac72070101edc47a06489f3940e44fe52a0`;
- current official capability schema: `fb817586b9a37ad7975ca820f69a7f2c6e575bca9f8d8686701d5fa0bf505896`;
- current capability oracle registry: `c4e7a5ecfedfa2ddf18e68fc2bc110bea48d9ff7ce63d0dd4fdc169711beda90`;
- current capability oracle schema: `55de87c13e78b4f349e7095232f31c1135155e0bc13ed6bcb8e4abb906f26cf1`.

The checked artifact proves:

- exactly 211 unique candidate capability keys and 289 unique current keys,
  with no overlap and a 500-capability combined partition;
- exactly 74 byte-equal authoritative gap requirements;
- candidate execution boundaries of 159 local, 46 alternate-local, and 6
  external;
- 205 `open_unexecuted` and 6 `external_boundary_unexecuted` candidate rows;
- zero candidate evidence records, executor-ready rows, or promotions;
- null fixture materialization, executor, collector, duration, request, and
  action fields for every candidate;
- all 289 current oracle states and evidence arrays copied exactly by
  capability ID; and
- zero current evidence records, without changing the one `passed_prior`
  ledger state or any other current runtime state.

Semantic preservation hashes are:

- current ledger records: `afca818d0d73eecd692869f998e949e5e2df7c1b7fabf91d8a55afb1486eb96c`;
- current oracle records: `370f93028b6fe5638680b568198ad99c13d2554b5d6ab0c27dc546c15624feb2`;
- current state/evidence projection: `82a748a7fa0065283df1f7e80ea3d479e073276b3a2881d8d13ffadf9de11abb`.

The adapter schema raw hash is
`959727de4d57884d67202847cd968e73fd792d1811356755c197a2e34403cbbb`.
The adapter payload hash is
`e7b67f4e4c3f25641eeb95fd665b2dc0b0d9224c1fec81007b4b7cdc4a40b541`;
the encoded artifact raw hash is
`6e77635625a1f6b4b27dfcdc9aa5a0e695d6656adad041604f2b96fa2ac17235`.

The test suite contains 19 checks covering deterministic reproduction, exact
candidate translation, current-state preservation, strict schema rejection,
duplicate keys, duplicate capability IDs, source drift, fabricated source
locators, absolute/parent paths, symlink inputs and outputs, authoritative-gap
contradiction, and absence of runtime/network activation imports.

This is not runtime qualification. No live ledger, live oracle, protocol case,
acceptance wrapper, service, or host state is changed.
