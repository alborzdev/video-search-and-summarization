# Thor Search UI runtime qualification — 2026-08-10

This note retains the bounded Search-tab runtime evidence collected from the
local VSS 3.2.1 stack on AGX Thor. The run used numeric loopback endpoints and
an existing retained VIOS file sensor. It did not add or remove a VIOS stream,
invoke Agent generation, or call an external inference endpoint.

## Search data path

- VIOS `2.1.0-26.05.4` exposed the retained `pit-POV` file sensor and its exact
  `2025-01-01T00:00:00.000Z` to `2025-01-01T00:00:19.205Z` timeline. A
  read-only historical picture returned a 1280x720 NASCAR pit-stop frame.
- The local RT-Embed service reported
  `cosmos-embed1-448p-anomaly-detection`. Direct video embedding of that
  already-retained VIOS media returned four ordered chunks, each with 768
  dimensions, over the full 19.205-second duration. Those four chunks were
  indexed under the exact `pit-POV` sensor UUID for the Search API.
- Three old `thor-rt-embed-qualification` documents referenced a deleted
  `/tmp/.../test.mp4` and had no corresponding VIOS stream, file, or timeline.
  An exact Elasticsearch delete-by-query removed only those three stale
  qualification documents. It reported three deletions, no failures, no
  timeout, and no version conflicts. A follow-up query found zero stale
  documents and four `pit-POV` documents.

## Browser qualification

The final headless Chromium run started at `2026-08-10T07:39:35.165Z`, took
5,114 ms, and exited successfully. It exercised this coherent flow at
`http://127.0.0.1:3001`:

1. Open Search and inspect the filter defaults.
2. Select the `pit-POV` video source.
3. Search for `race car in a pit stop`.
4. Load the result thumbnail.
5. Open and play the result clip in the video modal.

The sole mutating browser request was `POST /api/v1/search` with
`agent_mode: false`, source type `video_file`, source `pit-POV`, top K 10, and
minimum cosine similarity `-1.00`. No `/generate` request or prohibited
mutation was observed. The response was HTTP 200, 426 bytes, and had SHA-256
`777d6db65e13185ca2fbfc365ef6af3e928cd027865beeab3b43f5c5de8e8b8d`.

The UI rendered one result at similarity 0.2675. Its thumbnail loaded as a
1280x720 JPEG, all four observed picture requests returned HTTP 200, and the
VIOS clip path returned HTTP 206 `video/mp4`. Modal playback reached ready
state 4 with no media error, duration 19.209 seconds, and 1280x720 video. The
run observed zero UI errors and zero browser-console errors.

The source-type control now displays the contract-accurate label `Video File`.
The deployed UI container uses image
`sha256:2b28982cf9a39017840132fb242766ff890c547a3abdb2f1e14de06818b3a594`.
Only the UI service was recreated for this correction.

Final screenshots retained outside the repository for this run:

- `/tmp/vss-search-runtime-coherent-results.png`: 142,234 bytes, SHA-256
  `8e7d4300b8646a9ef4469c5a678b592f6e56a1bc34c7b640713fa9ce37d5f61a`.
- `/tmp/vss-search-runtime-coherent-playback.png`: 797,263 bytes, SHA-256
  `ad8a834721d7bd348e12d411ab922325d0897903d1806988d9d5d0a204405c4e`.

## Code verification and boundary

- All 12 Search test suites passed: 171 tests total.
- The Search package TypeScript `tsc --noEmit` check passed.
- The production multi-package UI image build completed successfully.

This evidence qualifies the Search filter defaults, source refinement, core
semantic-search request, result thumbnail, and result playback path. It does
not claim the complete advertised Search capability row: critic ordering,
attribute/fusion search, search by image, Agent follow-up Q&A, and RTSP stream
lifecycle qualification remain open.
