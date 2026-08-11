# Current Search semantic runtime qualification

This package closes the backend semantic gap for
`runtime.agent.search-profile` on the Thor-local VSS 3.2.1 profile. It
supersedes the non-promoting, operator-preprovisioned fixture proposal in
`search-semantic-runtime-evidence-successor`; it does not replace the separate
browser qualification for `runtime.ui.search-tab`.

The default command is inert:

```bash
python3 executor.py plan
```

An authorized live run uses the fixed receipt location and an explicit,
plain run identifier:

```bash
python3 executor.py execute-http \
  --run-id thorsearchYYYYMMDDa \
  --ack I_ACK_SEARCH_CURRENT_RUNTIME_AND_EXACT_INDEX_CLEANUP
```

The executor admits only the current local Search, Elasticsearch, analytics
ingress, and locally bindable RT-CV endpoints. Ambient proxies and redirects
are disabled. It does not call the VSS Agent `/generate` route, add or remove a
VIOS/RT-CV stream, change service lifecycle state, access the warehouse sample,
or write to the existing video-embedding index.

The live fixture uses one already-recorded local video and creates only the
otherwise-absent fixed behavior/raw index pair. It captures each index UUID,
writes three behavior documents and one raw frame, exercises the API, then
deletes an index only when both its UUID and complete document-ID inventory
match the executor-owned set. A foreign-document boundary falls back to exact
owned-document deletion and makes the run non-promotable.

Retained evidence contains only source/artifact digests, response digests and
sizes, counts, boolean semantic outcomes, and bounded scores. It contains no
raw prompt, vector, response, URL, sensor/stream/object identifier, credential,
or request/session identifier.

Validate the retained package offline with:

```bash
python3 verify.py
python3 build_capability_evidence.py
pytest -q tests
```

The retained run is described in `EVIDENCE.md` and summarized by
`official-runtime-evidence.json`. The separate
`canonical-runtime-evidence.json` is the deterministic, oracle-shaped
projection consumed by the canonical capability ledger; its builder first
re-runs the sealed package verifier.
