# Live overview clarity — September 28

## Finding

The integrated browser showed “No live cameras connected” followed by five empty
camera players, repeated connection warnings in an attention column, and a
recording in the same grid. This made the visitor's available next step hard to
find and blurred recorded footage with live camera capability.

## Changes

OperationsWorkspace now separates live cameras from recordings. Disconnected
cameras appear in a collapsed, counted connection list with individual source
navigation. They no longer mount preview players in the overview. Live sources
whose status is not explicitly offline/removed retain preview cards; unknown
status is not silently discarded. All recordings have distinct source buttons.
Counts explicitly distinguish configured live cameras, recordings, and searchable
live cameras. The attention panel remains for actual events or usable-source
status, rather than repeating the disconnected list. The former eight-source
slice is removed so source cards are not silently omitted.

The detail panel also labeled a disconnected camera's visual Q&A as Ready.
It now says “No live frames — camera disconnected” and “No live input” for
tracking. Configured detection without observations no longer claims readiness.

## Verification

- Codex in-app browser only; app URL http://10.88.9.12:7777/?workspace=live.
- Desktop and 390×844 mobile: clear empty-live state, recording handoff and
  collapsed connection details; no framework overlay or visible overlap.
- Expanded five disconnected cameras and opened IsaacSim CamNE. Verified corrected
  detail text. No Resume analysis action was invoked.
- Returned through the persistent Live cameras tab, opened Warehouse — Box Handling
  from its new recording button. Video reached readyState 4, currentTime 6.433 s,
  duration 9.9 s, with no media error. Browser console returned no errors/warnings.
- Twelve scoped OperationsWorkspace tests and app TypeScript passed. Tests cover
  disconnected preview suppression/detail access, explicit offline readiness,
  live-camera visibility, and existing profile/analyst flows. The Jest run still
  emits jsdom media cleanup warnings; no browser equivalent was observed.
- Screenshots: live-availability-overview.png and live-availability-mobile.png.

No live source was connected, ingestion enabled, inference submitted, or runtime
budget changed. Connected-camera rendering is covered by fixtures, not a real
live feed in this pass. Sustained live operation and the full demo remain open.
