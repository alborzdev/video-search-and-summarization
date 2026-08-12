# Evidence

The retained live-Thor run completed in 26,476 ms. One bounded local RTSP
fixture produced one genuine RT-VLM incident carrying the created alert-rule
UUID, RT-VLM stream UUID, requested sensor UUID, alert category, frame
references, and LLM query evidence.

Four candidate-owned Elasticsearch controls independently violated the stream,
sensor, category, or time bound. The one Alert Bridge request that combined
rule, stream, sensor, category, start-time, and end-time returned only the real
generated incident. A valid unknown rule returned zero results and a malformed
rule UUID returned HTTP 422.

The owned rule, stream, incident, four controls, and publisher were removed.
Public rules, persisted rules, RT-VLM streams, all pre-existing incidents, and
the 38-container running set had identical before/after digests. No external
endpoint, Warehouse sample, or VSS Agent `/generate` call was used. The receipt
retains hashes rather than raw URLs or runtime UUIDs.
