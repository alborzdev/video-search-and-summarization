# Evidence

## Result

The isolated compiler proves the following post-state without changing live
metadata:

- 55 features, 16 skills, 500 ordered capabilities, and 500 correspondingly
  ordered oracles;
- exact preservation of the first 289 live oracle rows and exact admission of
  211 successor planning rows;
- zero aggregate drift and zero acceptance coverage gaps;
- candidate classes: 159 required-local, 46 alternate-local, six external;
- candidate runtime states: 205 `not_qualified`, six `not_applicable`;
- 23 planning-only protocol bindings and 60 planning workloads;
- zero candidate runtime evidence, executor, collector, materialization, or
  promotion authority;
- eight external manifest families and six external candidate boundaries;
- Warehouse sample bundle excluded and live application unauthorized.

The adversarial suite has 29 passing tests covering ordering, duplication,
binding substitution, discriminator and loose-property attacks, activation
injection, external boundary downgrade, operator-gate promotion, protocol and
workload drift, dangling assertions, aggregate/coverage drift, exact proof
validation, duplicate/non-finite JSON, unsafe paths, symlinks, package-bounded
atomic writes, and absence of runtime/network/Docker/subprocess imports.

## Generated artifact raw SHA-256

| Artifact | SHA-256 |
| --- | --- |
| `post-state-official-capabilities.json` | `f1e63b25c607a09f19a3c53aa47d8d152c61ffbd330440b93d54eccfaa49add6` |
| `post-state-manifest.json` | `c71f75246fc1e4cbc388f93849d27c3b7dc7edf2d0a516fb3fa13f6d412a4a93` |
| `post-state-acceptance-inventory.json` | `69dc4aca160ae236880f9afe7b873c0b3b423f8981c5d934e4ed647043cd8cb0` |
| `post-state-capability-oracles.json` | `17091a3c0e9ac4d3aba7b5c6d91f09c8832648f149ac0624f3b63cd2c5e77271` |
| `post-state-capability-oracles.schema.json` | `b24308d9647ff7a4c7b66cc91881749eaaa84c21ab7423677fc30ab4f9c36233` |
| `migration.json` | `39ec1db0d4e42c7d39c237f647f80c15dff12cea15630ef3e8572bf5e32dac0d` |
| `migration.schema.json` | `786b095f40510e87e76405d0b06e3aae63f50530670d9a8453d5d5dee9b47eb7` |

Migration canonical payload SHA-256:
`cb9e00948545e21599889d7411ee7258aac92afb4715e33565663d0b896d934a`.

## Identity/order canonical SHA-256

| Sequence | SHA-256 |
| --- | --- |
| Feature IDs | `01049c6784ab291b080198ae890a856173e4e2ad4045238d8b304ff54f6db247` |
| Acceptance coverage feature IDs | `01049c6784ab291b080198ae890a856173e4e2ad4045238d8b304ff54f6db247` |
| Skill IDs | `9a25f4edc4cafa310ba7a1ac3df8bedb2ebf6bfe15a70d998dd66da027c6d917` |
| Capability IDs | `31ad7e72b405a52c6cb9e7f6f77a7f9a61b73c05a87c87678f089c265c306555` |
| Oracle capability IDs | `31ad7e72b405a52c6cb9e7f6f77a7f9a61b73c05a87c87678f089c265c306555` |
| Preserved 289 oracle rows | `370f93028b6fe5638680b568198ad99c13d2554b5d6ab0c27dc546c15624feb2` |
| Candidate 211 oracle rows | `8cc136ea78c7395c534db0c8601b4881ac7982a70e6c43218a6d7cc20b6ef5b4` |

## Five-target migration journal

| Target | Before raw / canonical SHA-256 / Git blob | After raw / canonical SHA-256 / Git blob |
| --- | --- | --- |
| Manifest | `1f56d63437bd7742cf7488b9bd85b25fc886cdaf39a3c2b46aabecbc6b7201ce` / `cbf65ddc55b3518763bf8ee57f58f24619956473035aeca98a274a7b1bc959f2` / `a9cfa3a01f9881cc37f08608f8268a0df3602e13` | `c71f75246fc1e4cbc388f93849d27c3b7dc7edf2d0a516fb3fa13f6d412a4a93` / `68620554a3a5f731d15283787f1e0bb3ff8e4a4e673b726412c94d592caf790c` / `a8516927c9cfddbab1d0253fb169d67c4c088f7e` |
| Ledger | `cde0dc3981aaf699a017c7108089aac72070101edc47a06489f3940e44fe52a0` / `30142a6716d48597f2daee6a5e776629393526bc7185ca7f70b89fefe2b13eec` / `5b9ea5ac3d67d6a700b0b1c21346a1a4db34c161` | `f1e63b25c607a09f19a3c53aa47d8d152c61ffbd330440b93d54eccfaa49add6` / `d9b78ab55c60df360b7f9afa1d57b5047644682ac85fd0749758cc0d2db48800` / `b1b3ef11dd168e7c656f025c7e009656b6b45150` |
| Acceptance | `79001985f9cc9d0dbb64adea2a014aaedacd0b0411d8becb5b311c8697a563a5` / `a15f9f6fb349b9907fc4934f633c9d9158dd781cd1f9cee50954ad836523dc25` / `e1f32e9b1ecb1ea1a8e89bc80a5bcf9958869298` | `69dc4aca160ae236880f9afe7b873c0b3b423f8981c5d934e4ed647043cd8cb0` / `b1d926b8ee7a1c7dde90fbc650c7758b3464296db90a002e0835c527af94b4e2` / `97e210d4944a2ba342541b8816709e0a6a46b0e3` |
| Oracles | `c4e7a5ecfedfa2ddf18e68fc2bc110bea48d9ff7ce63d0dd4fdc169711beda90` / `6d2b3991e6e31a74ba42c3271d7cc0dce8748468617d18772078db6abfd1e336` / `3c58bacf61d0a7dfad4bd3a3858a784feecd01d2` | `17091a3c0e9ac4d3aba7b5c6d91f09c8832648f149ac0624f3b63cd2c5e77271` / `1c2dae973a8ad69b02730f21d1d504fb9f80e3a6200bc98e1f435fad195ef286` / `523aab9d825439ead0c8a424e4f9bf9b31375dd8` |
| Oracle schema | `55de87c13e78b4f349e7095232f31c1135155e0bc13ed6bcb8e4abb906f26cf1` / `28fa11eb732af9ec8d8b72153ca656f7ed4004afce95d7cba18af11aa9238bfb` / `0ae50dadd151bf2cb71a757ce85d341bf90bf99c` | `b24308d9647ff7a4c7b66cc91881749eaaa84c21ab7423677fc30ab4f9c36233` / `208ca76a832ffb3c1079236c600addc7c16fe17a3d556aab2c1afe6cf09a4071` / `e1ce42e71cbc895b069156390753812cf3f39abb` |

## Validation commands

Observed locally without services, Docker, network, downloads, host inspection,
model execution, or Warehouse:

```text
python3 .../compiler.py --check
PASS: isolated five-file metadata post-state; capabilities=500, oracles=500, candidate promotion=0

pytest -q .../tests/test_compiler.py
29 passed

ruff check .../compiler.py .../tests/test_compiler.py
All checks passed!
```

## Application boundary

This evidence does not authorize a live write. A future atomic application must
first add and review a v2-aware `capability_oracles.py` adapter, verify every
recorded before hash, install all five post-state targets together, rerun the
live verifiers, and retain the reverse rollback journal. Partial application is
forbidden.
