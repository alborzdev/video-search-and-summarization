# LVS Prometheus metrics runtime qualification

This package proves official row 304 against the deployed Thor LVS service.
It snapshots `/metrics`, uploads one owned checked-in H.264 fixture, completes
one `/generate_vlm_captions` request with the local Cosmos model, snapshots
metrics again, and removes the owned file.

Acceptance requires Prometheus parser compatibility, exactly one increment in
the processed-query gauge and six VLM request/latency/processing histogram
counts, a zero pending gauge after completion, positive latest-latency gauges,
and no resource-ID label cardinality. File, graph, runtime, and running-container
baselines must be restored exactly.

```bash
python3 deploy/docker/thor-local/qualification/lvs-prometheus-metrics-runtime-successor/harness.py \
  --ack I_ACK_ONE_OWNED_LVS_FILE_AND_ONE_LOCAL_VLM_CAPTION_REQUEST
python3 deploy/docker/thor-local/qualification/lvs-prometheus-metrics-runtime-successor/verify.py
python3 -m pytest -q \
  deploy/docker/thor-local/qualification/lvs-prometheus-metrics-runtime-successor/tests/test_package.py
```
