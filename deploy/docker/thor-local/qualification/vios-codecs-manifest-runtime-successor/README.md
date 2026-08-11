# VIOS codec manifest runtime successor

This read-only package binds one retained, bounded Thor NvStreamer/VIOS runtime
transaction to four exact VSS 3.2.1 advertised rows: B-frame handling, HEVC
multislice/RFC7798, H.264/H.265, and audio RTSP republish. The source run used
tiny generated media, an isolated loopback container, and the immutable local
ARM64 NvStreamer derivative; it did not mutate the main VIOS deployment.

The compiler verifies the hash-locked raw receipt, cleanup wrapper, and capture
implementation before independently checking each advertised literal. It does
not claim row 423 audio recording: NvStreamer-to-main-VIOS recording was not
executed and remains a separate qualification item.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/vios-codecs-manifest-runtime-successor/compiler.py check
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  deploy/docker/thor-local/qualification/vios-codecs-manifest-runtime-successor/tests/test_compiler.py
```
