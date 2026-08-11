# Retained evidence

Status: **passed current** and promotion eligible.

The retained run exercised the live VSS Agent, main VIOS, RT-Embed, RT-CV, and
Elasticsearch services on this Thor. Both documented accepted MIME values
completed the real compatibility ingest path:

- `video/mp4`: HTTP 200, one embedding chunk, one exact sensor-ID embedding
  document;
- `video/x-matroska`: HTTP 200, one embedding chunk, one exact sensor-ID
  embedding document;
- missing `Content-Type`: HTTP 400; and
- `application/octet-stream`: HTTP 400.

The run used 40 bounded loopback HTTP requests and four persistent mutations:
two exact qualification uploads and their two exact Agent-managed deletions.
Postconditions proved both sensor names and their embed/behavior/raw documents
absent, the complete pre-existing sensor/file identity inventory restored, and
all four related container identities, health states, and restart counters
unchanged.

The source correction aligns the unsupported-media result with NVIDIA's VSS
3.2.1 HTTP 400 contract; the prior live behavior returned HTTP 415. The unit
contract was updated with the implementation.

Artifact SHA-256 values:

- contract: `5dc1b70063cb6c9df1c4c15b6694f83bbd41ae80dc32138239bb5d68ba354a53`
- executor: `6dfda2eb12f8ff7591ad203045f3c810426d87ba1955b95fb52e0ed74c7b4f87`
- receipt schema: `0d297d9bbdd8748b4b5c81d24f57a323476e2e0cb88ff4dd6e65394c724c0684`
- runtime receipt: `ec61b998395746dc6cc59a969188ac8de181d2939c82530463f5309db5db4d6d`
- verifier: `4624416bdaffc72966db09aa6d22e49f09cf39a38aaea426de6e1334021c89e9`
- human-readable runtime summary: `39992c51a2b9a004557554270e15d53499b6f2b5ff4c6a6b09d17fe6e51390f6`
- canonical evidence builder: `d9de04c6a9efe96357bec49041f5610366d8c4dc94d1141c312ec49610363c47`
- canonical runtime evidence: `59c55696d84cae84b5cea839bc319ed1f91dd3107af76dc62a78bbd78a5381c3`

No raw media, sensor identity, URL, response body, prompt, credential, session,
SDP, or ICE data is retained.
