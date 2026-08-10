# Runtime evidence

On 2026-08-10 this executor exercised the running VSS 3.2.1 Thor VIOS ingress
at loopback endpoint `http://127.0.0.1:30888/vst/api/v1`. The bounded run passed
all 13 requests and recorded:

- a 40,394-byte, two-second H.264 baseline/AAC fixture with no B-frames;
- HTTP 200 upload and stable stream/file identifiers across the timeline,
  sensor-scoped file list, path/metadata, media-info, and full-file surfaces;
- HTTP 409 for the adjacent duplicate-name upload;
- a 40,394-byte full download whose SHA-256 exactly matched the upload:
  `4985870a996fbd112ed0bc9d727f6f44b43b2d0f3c6bfc700f8a6bbffeacafa2`;
- HTTP 200 deletion of only the executor-owned stream range; and
- exact pre/post file-list and sensor-list document equality with zero owned
  namespace residue.

The raw receipt SHA-256 is
`d57f9d2adc648cbd09c8e46c4e18e5f943f2ac308e6e6464a54b5093e0c8e5c0`.
The canonical official-runtime wrapper SHA-256 is
`05d397fc57414b0cf404ce6e990f8759444597d7ce3901e6c467fbf0ca7ecdf7`.

This proves direct VIOS file upload, storage registration, duplicate rejection,
metadata/timeline lookup, byte-identical full-file download, and exact cleanup.
It does not claim the separate aggregate recording-size API, immediate cache
coherence in the split sensor microservice, NvStreamer RTSP/WebRTC playback,
VSS Agent generation, Warehouse data, or any RT-CV sample stream. Those remain
separate capability contracts.
