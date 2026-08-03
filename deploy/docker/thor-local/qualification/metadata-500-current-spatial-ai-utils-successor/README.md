# Reviewed SpatialAI Metadata Promotion

This package performs the reviewed, deterministic Metadata-289/500 promotion
for the seven provider-free SpatialAI utility capabilities (`00` through `06`).
The external AWS/GCS capability (`07`) is deliberately unchanged and no
Warehouse sample bundle is used.

`authoritative-integrated-receipt.json` is the immutable outer authority. The
compiler extracts its byte-bound producer receipt, validates the captured Git
checkout and every producer-lock source, and publishes exact post-state
documents. It preserves all 211 Metadata-500 suffix rows and all capability
identities and ordering.

Run the checked derivation with:

```bash
python deploy/docker/thor-local/qualification/metadata-500-current-spatial-ai-utils-successor/compiler.py
```

`--write` regenerates package outputs for review. `--install-canonical`
publishes only from exact checked outputs and accepts only a recognized complete
pre-state, complete post-state, or repairable exact partial state.
