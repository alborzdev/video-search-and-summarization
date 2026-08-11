# Search upload Content-Type current-runtime qualification

This package proves `behavior.search-upload.content-type` against the live VSS
3.2.1 Search profile on Thor. It exercises the deployed deprecated compatibility
route because that is the route named by NVIDIA's documented Search upload MIME
contract; new application code should continue to use the universal three-step
ingest flow.

The bounded executor:

- generates one two-second H.264 MP4 and one two-second H.264 Matroska fixture;
- uploads both through `PUT /api/v1/videos-for-search/{filename}`;
- requires VST sensor materialization, `chunks_processed >= 1`, and an exact
  sensor-ID embedding document for each accepted type;
- requires both a missing header and `application/octet-stream` to return HTTP
  400 before any upload;
- deletes only the two generated qualification videos; and
- requires namespace absence, exact sensor/file inventory restoration, and
  unchanged container identity/health/restart state.

All HTTP targets are fixed loopback addresses. The executor excludes the
Warehouse sample bundle and retains hashes rather than sensor IDs, names, URLs,
media, or raw responses.

Run the bounded transaction with:

```bash
python3 executor.py \
  --ack I_AUTHORIZE_SEARCH_CONTENT_TYPE_RUNTIME_AND_EXACT_CLEANUP
```

Validate the sealed receipt offline with:

```bash
python3 verify.py
pytest -q tests
```

See `EVIDENCE.md`, `runtime-receipt.json`, `official-runtime-evidence.json`, and
the validator-shaped `canonical-runtime-evidence.json` for the retained result.
