# RT-VLM URL-ingestion security qualification

This package retains current-Thor runtime proof for Metadata500 indices 60–63:
domain-scoped URL authentication, bounded redirects, bounded download size, and
domain-scoped TLS verification exceptions. The running RT-VLM 3.2.1 API was
healthy, exposed `url` and `url_headers` on `VlmQuery`, and rejected a loopback
URL through the real `/v1/generate_captions` endpoint with HTTP 422 before any
download or inference.

Positive and boundary cases use the same released RT-VLM image and the exact
read-only `asset_manager.py` mounted into the running Thor service. A
disposable process starts two self-signed, loopback-only fixture domains and
calls the real `AssetManager.download_file` implementation. Only the unrelated
SSRF resolver is replaced, with a fail-closed validator accepting exactly the
two fixture hostnames; redirect targets still pass through that validator.

The probe proves request-level and environment authentication, the allowed
header set, suppression over plain HTTP, same-host retention and cross-host
stripping. It exercises redirect limits 0, 1, and 2, clamps -1 to 0 and 20 to
10, and observes SSRF validation on every followed hop. It confirms the 8 GiB
default download limit and performs a bounded 64-byte threshold test with an
atomic 413 rejection. Finally, it proves verification is on by default, a
listed self-signed domain can be explicitly exempted, and an unlisted domain
remains verified.

Verify the retained receipt without changing runtime state:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/rt-vlm-url-security-runtime-successor/verifier.py check
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  deploy/docker/thor-local/qualification/rt-vlm-url-security-runtime-successor/tests
```

The live harness is `run_probe.py`. It creates no image, model, or external
network traffic and removes its disposable container and certificates. The
main RT-VLM container and asset catalog must match their exact pre-test state.
