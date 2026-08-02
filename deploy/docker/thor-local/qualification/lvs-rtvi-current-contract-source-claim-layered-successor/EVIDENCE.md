# Static evidence

This package contains source and contract evidence only. It records no live
service execution, runtime evidence, or readiness promotion.

Validated current identities:

| Artifact | SHA-256 |
| --- | --- |
| LVS MCP expected manifest | `6979727420bd3a6d0a58c4edd5ca07566fcbf3423f7a66198e12847bdd3d4d8a` |
| LVS expected manifest | `d1ed1fef7a40b1459722bcdefa766919705fd546d77074da087d5a2791ebd4f0` |
| RT-VLM expected manifest | `51d2c0b107fd12fb7a498c416541724edbbd01bf930f5a6b2cb37f6199d4a5ff` |
| API inventory | `e621f0b8a9e8be6fa04535965bdefc17910c6d88284779fc95daafeb4f66c482` |
| Official capability ledger | `fb80c2a96cc0951fc770b59a77c96d303fcf7c359e27201e16b1923e1a54a371` |
| Canonically generated oracle ledger | `4cfaa1996b6a46a1888035af773f444e505324c9edada2fee387c0399d9788ec` |
| Layered current-contract artifact | `cb3e1e2b15374a9a2a60715a475aaae055b4564f73b59987a0ca34b6ae454a59` |

Offline validation results:

- qualification contract: 17 surfaces, 330 declared REST operations, 329
  normalized unique REST operations, 42 MCP tools, and five MCP prompts;
- official capability ledger: 126 sources and 289 capabilities;
- capability oracle generator: 289 canonical oracles;
- layered transition: three capability records, three oracle records, 11
  official semantic pointers, and 21 oracle semantic pointers;
- focused successor tests: eight passed;
- current qualification contract tests: 15 passed.

The package forbids network, Docker, and service access. Runtime evidence and
`passed_current` promotions remain zero. The Warehouse sample bundle remains
excluded.
