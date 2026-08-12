# Realtime alert incident retrieval runtime successor

This package qualifies official VSS 3.2.1 capability row 332, `incident retrieval`, on the deployed Thor-local stack. It uses the small bundled alert fixture and a uniquely owned local RTSP path; the excluded warehouse sample is not used.

The harness creates one real rule and waits for RT-VLM to produce a Kafka/Elasticsearch incident carrying that rule UUID. Four owned control records independently violate the stream, sensor, category, or time bound. A single Alert Bridge query supplies rule, stream, sensor, category, start-time, and end-time filters and must return only real generated records with stable identities and evidence references. A valid unknown rule must return zero, and a malformed UUID must be rejected. The harness removes only its rule, stream, incidents, and publisher, then proves exact unrelated state and the running-container set were restored.

Run only when no realtime rules or RT-VLM streams are active:

```bash
python3 deploy/docker/thor-local/qualification/realtime-alert-incident-retrieval-runtime-successor/harness.py \
  --ack I_AUTHORIZE_OWNED_REALTIME_INCIDENT_RETRIEVAL \
  --contract deploy/docker/thor-local/qualification/realtime-alert-incident-retrieval-runtime-successor/contract.json \
  --fixture services/alert/warmup/test.mp4 \
  --output deploy/docker/thor-local/qualification/realtime-alert-incident-retrieval-runtime-successor/runtime-receipt.json \
  --run-id local-rerun
```

Verify retained evidence with `python3 deploy/docker/thor-local/qualification/realtime-alert-incident-retrieval-runtime-successor/verify.py`.
