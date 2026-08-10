# Thor Search UI Playwright runtime evidence

This package retains a bounded runtime qualification of the current Search UI
and local critic on Thor. It launches a fresh isolated Chromium context against
the already-running numeric-loopback VSS UI, exercises direct semantic search,
filters, playback, the Search-by-Image overlay, desktop/mobile layout, and a
fresh sidebar-agent search that renders a confirmed local critic card.

The run is intentionally partial. The current small local corpus has Cosmos
Embed search documents and playable VST frames, but its Video Analytics frame
queries and behavior/raw indices contain no tracked-object bbox records. The
overlay therefore correctly reaches the real frame and reports no boxes; an
object cannot be selected and `/api/v1/search/image` object-level KNN cannot be
claimed. This package cannot advance `runtime.ui.search-tab` or the broader
`runtime.agent.search-profile` to `passed_current`.

The harness is inert by default:

```bash
node deploy/docker/thor-local/qualification/ui-search-playwright-runtime-successor/harness.mjs plan
python3 deploy/docker/thor-local/qualification/ui-search-playwright-runtime-successor/verify.py
pytest -q deploy/docker/thor-local/qualification/ui-search-playwright-runtime-successor/tests
```

An authorized rerun requires the exact acknowledgement, numeric-loopback UI
origin, installed Playwright entry, Chromium executable, target commit, local
sensor name, and operator-supplied direct and agent search text. The text is
used only in memory. The receipt stores only its SHA-256 and byte length.
Screenshots are hashed and removed; no raw query, prompt, response, URL, UUID,
request ID, session ID, or conversation ID is retained.
