# Thor LVS custom-model and custom-prompt runtime qualification

This package proves the NVIDIA VSS 3.2.1 LVS custom-model configuration and
compatible prompt-override contract on Thor. It binds the official FAQ claim to
the current source, renders a non-default `vllm-compatible` model selector and
checkpoint beneath `MODEL_ROOT_DIR`, and proves the same model root reaches
both LVS and RT-VLM with a read-only same-path RT-VLM bind. The live path then
checks the exact pinned local Cosmos3 model, LVS OpenAPI prompt fields, invalid
model rejection, and a real compatible `override_vlm_prompt` summary.

Execution is inert unless the exact acknowledgement in `contract.json` is
provided. The executor uses numeric loopback only, never calls the VSS Agent,
never registers RTSP, never stages a model, never starts or stops a service,
and excludes the Warehouse bundle. It uploads one fixed qualifier-owned file
and deletes only that file, including on the recovery path.

```bash
python3 deploy/docker/thor-local/qualification/lvs-custom-model-prompt-runtime/execute.py plan

python3 deploy/docker/thor-local/qualification/lvs-custom-model-prompt-runtime/execute.py \
  execute \
  --ack I_ACK_LVS_CUSTOM_MODEL_PROMPT_AND_EXACT_CLEANUP \
  --retain

python3 deploy/docker/thor-local/qualification/lvs-custom-model-prompt-runtime/verify.py
```

The checked-in receipt retains only hashes, sizes, model/configuration identity,
status codes, counts, booleans, and durations. Prompt text, generated summary
text, request IDs, dynamic asset IDs, URLs, credentials, SDP, and ICE are not
retained.
