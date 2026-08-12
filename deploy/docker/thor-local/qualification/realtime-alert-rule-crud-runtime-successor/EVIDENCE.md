# Evidence

The retained live-Thor run completed in 29,437 ms. Invalid source and empty-prompt requests returned validation failures without changing rule, stream, persistence, or incident state. PATCH against an unknown rule returned an explicit unsupported/not-found result and did not create a rule.

The candidate then created an initial rule and its replacement on one owned local RTSP source. GET and list returned stable, distinct rule UUIDs and unchanged prompt/category configuration while hiding the internal stream/request bookkeeping. Elasticsearch retained two distinct RT-VLM request UUIDs bound to one shared stream UUID.

Deleting the superseded rule canceled its exact RT-VLM request. A repeated delete returned explicit not-found, the old rule was absent, and the replacement remained the sole active rule on the still-running shared stream. After that deletion, the replacement produced a genuine RT-VLM `Yes` result, Kafka incident, and Elasticsearch record carrying the replacement rule, request, stream, sensor, and category identities.

The replacement rule, one owned incident, UUID-derived raw-events index, and publisher were removed. Public rules, persisted rules, RT-VLM streams, all pre-existing incidents, and the 38-container running set had identical before/after digests. Disk free space remained above 20.6 GB. No external endpoint, Warehouse sample, or VSS Agent `/generate` call was used; the receipt retains hashes rather than raw URLs or runtime UUIDs.
