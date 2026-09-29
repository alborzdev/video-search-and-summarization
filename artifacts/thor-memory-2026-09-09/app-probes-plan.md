# Minimal current-app probes — 2026-09-09

Read-only plan extracted from current source. No inference/upload/delete calls were executed. Use new owned filenames/UUIDs and a new evidence directory. This avoids historical source-locked exhaustive harnesses. Before requests, GET current `/openapi.json` and confirm schemas against this plan; runtime images may lag the mounted source.

## Agent tool execution without a live source

POST `http://127.0.0.1:8100/generate`, JSON:

```json
{"input_message":"Call vst_video_list to list the currently available recorded videos. Do not inspect or summarize footage. Report the returned names, or say no recordings if the tool returns none."}
```

Allow up to 180s, use a fresh request without conversation history. This is the real payload used by the UI's generate adapter. `vst_video_list` is in the Thor top-agent tool allowlist and queries media inventory; an empty inventory is a valid outcome. It requires VIOS reachable but no active video/RTSP source.

A prompt cannot mathematically force an LLM to call a tool. **Pass only if it actually does:** capture the bounded Agent log interval and require `Executing tool/sub-agent: vst_video_list`, a completed matching tool trace/result, and final text consistent with that result. The top agent logs execution and emits TOOL_START/TOOL_END telemetry; `/generate/stream` with the same body is an alternative for capturing configured tool events directly. HTTP200/fluent list alone is insufficient. No source or report creation should occur, and unrelated catalogs must remain unchanged.

Sources: [UI payload](../../services/ui/packages/nemo-agent-toolkit-ui/pages/api/chat.ts), [top-agent execution](../../services/agent/src/vss_agents/agents/top_agent.py), [Thor tool list](../../deploy/docker/developer-profiles/dev-profile-thor-full/vss-agent/configs/config.yml).

## Fresh 25-second file through upload → embeddings → indexed search

Use a 25-second known-content local H.264 MP4 with distinctive visually verified content and no whitespace in its unique filename, e.g. `thor-memory-probe-<runid>.mp4`. Do not call a 10-second fixture25 seconds or fabricate semantic expectations. Record actual duration/hash and a brief ground-truth description. Choose `semantic-search` for the smallest complete ingestion/search path; this skips detection. A later `warehouse`/traffic profile test must separately exercise CV using the exact current profile IDs from `/api/v1/analysis-profiles` or source.

1. POST Agent `/api/v1/videos` with `{"filename":"thor-memory-probe-<runid>.mp4"}`. Read returned `url`; it resolves to the configured VST ingress `/vst/api/v1/storage/file`.
2. POST multipart to that URL with fields `mediaFile` (file bytes, filename), `filename`, and `metadata` containing a valid timestamp JSON such as `{"timestamp":"2026-09-09T12:00:00"}`. For a single-chunk small video use headers:

```text
nvstreamer-chunk-number: 1
nvstreamer-total-chunks: 1
nvstreamer-is-last-chunk: true
nvstreamer-identifier: <unique-upload-id>
nvstreamer-file-name: thor-memory-probe-<runid>.mp4
```

For a larger file reproduce the UI's sequential numbered chunk protocol with identical identifier and only the final chunk marked true. Preserve the final response's **sensorId**, not the filename, as the owned resource ID.
3. POST Agent `/api/v1/videos/<sensorId>/complete` with JSON `{"filename":"thor-memory-probe-<runid>.mp4","analysisProfileId":"semantic-search"}`. This call performs timeline/storage resolution then synchronous RT-Embed file generation, using 5-second chunks and the sensor ID as the Kafka routing key. Allow at least the current 600-second embedding timeout; do not launch a duplicate complete call merely because generation is still running. Expect positive generated chunk count and successful response. Roughly five chunks are expected for exactly25 seconds, but validate actual timeline/end-chunk behavior rather than assuming frame rounding.
4. Poll Agent `/api/v1/embed_search` every 2–5 seconds for up to 120 seconds using the exact query below. This generates a fresh text embedding and reads the real index, avoiding synthetic vectors/documents and avoiding LLM query rewriting:

```json
{
  "source_type":"video_file",
  "params":{
    "query":"<visually verified distinctive description>",
    "video_sources":"[\"<sensorId>\"]",
    "top_k":"5",
    "min_cosine_similarity":"0.0"
  }
}
```

