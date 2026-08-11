# Complete Search UI current-runtime evidence

Status: **passed current; promotion eligible**

The 2026-08-10 Toronto qualification ran against the freshly rebuilt
Thor-local production UI image and completed in 7.968 seconds. The isolated
Chromium performed 12 bounded actions, observed 35 numeric-loopback responses,
and made zero persistent mutations.

Current-image browser proof:

- the Search tab rendered and defaulted to Video File;
- the source selector exposed exactly Video File and RTSP, and completed a
  round trip through both values;
- filters defaulted to Top-K 10 and cosine similarity -1;
- an attempted Top-K 0 was behaviorally clamped to the advertised minimum 1,
  and the emitted request contained Top-K 1;
- the emitted direct Search request used recorded-video source type, Agent mode
  false, no selected sources, and a null time range;
- a deliberately unsorted three-row response rendered as Confirmed,
  Unverified, Rejected;
- similarities -1, 0.25, and 1 rendered in that sorted order;
- literal 23:45:10/23:45:11 values remained literal in an America/Toronto
  browser context, proving the no-offset-conversion UI contract;
- 1440×900 desktop and 390×844 mobile layouts had no horizontal overflow.

The Agent container had critic enabled, while Compose, both active profile
sections, the request model, and top-agent fallback all retained the default-on
contract and `ENABLE_CRITIC=false` disable boundary. The dependency receipt
also retains one real local Agent-mode Confirmed critic card. The three-row
fixture in this package is intentionally presentation-only: it proves all three
sort branches without invoking Agent `/generate` or claiming three new model
inferences.

The freshly rerun selected-object dependency proves the production data path on
the same deployed UI image: real MP4 playback, VST picture HTTP 200,
video-analytics frames HTTP 200, two selectable boxes, an actual canvas click,
object KNN candidate-only output with seed exclusion, and preservation of the
human-facing source name.

Browser diagnostics contained 34 HTTP 200 responses and one valid 206 response.
There were no console errors or warnings, page errors, unexpected request
failures, failing HTTP responses, non-loopback requests/responses/WebSockets,
or framework overlays. One exact aborted local Chat audio-presence HEAD probe
was classified separately; switching to the Search tab unmounts that optional
probe, and it is neither a Search request nor an HTTP failure.

The browser and temporary screenshot were removed, all UI/ingress/Agent
lifecycle facts and critic defaults matched before and after, both dependency
packages reverified, and no server-side state changed. The sealed receipt and
official projection retain only hashes, counts, booleans, sizes, and bounded
semantic values—no raw prompt, response, URL, vector, credential, or runtime
identifier.

This package is the authoritative current evidence for
`runtime.ui.search-tab`. The separate backend Search package is the
authoritative current evidence for `runtime.agent.search-profile`.

`canonical-runtime-evidence.json` binds this sealed run to the exact Search UI
capability oracle, fixture digest, assertion order, and read-only cleanup
postconditions. The richer `official-runtime-evidence.json` remains the
human-facing qualification summary and dependency record.
