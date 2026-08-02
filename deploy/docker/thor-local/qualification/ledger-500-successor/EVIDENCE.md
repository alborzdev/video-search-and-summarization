# Evidence boundary

Status: **500-row candidate projection complete; isolated and non-advancing**.

## Raw source locks

- live manifest: `1f56d63437bd7742cf7488b9bd85b25fc886cdaf39a3c2b46aabecbc6b7201ce`;
- live official capabilities: `cde0dc3981aaf699a017c7108089aac72070101edc47a06489f3940e44fe52a0`;
- official capability schema: `fb817586b9a37ad7975ca820f69a7f2c6e575bca9f8d8686701d5fa0bf505896`;
- candidate source: `a3c1b793f976fa384fb4ea588602f225e21c9d2d1fd563f12c0aadfa9d1a56fd`;
- candidate schema: `e3f09d7c86c46e236b9786f5eb3aa60868e67363224922ce04cfab3d60cd12a8`;
- candidate oracle adapter: `6e77635625a1f6b4b27dfcdc9aa5a0e695d6656adad041604f2b96fa2ac17235`;
- candidate adapter schema: `959727de4d57884d67202847cd968e73fd792d1811356755c197a2e34403cbbb`;
- acceptance inventory: `79001985f9cc9d0dbb64adea2a014aaedacd0b0411d8becb5b311c8697a563a5`;
- live capability oracles: `c4e7a5ecfedfa2ddf18e68fc2bc110bea48d9ff7ce63d0dd4fdc169711beda90`;
- live capability-oracle schema: `55de87c13e78b4f349e7095232f31c1135155e0bc13ed6bcb8e4abb906f26cf1`;
- oracle-500 successor: `75a7c6b6ecc5bcfee0eece99a10ca29c0258717887c59847252629ac4d21e364`;
- oracle-500 successor schema: `fcbe27337accc57c5a57a3ce7bf26d1e532c9001f7841134ec22db8663d41024`.

## Package and artifact hashes

- projection proof schema raw SHA-256: `8f74b849581029c303a1e7a927f1f31b7458ed87e529d14e25134e52396f4ec9`;
- projected manifest schema raw SHA-256: `90b0452d8e19f7770b1ed13d6a5a7f1040612cc6e99edf8f4cd2d32ed86582c5`;
- projection proof payload SHA-256: `2c62052d9059cad422e2a1acf336a61bc6a14e6d1127d26d570b2c2df7ceb0ed`;
- projection proof raw SHA-256: `4e206240795e2cf739f595811920ae66a7868ebe92031feb73b7fcbbe5a971d0`;
- projected manifest canonical SHA-256: `1d8d4d470c456c4eca8f6550e890cf2ee469ddd578b7c98c341324608749372b`;
- projected manifest raw SHA-256: `075a859219dfee4982338ca04244b6d444e0c23c9666c88e58e8f5fe58c366e8`;
- projected ledger canonical SHA-256: `d9b78ab55c60df360b7f9afa1d57b5047644682ac85fd0749758cc0d2db48800`;
- projected ledger raw SHA-256: `f1e63b25c607a09f19a3c53aa47d8d152c61ffbd330440b93d54eccfaa49add6`.

## Semantic hashes

- current manifest: `cbf65ddc55b3518763bf8ee57f58f24619956473035aeca98a274a7b1bc959f2`;
- current manifest non-ID feature fields: `c39e4e5863f1f52241a3f7b6d20a335609d2b52c2ea20337f65704d4dee67a34`;
- current feature capability-ID order: `3d3351479bc835785723fff9ecd707a4218a938c37ef41dd9010f0e2b7a07a31`;
- current ledger root without capabilities: `a4a86f0230bf4618545ebdbc692f6c98d83af8bf1ad9beee09b4782189e00898`;
- current 289 capability records: `afca818d0d73eecd692869f998e949e5e2df7c1b7fabf91d8a55afb1486eb96c`;
- current source discrepancies: `b97cf465bd5665c4192a24f8090b886792f292fac537c72179cac8a1b6f4b292`;
- current runtime-state projection: `8641982b7834b1442c4c090c96bb6fa9d829aba60fb45e3142a30d4f2594506b`;
- current manifest evidence fields: `b4738888a1fa2b67ef924f04673b2a6ae17e5979bbc22af600761d1459846f9d`;
- ordered 211 candidate records: `658f7972440b80eb6302c9ca6a64eb231ebaa41fc4d5ce7b633df020a55d69d9`;
- projected 500 capability records: `c83b16277c67fc74b61b9ef8cd659141faaeca88bf4a7701153bf8cde8b3a301`;
- candidate manifest-pointer append proof: `b341b268fe9d363a1097f1efbdf137796b8a11ff9daaf1c3a9949ea5033d1724`;
- projected oracle capability-ID order: `31ad7e72b405a52c6cb9e7f6f77a7f9a61b73c05a87c87678f089c265c306555`;
- projected 500 oracle records: `649458c5d354b7012bd5c719bc9e4711d263b0ba9951e244a2bc1cb5331273b5`;
- current 289 oracle records: `370f93028b6fe5638680b568198ad99c13d2554b5d6ab0c27dc546c15624feb2`;
- current oracle state/evidence projection: `82a748a7fa0065283df1f7e80ea3d479e073276b3a2881d8d13ffadf9de11abb`;
- 126 source claim-set transition rows: `146ac19f6bb32fa89c1630a735f5d8edd8fd1579828bba8e77280083e39d1a68`.

## Checked invariants

- 289 current capability records are preserved exactly and in order;
- 211 exact candidate records are appended in strict manifest-pointer order;
- all 55 feature records and 500 advertised literals change only through the
  exact `official_capability_ids` suffixes;
- all 500 titles have one exact same-family mapping, with zero missing or
  ambiguous rows;
- 126 source records preserve order and non-derived content while exactly 17
  claim-set hashes change and 109 remain unchanged under the live verifier's
  canonical algorithm;
- 74 authoritative gap bindings and 137 family-only rows remain exact;
- the oracle successor has the same 500 capability IDs in the same order and
  exact ledger bindings;
- live merge remains blocked by exactly nine family-status rows and eight
  acceptance-coverage rows; six external Thor-state differences are exact,
  separately reviewed, and nonblocking;
- proof schemas pin the exact append, source-transition, blocker, and
  distinction identities and reject duplicate/replacement/overlap mutations;
- zero runtime evidence, executor-ready candidates, current-pass promotions,
  required cloud inference, or Warehouse sample entries are introduced; and
- custom-data Warehouse capability remains in scope.

The 32-check test suite also covers duplicate JSON keys, non-finite JSON,
absolute and parent paths, symlinked inputs, symlinked/non-directory output
parents, output symlinks, deterministic atomic writes, static imports, and all
integrity locks.

No live manifest, capability ledger, oracle registry, acceptance inventory,
wrapper, runtime service, or host state is modified.
