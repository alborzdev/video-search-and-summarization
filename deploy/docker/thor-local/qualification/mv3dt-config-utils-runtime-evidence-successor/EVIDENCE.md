# MV3DT config-utils evidence boundary

The executor binds the current 3.2.1 capability and oracle rows, exact source
and fixture hashes, target commit `7732edf8fb38ef896b20f2a0a6a701a4db10dc57`,
and the separate 500-row executor-ready oracle projection. The projection keeps
the embedded `wave3_acceptance.materialized` and `executor_ready` values false;
those historical planning fields are observed exactly and are not rewritten as
execution authority. Readiness exists only in the oracle envelope.

The historical `offline-mv3dt-tools` receipt remains corroborating candidate
evidence and is never promoted or modified by this package.

Development execution against projection SHA-256
`53fe977aa208cdc78604e214817dac7d3683edea4402b160b9d3cf46571b49e3`
passed both capabilities with two deterministic positive runs, five adjacent
negatives, seven target actions/requests per capability, three bounded pub/sub
supporting fixture-generation actions (17 total actions and 14 requests), exact
namespace cleanup, six supporting argument-parser calls, 23 literal imported
source-function invocations, and all zero
prohibited-operation counters. Development output is intentionally
non-promoting and contains no official receipt objects.

The imported-call counts are observed through wrappers (parser 7, camInfo
generator 9, pub/sub generator 7), and product calls run under the oracle's hard
900-second signal deadline. Canonical official receipts retain their exact
verifier-required schema; the adjacent outer runtime binding supplies the
executor/contract/oracle, capture-time, action/request, run/output, negative-set,
and full row digests that the canonical nested schema cannot accept. Output is
published exclusively through component-wise non-symlink `openat` traversal.

A checked promotable receipt is intentionally absent until the producer and
projection are committed and the same execution is repeated from a clean
checkout. This prevents an uncommitted executor or planning-only oracle from
authorizing canonical state advancement.
