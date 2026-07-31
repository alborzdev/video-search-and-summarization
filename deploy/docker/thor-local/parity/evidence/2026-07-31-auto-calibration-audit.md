# Thor auto-calibration artifact audit — 2026-07-31

The VSS 3.2.1 auto-calibration source and skill match the audited upstream
commit. Its `auto_calib` Compose profile resolves only the backend and UI
services; it does not require the warehouse sample bundle.

Current Thor-local state:

- the 3.2.1 UI image is staged and is ARM64;
- the 3.2.1 backend has an ARM64 registry manifest but is not staged;
- the backend reports approximately 14.07 GB of compressed layers;
- the gated `vggt_1B_commercial.pt` checkpoint is absent and is approximately
  4.7 GB; and
- about 68 GiB of filesystem space remained at the final audit checkpoint, so
  capacity must be rechecked against the backend's unknown expanded footprint
  before staging.

The backend requires valid `vss-core` NGC access, and the optional VGGT
refinement checkpoint requires its separate license/token. These are
artifact-access prerequisites, not a warehouse-data dependency; VGGT does not
block base AMC.

The checked-in UI Compose now honors the documented
`VSS_AUTO_CALIBRATION_MS_API_URL`, preserves the legacy unprefixed fallback,
and passes a three-case resolved-Compose regression test. Base runtime
acceptance still needs the backend plus synchronized cameras, alignment, and
layout inputs; VGGT is additionally required only for refinement acceptance.
The official four-camera AMC fixture is about 154 MB and distinct from the
excluded warehouse bundle; equivalent custom operator data is also valid.
