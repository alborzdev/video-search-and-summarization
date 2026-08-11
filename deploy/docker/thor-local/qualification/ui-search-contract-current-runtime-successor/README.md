# Current complete Search UI contract qualification

This package is the promotion-grade current-runtime qualifier for
`runtime.ui.search-tab` on the Thor-local VSS 3.2.1 deployment. It combines two
sealed real-runtime dependencies with a bounded read-only Chromium flow:

- the selected-object package proves production Search, recorded-video
  playback, a real VST picture, a real video-analytics frame and bounding-box
  click, object KNN, seed exclusion, and result-card rendering;
- the earlier local Agent-mode package proves that a real local critic result
  rendered as Confirmed;
- this package proves the full UI contract on the currently deployed UI image:
  source defaults and values, Top-K default and behavioral minimum, similarity
  endpoints, critic default/disable wiring, verdict sorting, browser-local time,
  request construction, responsive layout, and diagnostics.

The default commands are inert:

```bash
python3 executor.py plan
node harness.mjs plan
```

The bounded live command is:

```bash
python3 executor.py execute \
  --ack I_ACK_UI_SEARCH_CONTRACT_CURRENT_RUNTIME_READ_ONLY
```

The executor admits only the sealed source/runtime identities, re-runs both
dependency verifiers, snapshots the UI, ingress, Agent, and critic defaults,
then launches the already-installed Chromium against numeric loopback. The
browser intercepts only its exact local Search request and returns three fixed
critic rows in deliberately unsorted order. This isolates presentation logic:
the production UI must emit the correct request, clamp an attempted Top-K 0 to
1, sort Confirmed before Unverified before Rejected, preserve literal local
times, render the full similarity range, and avoid desktop/mobile overflow.

The execution is read-only. It creates no sensor, stream, index, report, rule,
incident, image, volume, or container; never calls Agent `/generate`; blocks
external browser traffic; and deletes its sole temporary screenshot after
hashing. A strict postcondition requires all related runtime and critic facts to
match their pre-state.

Build and validate the retained evidence offline with:

```bash
python3 build_official_evidence.py
python3 build_capability_evidence.py
python3 verify.py
pytest -q tests
```

`build_official_evidence.py --write` is used only after a successful authorized
run. See `EVIDENCE.md` and `official-runtime-evidence.json` for the retained
result. The separate `canonical-runtime-evidence.json` is the deterministic,
oracle-shaped projection used by the canonical capability ledger; its builder
first re-runs the sealed complete-Search verifier.
