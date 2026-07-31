# VSS 3.2.1 official documentation byte-lock evidence

- Captured: `2026-07-31`
- Current live-ledger semantic documentation URLs after the wave-2 merge: `53`
  (`52` `versioned_official_docs`, `1` `release_notes`)
- Wave-2 official documentation URLs: `24`
- URLs currently referenced by both inputs: `24`
- Deduplicated URLs: `53`
- Successful captures: `53`
- Failed captures: `0`
- Identity-encoded responses: `53`
- Redirected responses: `0`
- Unique final URLs: `53`
- Aggregate record SHA-256:
  `adbd613b2f36f16fa06deb4aa104948e275a164a33ff5f18750053a8fa1d5aa8`

The capture used the constrained curl policy recorded in `source-lock.json`: absolute
curl path and version, curl config disabled, replacement no-proxy environment, default
system CA trust, manual version-path redirects, and an explicit identity-encoding
request and response requirement. Full page bodies were held in a temporary directory
and deleted; no NVIDIA documentation content was retained in this repository.

This evidence binds raw bytes from mutable versioned web pages. It does not prove the
correctness or completeness of semantic extraction and does not qualify any runtime
feature.

This policy does not control DNS, CDN/origin state, routing, the system resolver,
kernel networking, CA-store updates, or changes in curl/libcurl and linked libraries.
It records those client-side boundaries where practical; it does not claim a network
fetch is deterministic.

Reproduction:

```bash
python3 deploy/docker/thor-local/parity/source-lock/source_lock.py validate
python3 -m unittest discover \
  -s deploy/docker/thor-local/parity/source-lock/tests -v
ruff check deploy/docker/thor-local/parity/source-lock
```
