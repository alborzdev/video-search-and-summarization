# Evidence

The retained run completed in 23,134 ms against the live Thor stack. One declared domain-neutral rule activated for the owned camera. Duplicate events before and after restart returned the explicit already-active result without creating another RT-VLM worker.

The worker oracle observed cumulative create/remove counts `1/0`, `1/0`, `2/1`, `2/1`, and `2/2`. Thus the Alert Bridge restart replay replaced the one surviving worker exactly once, maintained one active worker, and the final camera removal left zero. The lifecycle also removed the owned RT-VLM stream.

Public rules, persisted rules, and RT-VLM streams had identical unrelated-state digests before and after. The same 38-container running set remained present, the publisher stopped, the Alert Bridge returned healthy after restart, and no Agent `/generate` call or external network endpoint was used. The receipt retains only hashes for runtime identities and no raw URLs or UUIDs.
