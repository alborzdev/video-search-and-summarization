# LVS custom-schema runtime successor

This authorization-gated Thor-local qualifier proves the VSS 3.2.1 advertised `structured output` capability through the real `/v1/summarize` API. It generates one small owned MP4, uploads it once, and runs two schema-aware requests against the current local model.

The positive schema requires the standard timestamp/type/description fields plus an unmistakable custom field: `schema_marker="thor-local-schema"`. A pass requires at least one fixture-grounded event with exactly those keys and types. The adjacent negative uses an empty enum and accepts only a parseable non-success response or a parseable HTTP-200 result containing zero events; malformed JSON cannot be labeled successful.

The executor selects NVIDIA's documented custom-schema mode (`enable_vlm_structured_output=false`, `batch_response_method=json_schema`), verifies the deployed container identities and model, exact-deletes the single owned file, restores the complete pre-existing file catalog, and verifies readiness afterward. It never stages a model, restarts a service, calls the Agent `/generate` endpoint, mutates VIOS/RT-CV streams, or uses the Warehouse sample.

```bash
python3 execute.py plan
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_execute.py
python3 execute.py execute --ack I_ACK_LVS_CUSTOM_SCHEMA_AND_EXACT_FILE_CLEANUP
```

Runtime output contains only hashes, counts, status codes, and booleans. Raw resource IDs, prompts, and semantic output are never retained.
