# Three-question and evidence qualification

`qualify_questions.py` is an explicit operational test. With `--allow-real-ask` it makes exactly three sequential real UI Ask requests for one registered source, then requests the first evidence window again without a fourth Ask. It never starts a detector, changes budgets, launches model containers, opens RTSP readers or decodes video. Development controls use mocked HTTP and virtual time; they do not qualify the actual system.

Run it only after the production UI and the two-source native pipeline, embedding, VLM and LLM services are ready. Run the separate `soak.py` monitor throughout to measure resource use, clocks, freshness, native acknowledgements, duplicate timestamps, OOM and restarts. This helper checks the exact active site/source, RTCP source clock, native active revision, current UI workload admission and the saved available-memory reserve before each question and before the repeat. It requires at least the saved reserve and 20 GiB. It does not replace the soak monitor.

The readiness snapshot has a bounded 1-MiB JSON limit because it includes retained tracks and events. Other JSON responses remain limited to 64 KiB.

```sh
python3 tools/smart-city/qualify_questions.py \
  --allow-real-ask --device spark \
  --site-id YOUR_EXACT_ACTIVE_SITE_ID \
  --source-id YOUR_CANONICAL_REGISTERED_SOURCE_UUID \
  --allow-vss-alias 172.17.0.1 \
  --output-dir .spark/city/runtime/three-question-trial-NEW
```

The UI origin defaults to `http://127.0.0.1:7777`; the city gateway defaults to port 9184. The alias flag only permits a returned media URL on a known local VSS hostname with the same scheme and port; it rewrites that URL to the configured UI origin. Without the flag, a different hostname is rejected. It does not allow arbitrary hosts, ports or media paths.

Each question uses the real source's current live five-second window. After the full Ask/export/fetch completes, the runner waits at least 60 seconds before starting the next question. Waits use one-second sleeps; `--between-calls-seconds` can increase the interval up to 900 seconds. Each network operation has a client timeout of at most 55 seconds. There are no retries. A timed-out client cannot prove that server work was cancelled: failure ends the runner before any further question. Coordinate recovery through the normal operator controls.

The answer must be nonempty, have `grounded: true`, evidence tools and a valid recent five-second observed window. Success stores only the answer SHA256 and character count, plus the grounded flag, tool names and observed window. Each subsequent window and returned media URI must be different. This is URI evidence of separate requested outputs, not proof of an internal cache miss or a semantic answer score.

For each returned window, the runner calls the actual `/api/vision/evidence` route and fetches the returned MP4 through only `/api/vision/evidence-media?key=...` or `/vst/storage/temp_files/NAME.mp4` on the same UI origin. Redirects, credentials, path traversal, arbitrary query parameters and external hosts are rejected. Fetches stream at most 20 MiB into a hash; no clip is saved or decoded. An MP4 header and full HTTP 200 delivery are required.

After the third question, the runner repeats the first observed-window evidence request and byte fetch. It records whether the normalized media URI and byte hash match the original. A changed byte hash fails this controlled repeat; equal URI/bytes do not establish VIOS's internal cache behavior. Export paths can run even though the HTTP operation is GET.

Output is a new private directory (mode 0700) with atomic private JSON files (0600): `progress.json` and final `receipt.json`. Receipts omit generated answer text, RTSP URLs, credentials, full API response bodies and media bytes. They retain source identity, request count, timing, readiness facts, observed windows, safe media paths and hashes. Failure exits nonzero and does not pause or delete sources. The separately configured soak monitor can use its own explicit source-scoped pause-on-failure action.

For the allocator trial, keep `MALLOC_ARENA_MAX=2` as the only changed VIOS setting. Keep the same image, 2-CPU/2-GiB limits, 20-GiB reserve, Medium profile and 10-ms mux setting. Record memory before, during and at least 60 seconds after each different-window export. Do not combine encoder/decoder thread changes with that trial.

Offline controls:

```sh
python3 -m unittest discover -s tools/smart-city/tests -p test_qualify_questions.py -v
```

These cover three serial distinct-window requests and an evidence-only repeat, exact identity, missing source clocks, denied admission, low reserve, invalid timing, missing answer/grounding/evidence, absent opt-in, unsafe media URLs and both declared and streamed oversize clips. All HTTP and time in the serial trial are mocked.
