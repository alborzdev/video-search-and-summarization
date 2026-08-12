# Evidence

The retained run binds the live LVS `/metrics` route to one bounded successful
local-model request. Prometheus text is parsed before and after with the official
Python client parser. The completed-query gauge and six VLM histogram counts
each advance exactly once; the pending gauge returns to zero and latest latency
gauges are positive. No metric exposes a request, video, file, asset, stream,
camera, sensor, candidate, or generic resource ID label.

The fixture is checked in, the model and endpoints are local, and one API-owned
file is deleted after the call. Exact file-catalog, Neo4j node/relationship,
LVS container, and running-container baselines are retained. The receipt stores
hashes rather than its UUID, prompt, or semantic output.
