# VIOS file-to-RTSP manifest runtime successor

This read-only package binds the retained, isolated NvStreamer file workflow
to exact VSS 3.2.1 manifest row 413. The runtime accepted API upload, shipped
UI upload, and automatic local-mount discovery; generated RTSP; decoded the
RTSP video/audio; returned a live snapshot; and played a real advancing WebRTC
frame. Invalid media failed with HTTP 400 and all owned resources were removed.

The compiler retains no stream IDs or media payloads and does not operate the
main VIOS or RT-CV deployments.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/vios-file-rtsp-manifest-runtime-successor/compiler.py check
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  deploy/docker/thor-local/qualification/vios-file-rtsp-manifest-runtime-successor/tests/test_compiler.py
```
