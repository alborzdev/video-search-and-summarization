# Second-successor evidence — 2026-07-31

Evidence class: `deterministic_file_static_evidence_not_runtime`.

The successor receipt locks and replays the original ten-case receipt before
executing the sixteen source-contract cases against a temporary reconstruction
of that predecessor. The original receipt remains byte-identical with raw
SHA-256
`1548dd1ca0871a24dd0adba231001ee5757e19ddfa6314d4d883656b9e8d432d`
and contract
`2eb1812f8854ef0f03334f68ceadcda64ffbfd166422da253f48c52ec8cdab71`.

Deterministic successor state:

- planning requirements: 110
- materialized/executor-ready: 26/26
- open: 84
- full capability oracles: 276 `planning_index_only`
- bounded static-subset oracle bindings: 26
- full-oracle executor-ready promotions: 0
- runtime-evidence records: 0
- `passed_current` promotions: 0
- new outcomes: 15 match / 1 mismatch
- cumulative outcomes: 23 match / 3 mismatch

The ledger and manifest are byte-identical to the predecessor. The only live
planning changes are sixteen true/true records with non-advancing static
bindings and the successor metadata. The capability-oracle output is
recompiled solely to project those bindings as bounded static subsets.

Successor receipt locks:

- raw SHA-256:
  `ae8716961b6a2ad30680cdf19587bd0578209594b6a39987b704ad2a29a1aad5`
- canonical SHA-256:
  `b1bd743da7511d2034ab0755d458f6b019df493f34c76fe81c9b2af2291a31fa`
- contract SHA-256:
  `1ba9dac99127932ddf8f517e1d87631bd13240fa61b8f360b123c42242f98cb9`
