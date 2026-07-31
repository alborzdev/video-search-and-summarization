# Thor AutoMagicCalib alternate lane — 2026-07-31

## Scope

This lane closes static and offline-operability gaps for the VSS 3.2.1
AutoMagicCalib service without downloading the excluded warehouse bundle,
pulling the approximately 14.07 GB backend, accessing gated VGGT, or changing
container lifecycle state.

It supports operator-owned synchronized MP4s and a redacted RTSP plan. The
official small AMC fixture remains optional; the local generated fixture is a
media-contract check only and is not represented as calibration evidence.

## Audited graph and artifacts

The upstream `auto_calib` profile resolves exactly two services:

1. `vss-auto-calibration` backend, host-networked on port 8010 by default;
2. `vss-auto-calibration-ui`, published on port 5000 by default.

The warehouse sample bundle is not a dependency of this profile. RTSP capture
adds an operational dependency on VIOS, while direct MP4 upload does not.

The checked-in inventory records the already staged UI as ARM64 with both image
ID and immutable repository digest
`sha256:e86c16ac9e88241dabd35e6f44c2d5086a77551a3e3654b4905e51bbf4cdf6a4`.
The absent backend has no invented digest, and the absent VGGT checkpoint has
no invented checksum. Both null locks fail closed. VGGT does not block base AMC.

## Added qualification controls

- Pull-free inventory based only on local Docker image inspection and local
  model hashing.
- Strict contiguous `cam_XX.mp4` naming and ffprobe checks for readable video,
  matching resolution/frame rate/duration/start time, with honest warnings for
  physical synchronization, resolution, and scene duration.
- JSON validation for optional settings/alignment and PNG signature validation
  for layout input.
- RTSP plan validation that enforces the 60-second minimum, unique camera names,
  and valid RTSP schemes while never emitting URLs or credentials.
- A deterministic two-camera H.264 fixture for codec/naming validation only.
- A Thor Compose overlay requiring a backend `@sha256` reference, pinning the
  UI digest, loopback-binding UI and backend, bounding logs, and disabling
  automatic restarts.
- GET-only runtime checks for AMC readiness, all 26 skill-advertised OpenAPI
  operations, UI reachability, and optional VIOS sensor-list reachability.
  Qualifier origins must be numeric loopback and have no credentials, query,
  fragment, or unexpected path; requests bypass proxies and redirects.

## Qualification state

Static and offline tests cover the input validators, secret redaction,
fail-closed lock semantics, resolved Compose hardening, generated H.264 fixture,
and GET-only OpenAPI contract logic. The focused suite passed 18 unit tests,
the generated-fixture integration check, and the pre-existing three-case AMC UI
Compose endpoint regression on 2026-07-31.

Current runtime status remains **blocked**:

- backend image: absent and not content-locked;
- VGGT: absent (optional for base AMC, required for refinement);
- backend/UI: not running;
- real synchronized cameras plus alignment/layout: not supplied;
- no real project has reached `COMPLETED`, produced an overlay, exported AMC or
  VGGT MV3DT results, or generated ground-truth accuracy metrics.

Those are explicit acceptance blockers, not warehouse-sample dependencies.
