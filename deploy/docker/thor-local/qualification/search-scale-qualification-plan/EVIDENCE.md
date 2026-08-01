# Static evidence boundary

## Established by this package

- nine predecessor/source contracts are raw-SHA-256 locked and checked for
  reviewed semantic fragments;
- the workload denominator is exactly progressive 2, 4, 8, and 16 plus a
  separate operator-approved 100-stream plan;
- one future, operator-owned H.264 loop source must be SHA-256 locked before a
  run and is reused only behind unique publisher/resource identities;
- 130 future stream instances compile to 520 globally unique owned names;
- the 16-stream claim is gated on exact H.264 1920x1080 input and complete
  per-stream evidence;
- a passing stream requires at least 1.0 average FPS and stays within the
  contract's 120s agent-add, 40s DeepStream-active, 120s first-embedding, and
  5s search-query latency ceilings;
- the 100-stream configuration claim rejects configuration-only evidence;
- every phase carries a 3 GiB available-memory floor, the exact nine-service
  health floor, all-publisher/all-source floors, zero failed streams, immediate
  abort, and no advancement after abort;
- future progressive evidence is a contiguous 2/4/8/16 prefix whose first
  failure ends the sequence, while the 16-stream claim requires all four phases;
- the separate 100-stream receipt has a distinct run ID, an explicit
  authorization ID, follows a completed successful 2/4/8/16 lane even when the
  100-stream attempt fails, and has a time window disjoint from every
  progressive phase;
- phase evidence IDs are derived from the exact run and stream count, and a
  qualified claim must list exactly its supporting phase IDs;
- future evidence has a strict schema covering correctness, latency, resource,
  abort, exact-owned cleanup, and claim-decision fields; and
- the compiler imports no activation/network/process library and exposes only
  inert `plan`/`--check` behavior.

Focused static checks:

```text
30 passed
```

## Not established

No publisher, RTSP source, API request, container, model, Elasticsearch index,
or VSS service was started, queried, changed, or cleaned up. No operator media
exists in this package, no Warehouse sample was used, and no 2-, 4-, 8-, 16-,
or 100-stream runtime was executed. The source locks and compiled names do not
prove correctness, latency, throughput, resource headroom, 1080p operation, or
cleanup under load.

The existing `thor-capacity-check.sh` remains evidence only for its historical
bounded 1-to-2 stream run and is not invoked here. Both advertised Search scale
gaps remain open with no new runtime evidence or `passed_current` promotion.
