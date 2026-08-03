# Evidence boundary

This is a checked future metadata projection, not runtime evidence and not a
canonical promotion.

## Locked inputs

- Runtime producer commit: `c06932bd641b00ac67df4508e5831644544f9ac1`.
- Runtime contract: `e1a73e2c6a8fa92f60e462ccf6d6777e8a28df598aa7aa38bb50eab358f02d2f`.
- Runtime executor: `494efc50a20ef2356acec2b728fe9c98600405c2d644ddd6c1228d6db034b115`.
- Runtime result schema: `6934a06b1090a815df83d0b84eb6054ac851e4b6574ba588e921c6afde8470dd`.
- Runtime interface: `191e883c6bf5d2b1331d2e4555aded50d202dbe2070f7ddfc95c3d7bbf88f2e3`.
- Current 289-row oracle registry: `856a93bf11bbe4cb77b315fe5ae1884ccedb7dc83107f4142c6721e78688308c`.
- Selected 500-row oracle registry: `53fe977aa208cdc78604e214817dac7d3683edea4402b160b9d3cf46571b49e3`.
- Current 289-row official ledger: `834bb40b576d9e9e546cecb3bdb866993b7be7fd3bf9d5e9e19a0d852d4e4e39`.
- Selected 500-row official ledger: `315fd11b4e40773cc711a43eb9c27edcaee752649cd71b3d6494fa3eb4d89229`.

## Checked outputs

- Oracle projection: `c2b8d584b4bb00f42d6337bbad31038d016fe02a7cfbf92ac747f42075bdc6c0`.
- Non-promoting ledger projection: `315fd11b4e40773cc711a43eb9c27edcaee752649cd71b3d6494fa3eb4d89229`.
- Oracle rows: 500 total, exactly 3 projected and 497 preserved.
- Ledger rows: 500 total, 500 preserved and zero promoted.
- Selected suffix: 211 rows preserved exactly.
- Projected bounds: 21 actions, 21 requests, and 34 observed imported-product
  calls across the three future executor-ready rows.
- Runtime evidence records: zero. Selected oracle states remain
  `open_unexecuted`.

Entry `07` and the four non-core SpatialAI rows are unchanged. The compiler is
static and local: zero network, Docker, service lifecycle, model, download,
credential, cloud-provider, or Warehouse-sample activity is performed or
claimed.
