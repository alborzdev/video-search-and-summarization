# Thor live picture lookup repair — October 9, 2026

The main camera question path failed with HTTP 422 from the CPU `/picture`
service. There were two distinct storage problems:

- VIOS live timelines could advance beyond the media packet timestamps. The
  camera packet clock lagged the host by roughly one minute.
- A broad VIOS file lookup found the currently open MKV, while a narrow lookup
  of a timestamp inside that same file returned no media. The narrow lookup
  succeeded after recording stopped, hiding the issue in retained-only tests.

The UI now reads packet-derived retained intervals from `/recording-window`.
Readiness uses advancement of these actual packet timestamps. The service
retains a bounded, source-specific association between verified intervals and
files, so a subsequent one-frame question does not repeat the unreliable narrow
lookup. Missing, stale, or out-of-range files do not satisfy this association.

CPU picture extraction now attempts input seeking and validates the decoded
frame's microsecond PTS. An incorrect seek index triggers bounded sequential
fallback; an out-of-window frame is rejected. The former sequential-only path
could time out after 15 seconds on a 2560×1920 camera recording. No model or
memory budget changed; the active guard remains at the selected 10 GiB reserve.

## Verification

- 38 CPU service tests passed inside the runtime image, including a growing
  epoch-timestamped MKV. Before closing the writer, interval advancement and
  picture extraction succeeded with narrow file lookup forced to fail.
- 81 scoped UI/API tests passed; app TypeScript check and `git diff --check`
  passed. Fixtures explicitly cover the local packet-based endpoint and the
  one-second default.
- The October 9 20:08:49.349 UTC camera frame (from the user's failed session)
  decoded to a 100,404-byte JPEG in 1.7 seconds including packet probing, with
  narrow VIOS lookup deliberately unavailable and zero calls to that lookup.
- After restarting only the CPU evidence service, the full UI analyst API
  answered two questions against the reboot session's retained camera footage
  in 6.19 and 7.25 seconds. The latter inspected 20:09:02.012–20:09:03.012 UTC
  instead of requesting the unavailable host-clock live edge.
- The UI and CPU service remain source-mounted for desktop startup/reboot.

The physical camera was disconnected when these final checks ran. The growing
file regression covers the active-writer lookup failure, but these checks do not
claim a completed fresh offline boot with the physical camera after this fix,
nor qualification for sustained live ingestion. Earlier retained-only success
was insufficient to demonstrate the now-covered active-file case.
