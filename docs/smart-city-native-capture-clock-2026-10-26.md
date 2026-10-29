# Native camera capture clock

The final Spark demo uses native image `4e6b73d1…` and UI package
`20261026T102610382036Z`. Its bounded live check passed 22 exact preview
envelopes. All 11 latest-source pairs were inside the unchanged 150 ms map
window: median 0.501 ms and maximum 123.686 ms. A separate actual browser
capture shows one shared-person marker. These results concern this tested
transport and display path; they are not an identity-accuracy score.
See [current health and identities](qa/smart-city-2026-10-26/native-sei-final-health.json),
[rates and clocks](qa/smart-city-2026-10-26/native-sei-final-native-performance.json),
[real paired observations](qa/smart-city-2026-10-26/native-sei-qualified-shared-pair.json)
and [actual dashboard pixels](qa/smart-city-2026-10-26/native-sei-final-dashboard.jpg).

The Isaac camera publisher writes its actual encoded-frame handoff wall time in
each H264 access unit. The explicit `source-native-sei` worker mode uses that
time before both native tracker stages. This is a capture handoff clock. It is
not a claim about physical exposure time or browser delay.

The current producer and VIOS streams were checked in one simultaneous
10-second encoded-only capture. Each path kept 90 access units per camera.
All native SEI and picture payloads matched through VIOS. The native camera
RTCP references for the same render frame differed by at most 0.305 ms. The
earlier worker nevertheless reported a median 597 ms camera difference and
put northeast frame times in the future. This places the fault in that worker
client's timestamp reconstruction. It does not prove which SDK or jitter-buffer
calculation introduced the offset. The producer was not changed.

See [current wire evidence](qa/smart-city-2026-10-26/current-epoch-native-vios-capture-clock.json)
and [bad worker evidence](qa/smart-city-2026-10-26/final-clock-regression-audit.json).

The new mode has these checks:

- The approved Isaac profile must explicitly select `sourceClockMode:
  source-native-sei`. Generic cameras keep their existing RTCP path. The flag
  works with one ordinary NvDCF camera and with the two-stage camera pair.
- The parser requires the exact native UUID and the existing five publisher
  fields, including `timestamp_basis: wall-capture`. The format version is the
  parser contract; the producer does not publish a `schemaVersion` field.
- Each picture access unit must have exactly one native capture record. The
  parser rejects duplicate fields, duplicate UUIDs, invalid numbers, truncated
  payloads and an invalid or inconsistent UTC label. Other VIOS metadata is
  separate from the capture authority.
  October 27 correction: the installed H264 parser can retain pictureless
  native-prefix units and append them to the next picture buffer. The native
  producer puts its clock before each access-unit delimiter. Only explicit
  delimiters, no picture in every discarded prefix, and strictly advancing
  source clocks allow those empty prefixes to be discarded. The final picture
  keeps its own record and exact decoded-buffer PTS; duplicate records within
  one delimited unit, multiple pictured units, missing delimiters and empty
  final units still fail. This handles the two retained failure buffers from
  the scenario-switch investigation without an RTCP or nearest-time fallback.
- A bounded per-source cache joins the encoded access unit to the decoded
  frame, the frame before mux, and the mux frame by **exact PTS**. A nearby PTS
  cannot supply the clock. Repeated PTS cannot reuse a consumed record.
- Capture times and frame counters must advance. Capture data older than two
  seconds or more than 50 ms in the future is refused. A stream reset,
  discontinuity or changed segment after data starts stops the worker. A fresh
  managed worker provides fresh source and fusion sessions.
- Immediately after mux, the worker replaces `NvDsFrameMeta.ntp_timestamp`
  with the verified handoff time. `buf_pts` remains unchanged. The installed
  DeepStream 9.2 tracker uses nonzero `ntp_timestamp` for
  `NvMOTFrame.timeMeta.frameTimeStamp`, so both trackers receive this time.
- Observations and exact previews use the same capture value. The observation
  also contains `city.source-native-sei.v1` evidence with its original AU PTS
  and publisher frame counter. The counter is provenance, not a tracking ID.

There is no RTCP fallback when this mode is selected. A missing or ambiguous
record stops the worker before inference or tracking can use it. The map still
requires the existing session, calibration, identity, image, distance and
150 ms pairing checks. Simulation time, actor positions and actor IDs do not
provide analytics or shared identities.

CPU checks cover the parser, real Gst metadata probes, cache bounds, failures,
the timestamp before tracking, the second tracker's frame counter rewrite, and
matching observation/preview time. They also accept 360 actual native and VIOS
access units from the retained capture. These checks do not establish live
MV3DT accuracy or long-run stability. The final bounded live checks are linked
above. The intermediate UI omitted nested clock proof and the first native
candidate retained an RTCP-only optional-ID gate. Both failures and their
narrow repairs are preserved. Generic RTCP handling, raw-video clock guards,
camera-local counts and all map joining limits remain unchanged.
