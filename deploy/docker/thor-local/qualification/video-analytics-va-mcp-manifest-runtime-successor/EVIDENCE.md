# Video Analytics and VA-MCP runtime evidence — 2026-08-11

PASS. The released Video Analytics API has retained live Thor evidence for all
56 operations (48 GET, eight POST), with 40 non-empty data-bearing GETs, eight
successful POST workflows, eight adjacent-negative POSTs, zero HTTP 5xx, and
exact cleanup. The optional-Kafka instance proved ordinary Elasticsearch reads
with no broker and the documented HTTP 422 contract for a Kafka-required path.

The currently deployed `vss-va-mcp` service was then exercised over loopback.
It was healthy on the immutable VSS 3.2.1 Agent image, advertised nine tools,
and all eight read-only tools completed using a fresh response-header session
for every call. It returned three matching VA/VST sensors, three current
incidents, the exact first incident, FOV histogram, average-speed, and analysis
responses. Docker's running set and VST's sensor set remained exact. No Agent,
stream mutation, Warehouse data, or external request was involved.
