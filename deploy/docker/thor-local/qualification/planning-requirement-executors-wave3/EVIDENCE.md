# Evidence

- Total planning requirements: **110**
- Integrated/materialized requirements: **27**
- Open planning requirements audited: **83**
- New isolated source cases: **6**
- Existing 10 + 16 source cases overlapped: **0**
- Observed matches: **5**
- Observed mismatches: **1**
- Requirements deliberately left open without a Wave 3 candidate: **77**
- Runtime evidence added: **0**
- Live acceptance/oracle changes: **0**

The sole mismatch is `systems-search-content-type`: the locked planning contract
expects HTTP 400 for both missing and unsupported Content-Type, but
`services/agent/src/vss_agents/api/video_search_ingest.py` returns 415 for the
unsupported case. This package records that discrepancy without changing either side.
