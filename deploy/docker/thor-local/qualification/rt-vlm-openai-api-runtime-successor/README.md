# RT-VLM OpenAI-compatible API runtime successor

This bounded current-Thor qualifier proves six exact VSS 3.2.1 advertised rows through the direct loopback RT-VLM service: OpenAI-compatible chat completions, text-only chat, multimodal multi-turn chat, token SSE, complete file CRUD, and health/metadata/models/metrics.

The deterministic text oracle must return one exact marker in both non-streaming and token-streaming modes, with SSE deltas reconstructing the non-streaming content byte-for-byte. A nine-second blue/green/red fixture proves ordered multimodal understanding and a referential follow-up. File create/list/get/content/delete plus post-delete unavailability are exercised around that same asset. Health, release metadata, manifest model identity, model inventory, and parseable Prometheus metrics are checked before exact cleanup.

The executor is inert by default. The acknowledged live mode is limited to 25 loopback requests and four model calls. It never calls VSS Agent `/generate`, mutates a stream, restarts a service, accesses the Warehouse sample, or retains prompts, generated text, or raw resource/request IDs.

```bash
python3 deploy/docker/thor-local/qualification/rt-vlm-openai-api-runtime-successor/execute.py plan
pytest -q deploy/docker/thor-local/qualification/rt-vlm-openai-api-runtime-successor/tests/test_execute.py
python3 deploy/docker/thor-local/qualification/rt-vlm-openai-api-runtime-successor/execute.py execute \
  --ack I_AUTHORIZE_BOUNDED_RT_VLM_OPENAI_API_RUNTIME
```
