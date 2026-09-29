# Distinguish selected intervals across searches

## Finding

A source-scoped box search returns a five-second clip, while the all-source
search can group two adjacent matches into ten seconds. Both have the same
title, source and starting offset. Selections intentionally persist across
searches, but the tray omitted duration and combined source/offset in a truncated
line. A visitor could mistake the old selection for the new result.

## Change

`InvestigateWorkspace` now passes the selected snapshot's duration, using the
existing duration formatter. `EvidenceAnalysisPanel` shows source on its own
line and start/length on a separate wrapping line. Increased tray title/source/
provenance text from 10/9/8 px to 12/11/10 px. No request bounds, selection
identity, inference behavior or report content changed.

## Verification

Codex integrated browser at `http://10.88.9.12:7777/?workspace=explore`:

1. Selected the ten-second all-source result.
2. Scoped search to Warehouse — Box Handling, obtaining the five-second result.
3. Confirmed the retained selection still reads `00:10 clip`.
4. Selected the new result and confirmed E1 `00:10 clip`, E2 `00:05 clip`,
   both with `0:00 into recording` and the correct source.
5. Inspected default desktop and 390 × 844 mobile; source/time remain readable,
   no overlap or framework overlay. Browser warning/error log empty. Reset viewport.

The existing InvestigateWorkspace and EvidenceAnalysisPanel suites passed
26/26 with the scoped Jest command and a 256 MiB Node heap cap. No new
implementation-mirroring test added; the actual cross-search reproduction is
the changed behavior's primary evidence. No full typecheck repeated at narrow
memory headroom. No fresh AI request submitted or report saved.

Screenshots: `evidence-durations-desktop.png`, `evidence-durations-mobile.png`.
This clarifies evidence selection; multi-clip visual correctness and sustained
runtime qualification remain open.
