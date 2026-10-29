# Pedestrian exit confirmation: source and offline qualification

This candidate fixes an observed single-frame lateral projection spike without
changing the measured position, the painted crossing polygon, or its one-second
observation gap. This document records source/CPU evidence. It does not claim a
live episode has passed after deployment.

A first fresh outside anchor remains outside: its current crossing occupancy is
zero. The journey temporarily awaits another observed sample. A second fresh
observation with the same camera/session/local identity and exit category
confirms a far-side completion, return, or lateral incomplete exit. Both samples
must fall within the existing gap measured from the last actual inside anchor.
Outside observations, changing exit categories, predictions and half-pixel
boundary ambiguity cannot extend that deadline. An actual inside re-observation
cancels the candidate and preserves the observed journey. A missing final sample
expires as incomplete; it never proves completion.

Class changes retire the proof. New IDs cannot inherit it. Source session,
calibration, configuration and reset boundaries clear it. Existing bounded
history and capacity limits remain. The result's `qualityReasons` explains a
pending exit; `pendingExitTrackCount` is separate from the existing
`pendingTrackCount`, which the UI describes as briefly missing. The public
`completionBasis` stays `observed-far-side-exit`. The internal
`exit-candidate-recovered` record only contributes a numeric recovery count;
it is not a new public event enum.

The focused controls passed **54/54**, including four tests through real
`CityEngine.ingest` for class/session/reset boundaries and public JSON. The
original nine single-sample terminal expectations were changed to require a
second actual outside sample. Fatal Ruff selection `E9,F63,F7,F82` passed.
Source hashes and the exact command are in the
[qualification receipt](pedestrian-pending-exit-source-qualification.json).

The [offline replay receipt](pedestrian-pending-exit-offline-replay.json) pins the
retained **2,298 actual observations / 1,149 Southwest frames**, original
scenario configuration, source calibration, source code and replay script. The
[saved replay script](replay-pedestrian-pending-exit.py) uses only first-NvDCF
boxes, current-frame observation flags and source-class projection. It verifies
the saved input hashes before reading; it does not read the growing live log or
mutate services.

After both backend candidates were frozen, the combined city suite passed
**259/259**. A separate read-only source review and isolated UI CPU run passed
**49/49** pending-evidence presentation controls; its
[independent review receipt](pending-evidence-ui-independent-review.json)
records the exact UI hashes. These checks do not constitute browser or live
scenario acceptance.

For handle `5527462707671859204`, source time `1793003197895063445` projects to
`[-13.345221, 83.220310]`, outside the East crossing. Current crossing occupancy
remains zero and the lateral exit is pending. At `1793003197949241222`, **54.18
ms later**, the same ID is actually observed at `[-11.077204, 85.254195]` inside
the crossing. The candidate is cancelled and the original journey survives.
The original immediate incomplete outcome at the spike is absent.

The replay still reports **zero completed crossings**. The separate observed SDK
identity exchange remains; no aliases or simulator ground truth repair it. This
patch is temporal confirmation, not a validated outlier classifier: two
consistent wrong outside measurements can still terminate a journey. It adds
one fresh-sample exit latency and intentionally leaves a single observed exit
followed by loss incomplete. A fresh controlled live episode remains required.
