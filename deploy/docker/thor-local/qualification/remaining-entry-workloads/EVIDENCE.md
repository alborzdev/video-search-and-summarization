# Candidate workload evidence boundary

This package is workload-planning evidence, not runtime evidence. It locks the
complete reviewed candidate artifact plus its API/deployment source inventories,
manifest, and official capability ledger. Every workload remains unexecuted.

| Artifact | Raw SHA-256 |
| --- | --- |
| 211-candidate artifact | `a3c1b793f976fa384fb4ea588602f225e21c9d2d1fd563f12c0aadfa9d1a56fd` |
| API inventory | `07087f97a00721e8a47d399a3a14275fa28bd47439d4ba955563f59ef7bc4b77` |
| Deployment inventory | `14b8087d963341343bd1b4977f196406b0b26d7e267e3d944632c3adcac2ccd8` |
| Manifest | `1f56d63437bd7742cf7488b9bd85b25fc886cdaf39a3c2b46aabecbc6b7201ce` |
| Official capabilities | `cde0dc3981aaf699a017c7108089aac72070101edc47a06489f3940e44fe52a0` |
| Workload schema | `736f9295e4f89afbb1aaed7c086155e30a09b6dc2c583433b9cb98ad2c005c14` |
| Compiled workloads | `ca4170118a94a659acca600d9ab00dca6504544f062edabd5cef0ed3311e8312` |

Compiled payload SHA-256:
`0e8512e64399af7d8acc0c7136efbd52da4ebf9119ad0826859e6fce6906d847`.

The deterministic denominator is 60 workloads: 41 API and 19 deployment,
with 134 API units and 58 deployment actions. Candidate runtime evidence
records, external activations, and Warehouse sample entries are all zero.
