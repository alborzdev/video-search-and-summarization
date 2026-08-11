# RT-VLM reasoning runtime successor

This package closes `manifest-entry.rt-vlm-media.09-reasoning` with direct current-Thor evidence from the local RT-VLM OpenAI-compatible API. It does not call VSS Agent `/generate`.

The executor generates two deterministic six-second MP4s in a temporary directory. In the target clip the blue square moves while the red square is static; the adjacent-negative clip mirrors that behavior. Both receive the same temporal question with `enable_reasoning=true`. Admission requires the exact advertised local model, a reasoning signal, the correct opposite final conclusions, and removal of the reasoning block before the semantic oracle runs.

The receipt retains only hashes, counts, and booleans. It never retains the prompt, media data URI, raw response, chain-of-thought, or raw response identifiers. No stream, database, container, service, or persistent media resource is mutated.

Safe inert validation:

```bash
python3 deploy/docker/thor-local/qualification/rt-vlm-reasoning-runtime-successor/execute.py plan
pytest -q deploy/docker/thor-local/qualification/rt-vlm-reasoning-runtime-successor/tests/test_execute.py
```

Bounded live execution:

```bash
python3 deploy/docker/thor-local/qualification/rt-vlm-reasoning-runtime-successor/execute.py execute \
  --ack I_AUTHORIZE_BOUNDED_RT_VLM_REASONING_RUNTIME
```
