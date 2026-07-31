# Official documentation byte source lock

This isolated lane records the response-body SHA-256 for every deduplicated
`versioned_official_docs` and `release_notes` URL referenced by the live VSS 3.2.1
capability ledger and the wave-2 candidate. It stores metadata and hashes only;
fetched NVIDIA documentation bodies are temporary and are deleted immediately after
hashing. The extractor also accepts an explicit `additional_audited_urls` list for a
future reviewed index-wide set; it does not crawl or implicitly trust the index.

The lock is a reproducibility aid for identifying source drift. NVIDIA's versioned web
pages remain mutable. A byte match says only that the raw response body matches this
capture; it is **not** proof that a capability was extracted correctly, that a locator
still has the same meaning, or that Thor implements the documented behavior.

## Contract

- Initial URLs must use HTTPS, the exact `docs.nvidia.com` host, and the
  `/vss/3.2.1/` path.
- Redirects are followed manually, at most five times, and every redirect target must
  remain HTTPS on the exact `docs.nvidia.com` host and `/vss/3.2.1/` path. Redirect
  loops and duplicate final URLs fail.
- The request explicitly asks for `Content-Encoding: identity`. Only HTTP 200
  `text/html` and `application/xhtml+xml` non-empty identity bodies are successful;
  `gzip`, `br`, and every other response encoding fail.
- Failed requests remain explicit records, and the command returns non-zero while any
  failure remains.
- Duplicate JSON keys, duplicate URLs, an input byte-hash change, and a URL-set change
  fail validation.
- Curl is invoked by the recorded absolute path with `--disable` as its first option
  and a replacement environment that carries no inherited proxy, `HOME`,
  `CURL_HOME`, curl-config, or custom-CA variables. The recorded curl version, system
  trust mode, options, final URL, status, content type, content encoding, byte count,
  body hash, and any failure are validated. Response bodies are never checked in.
- A refresh requires an explicit `--captured-on YYYY-MM-DD`. Atomic installation may
  replace an existing snapshot only with the same capture date; a different date
  requires a new output path, preventing an in-place silent relabel.
- The aggregate is SHA-256 over the canonical JSON form of the complete, URL-sorted
  capture-time record array. It binds failures, initial provenance, and metadata as
  well as successful body hashes.

Validate the checked-in capture without network access:

```bash
python3 deploy/docker/thor-local/parity/source-lock/source_lock.py validate
python3 -m unittest discover \
  -s deploy/docker/thor-local/parity/source-lock/tests -v
```

Refreshing is a deliberate network operation. This command atomically replaces the
same-date metadata snapshot:

```bash
python3 deploy/docker/thor-local/parity/source-lock/source_lock.py \
  fetch --captured-on 2026-07-31
```

Review every changed URL hash and failure before accepting a refresh. Never infer a
semantic capability change solely from a byte-hash change.

## Reproducibility boundary

The constrained invocation removes common process-level curl variability but cannot
make a network fetch deterministic. DNS answers, CDN edge selection, origin/CDN
mutation, TLS and CA-store updates, system resolver state, routing, kernel behavior,
and curl/libcurl or linked-library behavior can still change the returned bytes or
whether a request succeeds. The recorded absolute tool path and version describe this
capture; they do not reproduce NVIDIA's server-side state.