`params` values are **strings**. `video_sources` supports a JSON-array string; a UUID is filtered against `sensor.id.keyword`. Pass when nonempty results name the owned sensor, timestamps map into its25-second archive, similarity values are finite, and playback/clip resolution works. Compare a second clearly unrelated query and inspect rankings; a filtered nonempty result alone proves plumbing but weak semantic quality. Polling success is stronger than only positive embedding counts because Kafka→Logstash→Elasticsearch is asynchronous.
5. DELETE Agent `/api/v1/videos/<sensorId>` only for the captured owned ID. This removes VST sensor/storage and sensor-scoped ES documents and CV registrations where configured. Check returned overall status: deletion is best effort and can report `partial`/`failure`. Poll scoped search/index and VIOS inventory until absent; delayed Kafka writes mean immediate absence is not enough. Never delete the whole embedding index. If complete fails, still perform owned upload cleanup because the VST file may remain.

Sources: [upload handshake/complete](../../services/agent/src/vss_agents/api/video_ingest.py), [chunk headers](../../services/ui/packages/common/lib-src/utils/chunkedUpload.ts), [search schema](../../services/agent/src/vss_agents/tools/embed_search.py), [delete semantics](../../services/agent/src/vss_agents/api/video_delete.py).

## LVS file summary with both local models

Use the same25-second local file but create a separate owned LVS ID; it is a separate resource lifecycle from Agent/VIOS upload. Snapshot `GET http://127.0.0.1:38111/files`. POST multipart to LVS `/files` with `purpose=vision`, `media_type=video`, `id=<new UUID>`, `sensor_name=<unique name>`, and `file=<MP4 bytes with filename>`. Require returned ID match and retain it.

POST LVS `/v1/summarize`:

```json
{
  "id":"<owned LVS UUID>",
  "model":"nim_nvidia_cosmos3-nano-reasoner_bf16-final",
  "prompt":"Describe the visible actions in chronological order. Include the beginning and ending events and do not invent objects.",
  "chunk_duration":5,
  "max_tokens":128,
  "temperature":0.0,
  "top_p":1.0,
  "seed":1,
  "override_vlm_prompt":true,
  "enable_vlm_structured_output":false,
  "enable_qa":false
}
```

This is derived from the previously successful current-model request but removes fixture-specific asserted events. Allow up to 300s for five chunks plus aggregation. Require `object=summarization.completion`, nonempty `choices[0].message.content`, positive `usage.total_chunks_processed`, `summary_requests` and `summary_tokens` proving LLM aggregation, and semantically correct beginning/end events. If a client timeout leaves a running job, inspect status before retrying; do not overlap duplicates. `enable_qa=false` avoids retaining an unnecessary QA context for the memory test.

Finally DELETE LVS `/files/<owned LVS UUID>`, require `deleted=true`, verify baseline catalog restoration and absence of owned graph nodes. Repeat 3–5 times sequentially with fresh owned IDs and log memory after completion/cleanup; growth across jobs is a separate failure even if each request returned200. `/generate_vlm_captions` with the same basic fields can be used first to isolate the VLM-only portion if summary fails.

Source: [successful request and cleanup implementation](../../deploy/docker/thor-local/qualification/lvs-file-caption-summary-runtime-successor/harness.py), [multipart fields](../../deploy/docker/thor-local/qualification/lvs-recommended-config-runtime-successor/harness.py).

## 16K Nemotron context and concurrency risks

The active consumer family `vllm_llm` defaults to `LLM_MAX_TOKENS=2048`; several specialized models use 4096, LVS aggregation defaults 1024, and classifier branches 256. None of these configured output limits alone exceed16K. They are **output budgets**, so a 4096-output request has at most 12288 tokens left for prompt/tool definitions/history under a 16K server limit (2048-output leaves14336).

The top agent permits30 iterations and10 history entries, with planning enabled. Full tool schemas, accumulated tool results and media/analytics inventories can exceed the16K combined prompt+output limit; no guarantee of truncation to the new server bound was established in the inspected config. Keep this first inventory prompt fresh and concise, inspect returned token/error metrics, and verify that larger real report/search traces remain within budget. Do not silently clip tool results to claim success.

One sequence means inference queues; it does not mean only one consumer can send requests. Agent planning, execution, response formatting, LVS and alert/analytics LLM calls can contend. Keep probes sequential first, then perform a deliberately bounded overlapping workload to distinguish memory fit from unacceptable timeout/latency. Request-side `max_tokens` passed to LVS primarily bounds VLM chunk output; the LLM aggregation cap comes from LVS configuration.
