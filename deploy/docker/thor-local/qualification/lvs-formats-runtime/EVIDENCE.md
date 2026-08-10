# LVS advertised-format retained evidence

Runtime evidence is generated only by the acknowledgement-gated executor and
is admitted by `verify.py`. The qualifying run must prove all five advertised
containers with nonempty local-model summaries, the adjacent invalid-media
rejection, exact owned deletion after every positive case, and byte-stable
non-owned state.

The source fixture is the tracked 2.6 MB ten-second clip. Derived files exist
only in a private temporary directory and are removed when the executor exits.
Matroska/WebM raw hashes are observed but are not pre-locked because their
muxers emit runtime segment UIDs; exact codec, dimensions, rate, duration,
stream counts, byte size, generator binary hashes, and commands remain locked.

Warehouse sample data, RTSP registration, VSS Agent generation, service
lifecycle changes, model downloads, summary text, and credentials are outside
this evidence boundary.

## Retained run

The 2026-08-10 Thor run completed in 92.508906 seconds with all 37 HTTP
requests and all nine semantic actions inside their bounds. MP4/H.264,
AVI/MPEG-4, MOV/H.264, MKV/H.264, and WebM/VP8 each returned HTTP 200 from
upload, readback, and local-model summarization; each response processed one
chunk and contained a nonempty summary or event. Every positive file returned
an exact HTTP 200 delete confirmation before the next format began.

The adjacent malformed-media upload returned HTTP 400 with `InvalidFile` and
created no asset. The complete LVS file list, RT-VLM asset statistics, LVS
readiness/model/metadata, and both container identities matched their pre-run
state exactly; both containers remained healthy with zero restarts and no OOM.

- Contract SHA-256: `28030f32ef10d0fe240b11671511a75b5b308041732206a258f9e1f333bf20d7`
- Receipt SHA-256: `85b526607ff67698d43dbc424a78cc1feb4ac7304138999c0e82e65288e45f21`
- Official evidence SHA-256: `bedea1ec8ad2f7f10796a8aa6d8fe06bae0fd58912064c081abdcabc4b774574`
- Oracle SHA-256: `a079349e0bcaca755601b9067326ed09a86b0d488e8ae4a4b6bd200067224460`
