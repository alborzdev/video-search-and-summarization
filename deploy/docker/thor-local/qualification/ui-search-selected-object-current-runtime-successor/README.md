# Current UI selected-object Search qualification

This package closes the remaining browser gap for `runtime.ui.search-tab` on
the Thor-local VSS 3.2.1 profile. It drives the production UI through Search,
recorded-video filtering, semantic result playback, Search by Image, canvas
bounding-box selection, and the resulting object-level KNN search.

The default command is inert:

```bash
python3 executor.py plan
node harness.mjs plan
```

An authorized live run uses the fixed receipt location and a plain run ID:

```bash
python3 executor.py execute-http \
  --run-id thoruisearchYYYYMMDDa \
  --ack I_ACK_UI_SEARCH_SELECTED_OBJECT_CURRENT_RUNTIME_AND_EXACT_INDEX_CLEANUP
```

The executor first verifies the sealed backend Search package. It then creates
only the otherwise-absent fixed behavior/raw index pair, captures their UUIDs,
writes two behavior segments and one two-object raw frame, and launches an
isolated codec-enabled Chromium already installed on Thor. Browser traffic is
restricted to numeric loopback, ambient proxies are omitted, redirects and
external requests are rejected, and no browser download is permitted.

The UI uses a real existing recorded VST source. The qualification requires an
actual MP4 metadata load with positive duration, a real VST picture response,
a real video-analytics `/frames` response, the expected 1280×720 canvas and two
boxes, a click inside the reference box, and an exact selected-object request.
The response must contain only the candidate, exclude the seed, retain the
human-facing source name, and rerender one result card without page, console,
HTTP, framework-overlay, or external-network errors.

Cleanup is fail-closed. An index is deleted only when its UUID and complete
document-ID inventory match the executor-owned set. Both fixed indices must be
absent twice afterward, the frame query must be empty, the pre-existing embed
index must be unchanged, the browser and temporary screenshots must be gone,
and all seven related container lifecycle snapshots must match.

The executor never calls VSS Agent `/generate`, changes a sensor or stream,
changes service lifecycle state, accesses the warehouse sample bundle, or
retains prompts, vectors, URLs, responses, credentials, or runtime IDs.

Validate the sealed package offline with:

```bash
python3 verify.py
pytest -q tests
```

See `EVIDENCE.md` and `official-runtime-evidence.json` for the retained result.
