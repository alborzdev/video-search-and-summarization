# VSS 3.2.1 official documentation byte-lock evidence

- Captured: `2026-07-31`
- Exact recursive fixed-point URLs including `index.html`: `172`
- Recursive target-set canonical SHA-256:
  `74a1d6ae1f520049202e47dce69fa56d10c28c48aa3aa24a3a2c4214dad4b208`
- Recursive target input file SHA-256:
  `30e42ca2d085aa6e4b3ea99e537f9e2897864da1463979bb4768d06b8027a3aa`
- Current live-ledger semantic documentation URLs: `53`
  (`52` `versioned_official_docs`, `1` `release_notes`), all recursive members
- Wave-2 official documentation URLs: `24`
- URLs referenced by both the live ledger and Wave 2: `24`
- Successful captures: `172`
- Failed captures: `0`
- Successful raw response-body bytes: `13,351,947`
- Identity-encoded responses: `172`
- Redirected responses: `0`
- Unique final URLs: `172`
- Aggregate record SHA-256:
  `b37a617f351dbd32673983eee2299daed0db1f04b387db5d89ec2a89511d79eb`
- Source-lock JSON file SHA-256:
  `fbf21f64f13dc22328c4a01c79e427042c3112885073dc32bb0ebd6700f0fd07`

The capture used the constrained curl policy recorded in `source-lock.json`: absolute
curl path and version, curl config disabled, replacement no-proxy environment, default
system CA trust, manual version-path redirects, and an explicit identity-encoding
request and response requirement. Full page bodies were held in a temporary directory
and deleted; no NVIDIA documentation content was retained in this repository.

The collector consumed the exact recursive target artifact as an allowlist. It
did not perform a second crawl, follow arbitrary page links, download model or
sample assets, start containers, or invoke a GPU workload. The 53 live-ledger and
24 Wave 2 documentation URLs were checked as subsets and attached as record-level
provenance; they did not define or expand the capture set.

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
