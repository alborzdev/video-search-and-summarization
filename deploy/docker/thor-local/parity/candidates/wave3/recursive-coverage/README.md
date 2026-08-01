# VSS 3.2.1 recursive documentation coverage

This package records the same-version HTML link closure rooted at the NVIDIA VSS
3.2.1 documentation index. It proves that the direct-index denominator of 152
pages was incomplete: recursive traversal reaches 171 pages excluding the index,
adding exactly 19 Warehouse descendants.

This is an audit candidate. It does not modify the live parity ledger, source
lock, manifest, deployment profiles, or shared validator.

## Result

| Measure | Count |
| --- | ---: |
| Reachable URLs including `index.html` | 172 |
| Reachable pages excluding `index.html` | 171 |
| Direct-index pages | 152 |
| Added recursive descendants | 19 |
| Added semantic omissions | 8 |
| Added external workflow dependencies | 9 |
| Added navigation/reference hubs | 2 |
| Canonical directed links | 26,449 |

The full recursive classification, excluding the index, is 51 live-covered,
67 semantic omissions, 36 navigation/reference pages, and 17 external,
license, sample, or workflow dependencies. The total is 171.

The external-workflow classification does not require downloading or deploying
the roughly 100 GB Warehouse sample bundle. These pages define optional Isaac
Sim, synthetic-data, scene-preparation, calibration, post-processing, and
Sim2Real workflows; the bundle remains outside the local Thor parity boundary.

## Crawl policy and fixed point

The capture accepted only HTTPS links on the exact host `docs.nvidia.com`, under
the exact path prefix `/vss/3.2.1/`, ending in `.html`. It collected `href`
attributes from all elements, stripped query strings and fragments, and excluded
external links and assets. All 172 accepted URLs returned successfully; there
were no fetch failures or redirects.

The stored breadth-first proof is:

| Round | Frontier | New URLs | Total discovered |
| ---: | ---: | ---: | ---: |
| 0 | 1 | 152 | 153 |
| 1 | 152 | 13 | 166 |
| 2 | 13 | 6 | 172 |
| 3 | 6 | 0 | 172 |
| 4 | 0 | 0 | 172 |

Round 4 is the explicit empty-frontier fixed point. `crawl-graph.json` stores an
indexed adjacency list for every reachable page, allowing the traversal and edge
hash to be recomputed without network access.

Reachability proves denominator membership, not semantic implementation. Every
added record therefore sets `semantic_proof_from_crawl_reachability` to `false`.
The exact reviewed 8/9/2 classification is pinned both in
`recursive-coverage.json` and in the validator.

## Files

- `recursive-targets.json`: exact sorted 172-URL set, policy, counts, and canonical
  set hashes. Its stable shape lets later candidates, including Agent Smart City,
  bind their documentation sources to the recursive denominator.
- `crawl-graph.json`: successful-fetch facts, complete indexed adjacency, edge
  hash, depth distribution, and fixed-point rounds.
- `recursive-coverage.json`: comparison with the committed direct-index package,
  live ledger binding, all 19 classifications, and Agent Smart City corrections.
- `*.schema.json`: closed JSON Schemas; unknown fields are rejected.
- `validate_recursive_coverage.py`: default offline validator.
- `tests/test_recursive_coverage.py`: positive and fail-closed mutation tests.
- `evidence.md`: hashes, bindings, and review conclusions.

## Offline verification

From the repository root:

```bash
python3 deploy/docker/thor-local/parity/candidates/wave3/recursive-coverage/validate_recursive_coverage.py --report
python3 -m unittest discover -s deploy/docker/thor-local/parity/candidates/wave3/recursive-coverage/tests -v
```

The validator performs no HTTP, socket, container, model, sample-bundle, or GPU
operation. It validates schemas, file bindings, canonical URL and edge hashes,
reachability, fixed-point rounds, category membership, live-ledger absence, and
Agent Smart City URL corrections entirely from repository files.
