# Manifest 500 aggregate successor

This is an isolated, static candidate package. It reconciles feature-family status fields against the settled 500-capability ledger without editing the live parity manifest, running containers, using the network, loading models, or staging the optional Warehouse sample bundle.

The corrected live capability reducer reports six family-status differences. The preceding reducer reported nine because it did not preserve `external_optional` family boundaries; those legacy results for `alert-notifications-slack`, `helm`, and `enterprise-rag` are retained only as regression diagnostics. The checked artifact applies the six current-live changes and preserves those three external boundaries.

The six applied fields are:

- `video-summarization-live.thor_state`: `partial` → `wired`
- `rt-vlm-media.thor_state`: `partial` → `wired`
- `vios-codecs-audio.thor_state`: `wired` → `partial`
- `audio-understanding.runtime_state`: `blocked` → `not_qualified`
- `vios-ui.thor_state`: `wired` → `partial`
- `agent-and-mcp-apis.thor_state`: `wired` → `partial`

The proof keeps three categories separate:

- current live reducer drift: six before, zero after;
- legacy reducer regression diagnostics: nine before and exactly the three preserved external families after;
- acceptance coverage: eight gaps remain open and are the sole remaining blocker category.

The projected manifest preserves every root field, feature and skill order, capability-ID array, and every feature field except the exact six scalars above. Both generated schemas are deliberately exact-value schemas: any feature/skill reorder, identity substitution, capability-ID reorder, valid-enum scalar mutation, or reordered, duplicated, omitted, replaced, or mutated proof row is invalid.

Run:

```bash
python3 deploy/docker/thor-local/qualification/manifest-500-aggregate-successor/compiler.py --check
pytest -q deploy/docker/thor-local/qualification/manifest-500-aggregate-successor/tests
```

`--write` deterministically regenerates only this package's `projected-manifest.json` and `projection.json`.
