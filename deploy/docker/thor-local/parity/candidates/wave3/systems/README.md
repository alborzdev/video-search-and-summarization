# VSS 3.2.1 Wave-3 systems candidate

This isolated candidate captures the omitted VSS 3.2.1 system, broker/schema,
observability, performance, release-note, and FAQ semantics. It does not edit or
merge the live capability ledger, parity manifest, acceptance inventory,
capability oracles, shared wrapper, or source lock.

Exact payload counts:

| Record | Count |
| --- | ---: |
| Official 3.2.1 sources | 23 |
| Proposed capabilities | 55 |
| Existing-capability enrichments | 19 |
| Discrepancies and support boundaries | 18 |
| FAQ duplicate groups | 4 |
| FAQ external/non-Thor groups | 5 |
| Performance fixture requirements | 7 |

The reviewed sources are exactly 14 system pages, seven performance pages,
`release-notes.html`, and `faq.html`. `release-notes-ver-2.html` is outside this
candidate. The approximately 100 GB Warehouse sample bundle remains excluded.

## Package layout

- `candidate.json` is the complete machine-readable extraction.
- `candidate.schema.json` is a strict Draft 2020-12 schema.
- `validate_candidate.py` pins exact source and claim sets, current enrichment
  targets, live scenario membership, FAQ classification, and fail-closed
  benchmark boundaries.
- `evidence/broker-topic-contracts.json` preserves the 18 Kafka and 16 Redis
  contracts without claiming broker equivalence.
- `evidence/nvstreamer-config-contract.json` preserves exact key defaults as a
  documentation contract, not observed runtime state.
- `evidence/performance-reference-contracts.json` preserves source-table cross
  checks and requires every official row to be transcribed into the eventual
  reference fixture. It explicitly sets `thor_results=false`.
- `evidence/2026-07-31-systems-extraction.md` records extraction decisions,
  source inconsistencies, release-note grouping, and merge boundaries.

## Performance boundary

All seven performance records enrich existing capabilities. Official benchmark
hardware, models, concurrency, latency, throughput, and utilization are
reference data only. Thor remains `partial/not_qualified` until a separate
local execution fixture remeasures the same contract. AGX Thor rows published
by NVIDIA are still official reference rows, not evidence from this machine.

The package preserves these source inconsistencies instead of resolving them:

- Alert Spark prose says sub-second, while the table reports 1.25 seconds.
- Alert H100 rows are explicitly VSS 3.1.
- Performance test scopes say VSS 3.2, not a distinct 3.2.1 rerun.
- LVS and RT-VLM name Cosmos3 Nano in test configuration and CR2-8B elsewhere.

## Validation

Run from the repository root:

```bash
python3 deploy/docker/thor-local/parity/candidates/wave3/systems/validate_candidate.py --report
python3 -m unittest discover \
  -s deploy/docker/thor-local/parity/candidates/wave3/systems/tests -v
ruff check deploy/docker/thor-local/parity/candidates/wave3/systems
```

Validation is offline and does not start services or retrieve documentation.
