# Source-contract tranche evidence

Evidence class: `deterministic_file_static_evidence_not_runtime`.

Current second-successor result:

- candidate materialized/executor-ready: 16/16
- new live materialized/executor-ready: 16/16
- cumulative live materialized/executor-ready: 26/26; 84 open
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
  `7c9d65fee42f0f6089ec705972ae900a001ab68eaafad23d3c983425b305fe7f`
- raw `inventory.schema.json` SHA-256:
  `8cf3261a8785d376af2d9bd1b9b5a4216e06f5408cb724af0db485ad2091f81f`
- raw `result.schema.json` SHA-256:
  `ed542c6c39a2bcf9e754cada2d6b7d4114019dbeaa3a14789f907ca3c6d4fcd0`

Every assertion source has an exact SHA-256 lock in `inventory.json`. The
executor verifies those locks before evaluating assertions and re-hashes every
read source after evaluation.
