# Official documentation byte source lock

This isolated lane records the response-body SHA-256 for the exact 172-page
recursive fixed-point set rooted at the VSS 3.2.1 documentation index. The
allowlist is read from
`candidates/wave3/recursive-coverage/recursive-targets.json`; the source-lock
collector does not crawl or add URLs. The live capability ledger and immutable
Wave 2 candidate remain inputs only to attach provenance labels, and every one of
their documentation URLs must occur in the recursive allowlist.

The lock stores bounded response metadata and hashes only. Fetched NVIDIA
documentation bodies are temporary and are deleted immediately after hashing.

The lock is a reproducibility aid for identifying source drift. NVIDIA's versioned web
pages remain mutable. A byte match says only that the raw response body matches this
capture; it is **not** proof that a capability was extracted correctly, that a locator
still has the same meaning, or that Thor implements the documented behavior.

## Contract

- Initial URLs must use HTTPS, the exact `docs.nvidia.com` host, and the
  `/vss/3.2.1/` path, end in `.html`, and match the pinned sorted 172-URL set.
- The recursive target input must contain exactly 172 unique sorted URLs and its
  canonical target-set hash must be
  `74a1d6ae1f520049202e47dce69fa56d10c28c48aa3aa24a3a2c4214dad4b208`.
  An extra, missing, reordered, or changed URL fails before fetching.
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
- A refresh of this reviewed snapshot requires the exact explicit
  `--captured-on 2026-07-31`. Atomic installation may replace the existing
  snapshot only with that date. A later capture requires a separately reviewed
  snapshot/schema change, preventing an in-place silent relabel.
- The aggregate is SHA-256 over the canonical JSON form of the complete, URL-sorted
  capture-time record array. It binds failures, initial provenance, and metadata as
  well as successful body hashes.
- The summary records the sum of successful raw response-body byte counts. It
  does not claim deterministic network transfer overhead.

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

The checked-in 2026-07-31 capture contains 172 successes, zero failures, and
13,351,947 successful raw response-body bytes. Its canonical record aggregate is
`b37a617f351dbd32673983eee2299daed0db1f04b387db5d89ec2a89511d79eb`.

## Reproducibility boundary

The constrained invocation removes common process-level curl variability but cannot
make a network fetch deterministic. DNS answers, CDN edge selection, origin/CDN
mutation, TLS and CA-store updates, system resolver state, routing, kernel behavior,
and curl/libcurl or linked-library behavior can still change the returned bytes or
whether a request succeeds. The recorded absolute tool path and version describe this
capture; they do not reproduce NVIDIA's server-side state.
