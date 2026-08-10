# Evidence

Status: passed current on Thor (`2026-08-10`).

The bounded native-browser transaction passed against VIOS replay service
`2.1.0-26.05.4`. It established:

- native VIOS Recorded Streams UI selection of the retained `pit-POV` sensor;
- replay WebSocket configuration plus real browser SDP and ICE negotiation;
- one live, unmuted 1280x720 video track with decoded frames advancing from 2
  to 50 across the tested controls;
- a successful API `seekForward` with string value `"2"` and continued frames;
- successful opaque position readback without a client-supplied `action` query;
- exact rejection of `seekSideways` as HTTP 501 `VMSNotSupportedError`, without
  disrupting playback;
- successful native UI seek-forward and continued frames;
- explicit native UI stop, stop-frame observation, video removal, WebSocket
  close, targeted peer absence, and an empty aggregate replay-session result;
- zero external browser requests, zero Docker lifecycle actions, zero
  persistent mutations, and exact fixture, container, and running-set restore.

The released stream-processing binary applies POST body validation to the GET
seek-position route. The checked-in C++ fix separates `QueryOnly` validation
for future builds. The current prebuilt Thor image is made standards-compliant
by an exact-path, GET-only VIOS ingress compatibility rule; POST behavior and
all other routes remain untouched. Both source and runtime configurations are
digest-bound by the fixture contract.

Retained immutable artifacts:

- `runtime-receipt.json`:
  `77f99ba9d383838e53e39ce6c9e38f2e2df89d7ae1632014a29a017afe581adf`;
- `official-runtime-evidence.json`:
  `1475508276dc062fccd070d696718a7b10a88c8a613778aa2b30d822728dba1f`;
- `fixture-contract.json`:
  `0cdf3e7196e191f0a0f68c24c7b93eb06b223991372ec625443c40f7c19aeebd`;
- `execute.py`:
  `3027238f90a2dee37ce73a934f46f10440cd3cd11ecd68d62917c27b0b61dfa9`;
- `harness.mjs`:
  `f5abfa9d883e0e87cf0db8cdac20dea0b059e2adb813ca2af4a69d1488f1d1ba`;
- bound capability oracle:
  `44890e277752ed50faabd548d2423aea19c8e4af87fa16a6ae3eecdb2b89495b`.

No WebRTC credentials, peer IDs, media-session IDs, SDP, or ICE candidates are
retained. The transaction did not invoke either user-gated sample-stream add or
the user-gated VSS Agent generation endpoint.
