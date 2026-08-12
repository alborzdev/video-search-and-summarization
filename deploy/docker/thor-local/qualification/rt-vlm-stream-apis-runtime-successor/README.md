# RT-VLM original and CV-compatible stream APIs

This package qualifies advertised capability rows 351 and 352 against the live
Thor RT-VLM service. It runs one disposable MediaMTX publisher on the existing
Docker network, adds one stream through each API family, verifies both catalog
views, exercises positive and negative removal behavior, and restores the exact
catalog and running-container baselines.

The generated 500-row ledger reverses the endpoint families in its
`required_semantics`: NVIDIA's released source and live OpenAPI define the
original API as plural `/v1/streams/*` and the CV-compatible API as singular
`/v1/stream/*`. The retained evidence follows those authoritative surfaces and
records the ledger defect explicitly.

```bash
python3 deploy/docker/thor-local/qualification/rt-vlm-stream-apis-runtime-successor/harness.py \
  --ack I_ACK_ONE_LOCAL_RTSP_PUBLISHER_AND_TWO_OWNED_RT_VLM_STREAMS
python3 deploy/docker/thor-local/qualification/rt-vlm-stream-apis-runtime-successor/verify.py
python3 -m pytest -q \
  deploy/docker/thor-local/qualification/rt-vlm-stream-apis-runtime-successor/tests/test_package.py
```
