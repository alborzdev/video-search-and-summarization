# Evidence

The retained live-Thor run passed in 77,017 ms. One natural-language rule asked the local Cosmos 3 Nano Reasoner whether the dominant full-frame color in each current four-second RTSP window was green. Across one complete 36-second visual cycle, the model returned `No, No, No, No, Yes, Yes, Yes, No, No`: exactly three cyclically contiguous matches for the twelve-second green phase and six non-matches for the blue/red phases.

The three matching chunks set `incidentDetected=true` and produced exactly three Elasticsearch incidents. All six non-matching chunks set `incidentDetected=false` and produced no incident. Every incident retained the exact rule, RT-VLM request, stream, sensor, category, and chunk identities.

The deployed run also proves the Thor stream-registration fix: Alert Bridge uses a bounded 60-second timeout for RT-VLM RTSP validation, preventing its former 10-second timeout from rolling back while RT-VLM completed and left an orphan stream.

Cleanup removed the owned rule, three incidents, raw-events index, stream, and publisher. Public rules, persisted rules, streams, all pre-existing incidents, and the 38-container running set had identical before/after digests. Disk free space remained above 20.7 GB. No external endpoint, Warehouse sample, or Agent `/generate` call was used; retained identities and prompt configuration are hashes.
