# Evidence

- Capabilities: `manifest-entry.rt-vlm-media.00-file-upload` and `manifest-entry.rt-vlm-media.06-dense-captions`
- Surface: live OpenAPI, `/v1/files`, exact content readback, `/v1/generate_captions`, and `/v1/models`
- Positive: deterministic file digest, stable owned identity, exact content readback, three ordered 3-second captions with planted phase markers
- Adjacent controls: corrupt bytes allocate no asset; chunking disabled returns one full-file chunk
- Cleanup: exact owned-file deletion, complete catalog restoration, unchanged model set
- Policy: direct loopback only; zero Agent `/generate`, stream, or lifecycle operations; Warehouse sample excluded

The schema-valid sanitized live result is retained as `runtime-receipt.json`.
