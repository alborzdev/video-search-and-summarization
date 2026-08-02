# Evidence boundary

Clean runtime authority:

- Aggregate receipt: `aggregate-runtime-receipt.json` (`1e207198c907fde4f7370c3de814b88ebcd171e616be5f833e50509fb4b85362`).
- Clean checkout HEAD: `53998f19f11451f63ef582e1f9d06602229461eb`.
- Clean checkout tree: `eec19dd141cfa1278ef05754f1be85e51aa4972f`.
- Runtime contract: `a985966163e9bc726abcadf4564b9274657d426ebcd6629e2c8387b79c3ab99c`.
- Runtime executor: `74b8ad607621a4a796899d7837e65c3f88c8f2b56e404e1942b529e8ddba140b`.
- Future oracle document: `c50c762e94ceb68e05c0e4a49c8d8f5405f462bd030f81bf982cd2593cf5d5b6`.
- The aggregate records 75 allowlisted local commands and exactly zero network, Docker, service-lifecycle, model, download, and Warehouse-sample accesses.
- Aggregate cleanup records zero repository mutations, removal of the exact temporary root, and unchanged sibling names.

Derived official receipts:

- semantic label helpers: `91afcd30bf85fdfe6cbc29ac0792707ee459912c900f2e2e6c6ade9dd66d9324`
- dataset checks: `dbf1a3a21ae063b4b4eeb19553482cf245e98cdcbb32b5c3221f46deb8cc5a20`
- RGB/depth/video conversion: `dac14785935ed85305b77d73cdd13f6ea953709bec8da83f07f272cd4d0e411b`
- ground-truth conversion: `2611b2a01ac98e5c95a33980c3164811a1ded0c13e5ed0de94e0fa94e7141e7f`

Post-state derivation:

- Oracle registry: `c50c762e94ceb68e05c0e4a49c8d8f5405f462bd030f81bf982cd2593cf5d5b6`, 500 rows, exactly four executor-ready Synthetic Data rows and 496 preserved rows.
- Official ledger: `6698f904f93fbefa7c2bc9c7512ccf4765d3ba27200843a86ea1e6522375ae73`, 500 rows, exactly four promoted rows and 496 preserved rows.
- Manifest: `b2fa6b72ca756b37103178cb3d40aeed9e8d4d5c137883812ff0600f62168fb8`, 55 families, exactly one changed family.
- The current 289-row official-ledger prefix is rebased into the selected 500-row ledger; the selected 211-row suffix is byte-for-byte structurally preserved.
- The selected acceptance inventory remains unchanged at `69dc4aca160ae236880f9afe7b873c0b3b423f8981c5d934e4ed647043cd8cb0`.

The checked receipt promotion is limited to these four capabilities. It is not evidence for any other VSS family.
