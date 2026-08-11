# UI selected-object Search current-runtime evidence

Status: **passed current; promotion eligible**

The 2026-08-10 Thor run exercised the real VSS 3.2.1 Search UI in an isolated,
codec-enabled Chromium. The run used 16 browser actions, observed 42 loopback
browser responses, used 35 bounded fixture/cleanup HTTP requests, and performed
nine exact owned mutations.

Runtime-proven browser flow:

- the Search tab rendered with the expected defaults and an exact local
  recorded-video source filter;
- direct semantic Search returned and rendered one fixture-aligned result;
- the playback modal loaded MP4 metadata and reported a positive duration;
- Search by Image fetched a real VST picture and a real video-analytics frame;
- the 1280×720 overlay exposed two selectable boxes;
- the browser clicked the contracted reference-box center and observed the
  selected-object state;
- the UI posted the exact object/sensor/timestamp composite identity with
  Agent mode disabled and the recorded-video source family;
- object KNN returned one candidate, excluded the seed, and rerendered one card;
- the result retained the human-facing camera name instead of exposing its
  internal stream UUID;
- desktop and 390×844 mobile layouts had no horizontal overflow.

The browser recorded 41 HTTP 200 responses and two valid media-range 206
responses. It recorded no console error or warning, page error, failing HTTP
response, unexpected request failure, non-loopback request/response/WebSocket,
or framework error overlay. One media request was predictably canceled when
the selected-object action closed the playback modal; it was classified as an
exact browser `ERR_ABORTED` teardown event, not an HTTP or playback failure.

Cleanup and non-interference proof:

- the two fixed indices were absent before the run;
- each created index UUID and complete document inventory matched before
  deletion;
- both indices were absent in two delayed post-delete checks;
- the video-analytics frame query was empty after cleanup;
- the existing embedding index UUID and document count were unchanged;
- the isolated browser closed and four temporary screenshots were deleted
  after hashing;
- all seven related runtime identities, start digests, restart counters, and
  OOM states matched before and after;
- no sensor, stream, service lifecycle, or warehouse-sample mutation occurred.

The retained receipt passes a strict Draft 2020-12 schema, source and artifact
locks, semantic and cleanup verification, and retention scans. It contains
only hashes, counts, booleans, sizes, status codes, and the bounded similarity;
raw prompts, vectors, bodies, endpoints, credentials, and runtime identifiers
were discarded.

This package supersedes the earlier partial selected-object receipt and is a
sealed dependency of `ui-search-contract-current-runtime-successor`. That
combined package closes `runtime.ui.search-tab`; the sealed backend Search
package independently closes `runtime.agent.search-profile`.
