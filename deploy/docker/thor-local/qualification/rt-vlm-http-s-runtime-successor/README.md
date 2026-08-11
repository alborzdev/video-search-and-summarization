# RT-VLM HTTP/S media runtime successor

This package proves advertised entry `manifest-entry.rt-vlm-media.01-http-s`
against the live VSS 3.2.1 RT-VLM on Thor.

The HTTP positive serves a deterministic 75 KB video from a temporary
process-local server bound only to the existing `mdx_default` bridge gateway.
The HTTPS positive uses the stable W3C Sintel trailer, checks its exact bytes
with the host trust store, and then exercises the RT-VLM downloader with TLS
verification. Adjacent negatives prove loopback SSRF rejection and the
default no-redirect policy. The qualifier stops its server and proves exact
catalog, statistics, model, and temporary-file restoration.

Plan without mutation:

```bash
python3 deploy/docker/thor-local/qualification/rt-vlm-http-s-runtime-successor/execute.py plan
```

The acknowledged execute mode prints a sanitized receipt to stdout and never
writes it automatically:

```bash
python3 deploy/docker/thor-local/qualification/rt-vlm-http-s-runtime-successor/execute.py execute \
  --ack I_ACK_RT_VLM_BOUNDED_HTTP_S_MEDIA_AND_EXACT_CLEANUP
```
