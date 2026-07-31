# Thor-local domain packs

Domain packs are declarative, offline-safe tradeshow configurations. Each JSON
file uses schema version `1` and controls only:

- runtime UI title and subtitle;
- operator terminology and curated demo/search prompts shown by the CLI;
- candidate-verification prompts applied through the local Alert Bridge.

They do not change models, analytics pipelines, search indexes, network access,
or video retention. Terminology is operator guidance; it does not silently
rename API fields or stored data.

## Schema

The filename must match `id`. IDs use lower-case letters, digits, and hyphens.
Unknown keys fail validation. `demo_questions` and `search_prompts` each contain
one to eight single-line strings. Every verification rule has a normalized
`alert_type`, prompts, an optional output label, and:

```json
"vlm_params": { "num_frames": 4 }
```

`num_frames` must be an integer from `1` through `4`, matching the default
local Qwen VLM admission contract. A pack may contain at most eight rules.

Validate every versioned pack without starting containers or accessing a
network:

```bash
python3 deploy/docker/thor-local/domain-packs/domain_pack.py validate
```

Use `thor-local.sh domain show <id>` to review the human-facing result. Applying
a pack requires the local Alert Bridge because rule seeds are synchronized at
apply time. The helper validates that the API URL is loopback-only.

## Ownership and idempotence

The launcher records managed rule payloads in
`deploy/docker/thor-local/.domain-pack-state.json` and the current selection in
`.domain-pack-current`. Both are gitignored, current-user owned, and mode
`0600`. A repeat apply makes no rule or container change when the effective
configuration already matches.

An existing exact match can be adopted. An existing different rule is treated
as operator-owned and preserved. Once a managed rule is edited outside the
launcher it is also preserved and relinquished. This deliberately favors an
operator's work over a domain-pack default.
