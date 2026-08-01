# Future evidence contract

`evidence.schema.json` is intentionally stricter than a generic test report. A
future receipt must bind all observations to one exact `run_id`, one distinct
single-use `authorization_id`, the authorized repository commit, and the
canonical digest of the compiled plan.

Required evidence includes:

- one pre-existing `127.0.0.1` UI origin and three pre-existing
  `127.0.0.1` mock API endpoints on four distinct ports;
- five locally generated and digested fixtures: alerts mock data, search mock
  data, tiny MP4, tiny MKV, and mocked RTSP inventory;
- passing Thor cgroup, memory, disk, endpoint-health, and postflight gates;
- three ordered, non-overlapping, duration/request/action-bounded cases;
- a real browser driver with rendered-UI and DOM-action observations, a
  sanitized trace, DOM snapshot, and screenshot for every case;
- sanitized, run/authorization-bound API exchanges correlated with browser
  observations; raw URLs, headers, credentials, and secret-like strings are
  forbidden;
- exact assertions for alerts defaults and friendly/custom sensor forwarding,
  search defaults/critic ordering/image flow, and video upload/progress/RTSP/
  irreversible-delete behavior;
- the exact six run-owned resources, their deletion and confirmed absence,
  repeated video deletion, unchanged pre-existing state, and passing postflight
  capacity evidence.

The semantic validator rejects API-only evidence, mock output presented as
rendered behavior, non-loopback or DNS targets, source-lock drift, insufficient
resource reserve, uncorrelated image responses, overlapping or expired runs,
ambiguous resource ownership, incomplete cleanup, and live-state promotion.

Validation is offline. A structurally and semantically valid receipt remains a
future candidate for human/integration review; the package never updates the
acceptance inventory or capability-oracle ledger.
