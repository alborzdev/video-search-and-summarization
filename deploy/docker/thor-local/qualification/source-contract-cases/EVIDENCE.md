# Source-contract tranche evidence

Evidence class: `deterministic_file_static_evidence_not_runtime`.

Current isolated result:

- candidate materialized/executor-ready: 16/16
- live materialized/executor-ready: 0/0
- outcomes: 15 `observed_match`, 1 `observed_mismatch`
- runtime evidence: 0
- capability advancement / `passed_current`: 0 / 0
- maximum observed bound: 8 files and 1,410,135 bytes in one case

The sole mismatch is
`source-contract-case.nvstreamer-full-config`. The official reference defaults
and the checked-in Thor-effective VIOS configuration differ at:

| Assertion | Official reference | Checked-in local value |
|---|---:|---:|
| RTSP port | 8554 | 30554 |
| RTSP instances | 8 | 10 |
| maximum upload MB | 10000 | 25600 |
| HTTPS enabled | true | false |

Session age remains equal at 2,592,000 seconds. These observations establish
static configuration drift only; they do not decide whether the overrides are
operationally correct or prove VIOS runtime behavior.

Package locks:

- canonical `inventory.json` SHA-256:
  `7b1df3c87148a1539e3035cda28755f7946174636a992db1dfb6b87f6f17f593`
- raw `inventory.schema.json` SHA-256:
  `9a5e9a6d3e41070b6c2d455c7b645318b1f9d1b874395aeaeba9b054ff65fc37`
- raw `result.schema.json` SHA-256:
  `87709030a4d00b1d3995688f69b604f37c95c18b9aa32d9d56039a993491ce5a`

Every assertion source has an exact SHA-256 lock in `inventory.json`. The
executor verifies those locks before evaluating assertions and re-hashes every
read source after evaluation.
