# RT-VLM RTSP runtime successor

This package proves advertised entry `manifest-entry.rt-vlm-media.05-rtsp`
against the live VSS 3.2.1 RT-VLM on Thor.

The acknowledged executor generates the deterministic 75 KB color timeline,
starts one qualifier-owned MediaMTX container from an already-present digest,
publishes the clip as a looping H.264 RTSP stream, registers exactly one direct
RT-VLM stream, and reads one real SSE caption chunk. It then stops captioning,
deletes the exact RT-VLM stream, stops the publisher and support container, and
proves the original stream catalog and runtime identity were restored.

The source fixture is byte-locked at 1280x720, 8 fps, and nine seconds. The
live probe proves H.264, dimensions, a valid RTSP clock, and TCP readability;
the semantic oracle must return the blue, green, and red phases in order.

This does not call the VSS Agent and does not add any VIOS or RT-CV stream.

```bash
python3 deploy/docker/thor-local/qualification/rt-vlm-rtsp-runtime-successor/execute.py plan
```

```bash
python3 deploy/docker/thor-local/qualification/rt-vlm-rtsp-runtime-successor/execute.py execute \
  --ack I_ACK_RT_VLM_ONE_OWNED_RTSP_STREAM_AND_EXACT_CLEANUP
```
