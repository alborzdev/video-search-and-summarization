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
- the existing 77 GiB free-disk envelope is sufficient for the downloads, but
  the backend's expanded footprint must be measured before staging.

The registry currently denies the backend manifest request without a valid
`vss-core` NGC credential, and the VGGT checkpoint requires its separate
license/token. These are artifact-access prerequisites, not a warehouse-data
dependency.

The checked-in UI Compose now honors the documented
`VSS_AUTO_CALIBRATION_MS_API_URL`, preserves the legacy unprefixed fallback,
and passes a three-case resolved-Compose regression test. Full runtime
acceptance still needs the backend/checkpoint plus synchronized cameras,
alignment, and layout inputs. The official four-camera AMC fixture is about
154 MB and distinct from the excluded warehouse bundle; equivalent custom
operator data is also valid.
